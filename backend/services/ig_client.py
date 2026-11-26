"""A hardened instagrapi Client.

instagrapi is easy to fingerprint out of the box: several headers it sends on
*every* request are hardcoded constants baked into its source, so they are
byte-identical for every instagrapi user on earth, and a few of them are
outright invalid (signed routing hints copied from one developer's capture,
re-sent with a different account's user id). It also retries automatically when
Instagram answers "429 Too Many Requests", which turns a polite throttle into a
hammering, and it silently falls back to scraping the logged-out web API with
the mobile session cookie injected into a 2018 desktop-Safari user agent.
It verifies TLS against certifi alone, which fails on a machine whose HTTPS
is re-signed locally (an antivirus, a corporate proxy), and it fetches the
login encryption key from an endpoint Instagram has removed, so no login
can complete at all.

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

# Retry policy for both sessions. instagrapi's own default puts 429 in the
# status_forcelist with three attempts, so the moment Instagram tells us to
# slow down, requests immediately fires the same call three more times — the
# exact opposite of backing off, and a fast way to turn a soft throttle into a
# multi-day restriction. Only genuine server errors are worth retrying.
RETRY_STATUSES = [500, 502, 503, 504]
RETRY_TOTAL = 2
RETRY_BACKOFF_FACTOR = 2


def _build_ssl_context() -> ssl.SSLContext:
    """Trust both the bundled CA list and the operating system's own store.

    requests verifies against certifi alone, which fails outright on machines
    where an antivirus or corporate proxy re-signs HTTPS traffic (Norton's
    "Web/Mail Shield", for instance, installs its root into the Windows store,
    not into certifi). Trusting the union of both stores keeps verification
    on without breaking those machines: it is a strict superset of the default
    trust set, so it cannot regress where there is no interception.
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
        self._password_key: tuple[int, str] | None = None

        # instagrapi declares `Client(settings: dict = {})` — a mutable default
        # shared by the class. Left alone, two clients built with no arguments
        # would write their device fingerprints into the same dict and inherit
        # each other's uuids.
        super().__init__(settings if settings is not None else {}, *args, **kwargs)
        self._harden_transport()

    # ── Transport ────────────────────────────────────────────────────────────

    def _harden_transport(self) -> None:
        """Stop auto-retrying throttles and verify certificates properly.

        Called again from init(), because instagrapi rebuilds the private
        session's adapter from its own retry settings every time settings are
        loaded — which would otherwise silently drop the merged trust store and
        put 429 back in the retry list.
        """
        # Keep the library's own knobs in step with ours, so an adapter it
        # rebuilds on its own carries the same policy.
        self.session_retry_total = RETRY_TOTAL
        self.session_retry_backoff_factor = RETRY_BACKOFF_FACTOR
        self.session_retry_statuses = list(RETRY_STATUSES)

        kwargs = dict(
            total=RETRY_TOTAL,
            connect=RETRY_TOTAL,
            read=RETRY_TOTAL,
            status_forcelist=RETRY_STATUSES,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            respect_retry_after_header=True,
        )
        try:
            retry = Retry(allowed_methods=["GET", "POST"], **kwargs)
        except TypeError:  # urllib3 < 1.26
            retry = Retry(method_whitelist=["GET", "POST"], **kwargs)

        # graphql only exists on instagrapi 3.x; it must be hardened too, or a
        # single call through it would bypass the trust store.
        sessions = [self.private, self.public, getattr(self, "graphql", None)]
        for session in sessions:
            if session is None:
                continue
            # One adapter per session: sharing a single instance would put both
            # sessions on the same connection pool, so closing either would tear
            # down connections the other is still using.
            adapter = _TrustStoreAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            # requests verifies against certifi alone, which fails on this
            # machine's re-signed HTTPS; the adapter above fixes that, so
            # verification stays on rather than being switched off.
            session.verify = True

    def init(self) -> bool:
        """Re-apply the transport hardening after every settings load."""
        result = super().init()
        self._harden_transport()
        return result

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
        key_id = incoming.get("ig-set-password-encryption-key-id")
        public_key = incoming.get("ig-set-password-encryption-pub-key")
        if key_id and public_key:
            # Instagram hands the login key out as a response header on ordinary
            # API calls, and rotates it; keep the newest one we were given.
            try:
                self._password_key = (int(key_id), public_key)
            except (TypeError, ValueError):
                logger.warning("Ignoring unreadable password key id %r", key_id)

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

    # ── Login password encryption ────────────────────────────────────────────

    def password_publickeys(self):
        """Return the RSA key Instagram wants the password encrypted with.

        instagrapi fetches it with a GET to /api/v1/qe/sync/. That endpoint is
        gone — Instagram answers "Endpoint /v1/qe/sync/ does not exist" — so
        every login died there with no key and no usable error. The key is in
        fact never fetched on its own: the server attaches
        ig-set-password-encryption-key-id / -pub-key to ordinary API responses,
        and the app uses the last pair it was handed. _absorb_response() keeps
        them, so by the time login() needs the key, pre_login_flow()'s
        launcher/sync call has already supplied it.
        """
        if self._password_key is None:
            # Reached cold (no pre-login call yet, or the key never arrived).
            # launcher/sync is the request the real app's login starts with.
            logger.info("No login key yet; syncing the launcher to obtain one.")
            try:
                self.sync_launcher(True)
            except Exception as e:
                raise ClientError(
                    f"Instagram giriş anahtarı alınamadı ({e}). Giriş şu an yapılamıyor."
                ) from e

        if self._password_key is None:
            # Blocked IP, maintenance, or a response shape we do not know.
            # Without this the caller would see a bare TypeError from int(None).
            raise ClientError(
                "Instagram giriş şifreleme anahtarını vermedi "
                f"(son yanıt HTTP {getattr(self.last_response, 'status_code', '?')}). "
                "Giriş şu an yapılamıyor."
            )
        return self._password_key

    # ── Keep the logged-out web API out of the picture ───────────────────────

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
