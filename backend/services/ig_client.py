"""A hardened instagrapi Client.

instagrapi is easy to fingerprint out of the box: several headers it sends on
*every* request are hardcoded constants baked into its source, so they are
byte-identical for every instagrapi user on earth, and a few of them are
outright invalid (signed routing hints copied from one developer's capture,
re-sent with a different account's user id). It also retries automatically when
Instagram answers "429 Too Many Requests", which turns a polite throttle into a
hammering, and it silently falls back to scraping the logged-out web API with
the mobile session cookie injected into a 2018 desktop-Safari user agent.

This subclass fixes those behaviours. It does not try to make the client
undetectable — it only removes the signals that mark it as a bot rather than as
the phone it claims to be.
"""

import logging
import random
import ssl
import time
import uuid

import certifi
from instagrapi import Client
from instagrapi.exceptions import ClientError
from instagrapi.utils import random_delay
from requests.adapters import HTTPAdapter

try:  # urllib3 ships with requests; keep the vendored path as a fallback
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# The Instagram app keeps one "Pigeon" analytics session per foreground run and
# rotates it after roughly half an hour of use. instagrapi generates a brand new
# one for every single request, which makes each request look like a separate
# app launch.
PIGEON_SESSION_TTL = 30 * 60

# Plausible range for X-IG-Bandwidth-Speed-KBPS (kilobits/s) on a phone with a
# decent wifi link. Used both to seed the value and to clamp the running
# estimate, so a burst of tiny responses cannot report an absurd link speed.
BANDWIDTH_KBPS_RANGE = (2500.0, 30000.0)

# Routing hints the server hands out via ig-set-* response headers. The real app
# echoes whatever it was given back on subsequent requests; it never invents
# them. Keys are lowercase response headers, values are the request headers.
_SERVER_STATE_HEADERS = {
    "ig-set-ig-u-shbid": "IG-U-SHBID",
    "ig-set-ig-u-shbts": "IG-U-SHBTS",
    "ig-set-ig-u-ig-direct-region-hint": "IG-U-IG-DIRECT-REGION-HINT",
}

# instagrapi hardcodes fake values for all of these (see mixins/private.py).
_FORGED_ROUTING_HEADERS = (
    "IG-U-SHBID",
    "IG-U-SHBTS",
    "IG-U-IG-DIRECT-REGION-HINT",
    "IG-U-RUR",
)

# Android fragment names for the surfaces this app actually visits, used to
# build a navigation chain that reflects where we really are.
_NAV_FRAGMENTS = {
    "feed_timeline": "MainFeedFragment",
    "self_profile": "UserDetailFragment",
    "self_followers": "UserListFragment",
    "self_following": "UserListFragment",
    "profile": "UserDetailFragment",
}

# How many navigation steps the app carries along in X-IG-Nav-Chain.
_NAV_CHAIN_DEPTH = 6

_PUBLIC_API_DISABLED = (
    "Logged-out web API (www.instagram.com) is disabled for this client. "
    "Mixing it with the mobile session is what gets accounts rate-limited."
)


def _build_ssl_context() -> ssl.SSLContext:
    """Trust both the bundled CA list and the operating system's own store.

    requests verifies against certifi alone, which fails outright on machines
    where an antivirus or corporate proxy re-signs HTTPS traffic (Norton's
    "Web/Mail Shield", for instance, installs its root into the Windows store,
    not into certifi). That failure is why instagrapi ships with certificate
    checking switched off entirely. Trusting the union of both stores keeps
    verification on without breaking those machines.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        context.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception as e:  # pragma: no cover - platform dependent
        logger.warning("Could not load the OS certificate store: %s", e)
    return context


class _TrustStoreAdapter(HTTPAdapter):
    """HTTPAdapter that verifies against the merged certificate store."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _build_ssl_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = _build_ssl_context()
        return super().proxy_manager_for(*args, **kwargs)


class HardenedClient(Client):
    """instagrapi Client with the bot-shaped defaults removed."""

    def __init__(self, settings: dict = None, *args, **kwargs):
        # These must exist before super().__init__() runs: it calls init(),
        # which builds base_headers, which reads them.
        self._pigeon_session_id = ""
        self._pigeon_started_at = 0.0
        self._salt_ids = str(random.randint(1061162222, 1061262222))
        # Plausible starting values for a phone that has been on wifi a while.
        self._bandwidth_kbps = round(random.uniform(*BANDWIDTH_KBPS_RANGE), 3)
        self._bandwidth_total_bytes = random.randint(3_000_000, 12_000_000)
        self._bandwidth_total_ms = random.randint(4_000, 15_000)
        self._nav_chain: list[str] = []
        self._nav_position = 0
        self._server_state: dict[str, str] = {}

        # instagrapi declares `Client(settings: dict = {})` — a mutable default
        # shared by the class. Left alone, two clients built with no arguments
        # would write their device fingerprints into the same dict and inherit
        # each other's uuids.
        super().__init__(settings if settings is not None else {}, *args, **kwargs)
        self._harden_transport()

    # ── Transport ────────────────────────────────────────────────────────────

    def _harden_transport(self) -> None:
        """Stop auto-retrying throttles and re-enable certificate checking.

        instagrapi's retry policy includes 429 in its status_forcelist with
        three attempts and a backoff factor of 2. So the moment Instagram tells
        us to slow down, requests immediately fires the same call three more
        times — the exact opposite of backing off, and a fast way to escalate a
        soft throttle into a multi-day restriction. Only genuine server errors
        are worth retrying.
        """
        kwargs = dict(
            total=2,
            connect=2,
            read=2,
            status_forcelist=[500, 502, 503, 504],
            backoff_factor=2,
            respect_retry_after_header=True,
        )
        try:
            retry = Retry(allowed_methods=["GET", "POST"], **kwargs)
        except TypeError:  # urllib3 < 1.26
            retry = Retry(method_whitelist=["GET", "POST"], **kwargs)

        for session in (self.private, self.public):
            # One adapter per session: sharing a single instance would put both
            # sessions on the same connection pool, so closing either would tear
            # down connections the other is still using.
            adapter = _TrustStoreAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            # instagrapi disables TLS verification wholesale to dodge an old
            # SSLError; that hands the session cookie to anyone on the path.
            session.verify = True

    # ── Session-stable identifiers ───────────────────────────────────────────

    @property
    def pigeon_session_id(self) -> str:
        now = time.time()
        if not self._pigeon_session_id or now - self._pigeon_started_at > PIGEON_SESSION_TTL:
            self._pigeon_session_id = f"UFS-{uuid.uuid4()}-1"
            self._pigeon_started_at = now
        return self._pigeon_session_id

    # ── Navigation chain ─────────────────────────────────────────────────────

    def navigate(self, module: str) -> None:
        """Record that the "user" moved to another screen.

        instagrapi sends one frozen nav chain (self_profile → media tab →
        self_following) on every request it ever makes, including the login
        call, which is both a constant fingerprint and nonsense for most
        endpoints.
        """
        fragment = _NAV_FRAGMENTS.get(module, "MainFeedFragment")
        self._nav_position += 1
        self._nav_chain.append(f"{fragment}:{module}:{self._nav_position}")
        del self._nav_chain[:-_NAV_CHAIN_DEPTH]

    def reset_navigation(self) -> None:
        """Back to a cold app start (no screens visited yet)."""
        self._nav_chain.clear()
        self._nav_position = 0

    @property
    def nav_chain(self) -> str:
        return ",".join(self._nav_chain)

    # ── Headers ──────────────────────────────────────────────────────────────

    @property
    def base_headers(self) -> dict:
        headers = super().base_headers

        # Drop instagrapi's forged routing hints and re-add only the ones the
        # server actually issued to us.
        for name in _FORGED_ROUTING_HEADERS:
            headers.pop(name, None)
        headers.update(self._server_state)
        if self.ig_u_rur:
            headers["IG-U-RUR"] = self.ig_u_rur
        if self.ig_www_claim:
            headers["X-IG-WWW-Claim"] = self.ig_www_claim

        headers["X-Pigeon-Session-Id"] = self.pigeon_session_id
        headers["X-IG-SALT-IDS"] = self._salt_ids

        # These are cumulative counters on a real device, so they only ever go
        # up. instagrapi re-randomises them per request, which means the phone
        # appears to forget how much data it has used between two calls one
        # second apart.
        headers["X-IG-Bandwidth-Speed-KBPS"] = f"{self._bandwidth_kbps:.3f}"
        headers["X-IG-Bandwidth-TotalBytes-B"] = str(self._bandwidth_total_bytes)
        headers["X-IG-Bandwidth-TotalTime-MS"] = str(self._bandwidth_total_ms)

        nav = self.nav_chain
        if nav:
            headers["X-IG-Nav-Chain"] = nav
        else:
            headers.pop("X-IG-Nav-Chain", None)

        return headers

    # ── Response bookkeeping ─────────────────────────────────────────────────

    def _send_private_request(self, *args, **kwargs):
        try:
            return super()._send_private_request(*args, **kwargs)
        finally:
            self._absorb_response(self.last_response)

    def _absorb_response(self, response) -> None:
        """Remember the routing state the server just handed us."""
        if response is None:
            return
        try:
            incoming = response.headers
        except Exception:
            return

        for source, target in _SERVER_STATE_HEADERS.items():
            value = incoming.get(source)
            if value:
                self._server_state[target] = value

        rur = incoming.get("ig-set-ig-u-rur")
        if rur:
            self.set_ig_u_rur(rur)
        claim = incoming.get("x-ig-set-www-claim")
        if claim:
            self.set_ig_www_claim(claim)
        mid = incoming.get("ig-set-x-mid")
        if mid:
            # instagrapi only picks this up inside _send_private_request, so
            # responses we fetch directly would otherwise lose the machine id.
            self.mid = mid

        self._advance_bandwidth(response)

    def _advance_bandwidth(self, response) -> None:
        try:
            transferred = len(response.content or b"")
            elapsed_ms = max(1, int(response.elapsed.total_seconds() * 1000))
        except Exception:
            return
        self._bandwidth_total_bytes += transferred
        self._bandwidth_total_ms += elapsed_ms
        if not transferred:
            return
        # Kilobits per second, matching the header's name and the scale
        # instagrapi and the real app report on.
        observed = (transferred * 8 / 1000) / (elapsed_ms / 1000)
        # Smooth it the way a rolling client-side estimate would behave, then
        # clamp: a handful of tiny responses would otherwise drag the reported
        # link speed down to a value no phone on wifi would ever send.
        smoothed = self._bandwidth_kbps * 0.8 + observed * 0.2
        low, high = BANDWIDTH_KBPS_RANGE
        self._bandwidth_kbps = round(min(max(smoothed, low), high), 3)

    # ── Keep the logged-out web API out of the picture ───────────────────────

    def password_publickeys(self):
        """Fetch the login public key over the private session.

        instagrapi issues this one request through its *public* session, which
        carries a desktop Safari user agent — so every login is preceded by a
        Mac browser asking i.instagram.com for Android login keys from the same
        IP, seconds before the Android app logs in.
        """
        # private_request() paces every other call; this one goes out through
        # the session directly, so it has to pace itself or the login sequence
        # fires three requests back to back.
        if self.delay_range:
            random_delay(delay_range=self.delay_range)

        headers = self.base_headers
        # pre_login_flow() leaves a POST Content-Type on the session; None tells
        # requests to drop the session-level header for this GET.
        headers["Content-Type"] = None
        response = self.private.get(
            "https://i.instagram.com/api/v1/qe/sync/",
            headers=headers,
            proxies=self.private.proxies,
        )
        self._absorb_response(response)

        key_id = response.headers.get("ig-set-password-encryption-key-id")
        public_key = response.headers.get("ig-set-password-encryption-pub-key")
        if not key_id or not public_key:
            # Blocked IP, a redirect to /login, or maintenance. Without this the
            # caller sees a bare KeyError as its login error message.
            raise ClientError(
                "Instagram did not return the login encryption key "
                f"(HTTP {response.status_code}). Giriş şu an yapılamıyor."
            )
        return int(key_id), public_key

    def public_request(self, *args, **kwargs):
        raise ClientError(_PUBLIC_API_DISABLED)

    def public_a1_request(self, *args, **kwargs):
        raise ClientError(_PUBLIC_API_DISABLED)

    def public_graphql_request(self, *args, **kwargs):
        raise ClientError(_PUBLIC_API_DISABLED)

    def inject_sessionid_to_public(self) -> bool:
        """Never hand the mobile session id to the web surface."""
        logger.debug("Refused to inject the mobile session id into the web session.")
        return False
