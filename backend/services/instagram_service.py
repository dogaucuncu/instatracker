import time
import random
import logging
from functools import wraps
from typing import Optional
from pathlib import Path

from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    UserNotFound,
    ClientError,
    ClientLoginRequired,
    ClientThrottledError,
    FeedbackRequired,
    PleaseWaitFewMinutes,
    PrivateError,
    RateLimitError,
)

from services.ig_client import HardenedClient
from config import (
    SESSION_FILE,
    MIN_DELAY,
    MAX_DELAY,
    SCAN_MIN_DELAY,
    SCAN_MAX_DELAY,
    SCAN_PAUSE_EVERY_PAGES,
    SCAN_PAUSE_MIN_DELAY,
    SCAN_PAUSE_MAX_DELAY,
    FRIENDSHIP_PAGE_SIZE,
    MAX_FRIENDSHIP_PAGES,
    LOGIN_MIN_DELAY,
    LOGIN_MAX_DELAY,
    IG_DEVICE,
    IG_LOCALE,
    IG_COUNTRY,
    IG_COUNTRY_CODE,
    IG_TIMEZONE_OFFSET,
)

logger = logging.getLogger(__name__)

# Instagram telling us to stop, or that the session is no longer valid. Never
# swallow these: continuing past one is how a soft throttle becomes a multi-day
# restriction.
FATAL_SCAN_ERRORS = (
    PleaseWaitFewMinutes,
    ClientThrottledError,
    RateLimitError,
    FeedbackRequired,
    ChallengeRequired,
    LoginRequired,
)

# Global client instance
_client: Optional[HardenedClient] = None
# Store pending 2FA state
_pending_2fa: dict = {}
# Store pending challenge (device approval) state
_pending_challenge: dict = {}


import json

# device codenames known to be instagrapi's flagged default fingerprint
_LEGACY_DEFAULT_DEVICES = {None, "", "devitron"}


def _apply_ig_profile(cl: HardenedClient) -> None:
    """Apply the stable Turkish-region Android fingerprint to a fresh client.

    Order matters: locale must be set before the user agent is (re)generated,
    otherwise the UA is stamped with instagrapi's default en_US locale.
    """
    cl.set_locale(IG_LOCALE)
    cl.set_country(IG_COUNTRY)
    cl.set_country_code(IG_COUNTRY_CODE)
    cl.set_timezone_offset(IG_TIMEZONE_OFFSET)
    cl.set_device(IG_DEVICE)
    cl.set_user_agent()  # regenerate UA from IG_DEVICE + tr_TR locale


def _new_client() -> HardenedClient:
    """Create a new instagrapi Client with a persistent, realistic device.

    Reusing the same device_id/phone_id/uuid + a real Turkish Android
    fingerprint across sessions makes Instagram treat the client as one
    ordinary, already-known phone instead of a fresh bot on every login.
    """
    # An explicit dict matters: instagrapi's Client(settings={}) default is a
    # mutable class-level default, so without this every client would share
    # (and pollute) the same settings dict.
    cl = HardenedClient(settings={})
    # Interactive auth uses the short delays; scan/per-user functions
    # temporarily switch to their own ranges via _with_delays.
    cl.delay_range = [LOGIN_MIN_DELAY, LOGIN_MAX_DELAY]
    session_path = Path(SESSION_FILE)

    if session_path.exists():
        try:
            settings = json.loads(session_path.read_text())
            device = settings.get("device_settings") or {}
            is_legacy_default = device.get("device") in _LEGACY_DEFAULT_DEVICES
            # Only load device fingerprint fields, NOT auth/session tokens.
            # "mid" belongs here too: it is Instagram's machine id for this
            # install, so dropping it on every password login would make the
            # phone look brand new no matter how stable the rest of the
            # fingerprint is.
            device_keys = {
                "uuids", "device_settings", "country", "country_code",
                "locale", "timezone_offset", "user_agent", "mid",
                "ig_www_claim",
            }
            device_settings = {k: v for k, v in settings.items() if k in device_keys}
            if device_settings and not is_legacy_default:
                cl.set_settings(device_settings)
                logger.info("Loaded persisted device (device_id=%s)", cl.android_device_id)
                return cl
            if is_legacy_default:
                logger.info("Legacy default fingerprint detected — upgrading to Turkish Android profile.")
        except Exception as e:
            logger.warning("Failed to load device settings: %s", e)

    # First run (or legacy upgrade): seed the realistic profile and persist it.
    _apply_ig_profile(cl)
    try:
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_text(json.dumps(cl.get_settings(), indent=4))
        logger.info("Seeded Turkish Android fingerprint (device_id=%s)", cl.android_device_id)
    except Exception as e:
        logger.warning("Failed to save initial device settings: %s", e)

    return cl


def get_client() -> Optional[HardenedClient]:
    return _client


def is_logged_in() -> bool:
    if _client is None:
        return False
    # If we have a user_id and authorization, consider logged in
    # even if account_info() fails due to Checkpoint
    if _client.user_id and _client.authorization:
        return True
    try:
        account = _client.account_info()
        return account is not None
    except Exception:
        return False


def load_session() -> bool:
    """Reuse a saved session WITHOUT re-entering the password.

    Repeated password logins are one of Instagram's strongest bot signals, so
    on startup we load the saved auth token and merely validate it with a single
    lightweight timeline request (exactly what the real app does when opened).
    We never delete the session file here: even when the auth token has expired,
    the persisted device fingerprint must survive so the next password login
    comes from the same, already-known device.
    """
    global _client
    if not SESSION_FILE.exists():
        return False
    try:
        cl = HardenedClient(settings={})
        cl.delay_range = [LOGIN_MIN_DELAY, LOGIN_MAX_DELAY]
        cl.load_settings(str(SESSION_FILE))
        if (cl.device_settings or {}).get("device") in _LEGACY_DEFAULT_DEVICES:
            # Old session tied to instagrapi's flagged default device — force a
            # fresh login so it is reseeded on the realistic Turkish fingerprint.
            logger.info("Saved session uses legacy default device; forcing re-login to upgrade fingerprint.")
            return False
        if not cl.user_id:
            # Only a device fingerprint was saved, no auth token yet.
            logger.info("Saved session has no auth token; password login required.")
            return False
        # Validate the token without touching username/password. This is a warm
        # start of the app, not a cold one — the feed is the first screen.
        cl.reset_navigation()
        cl.navigate("feed_timeline")
        cl.get_timeline_feed("warm_start_fetch")
        _client = cl
        logger.info("Session reused for user_id=%s (no re-login).", cl.user_id)
        return True
    except LoginRequired:
        logger.info("Saved session expired; password login required (device kept).")
        return False
    except Exception as e:
        logger.warning("Failed to reuse session: %s", e)
        return False


def login(username: str, password: str) -> dict:
    """
    Login to Instagram.
    Returns:
        {"status": "ok"} on success
        {"status": "2fa_required"} on code-based 2FA (SMS/TOTP)
        {"status": "challenge_required", "challenge_type": "device"} on device approval
        {"status": "error", "message": ...} on failure
    """
    global _client, _pending_2fa, _pending_challenge
    cl = _new_client()
    try:
        cl.login(username, password)
        _client = cl
        _save_session()
        return {"status": "ok"}
    except TwoFactorRequired as e:
        # Check 2FA method — device approval or code-based?
        two_factor_info = {}
        if hasattr(e, "two_factor_info"):
            two_factor_info = e.two_factor_info or {}
        elif hasattr(cl, "last_json") and cl.last_json:
            two_factor_info = cl.last_json.get("two_factor_info", {})

        logger.info("TwoFactorRequired for @%s — info: %s", username, two_factor_info)

        # Check if any code-based method is available
        has_sms   = bool(two_factor_info.get("sms_two_factor_on"))
        has_totp  = bool(two_factor_info.get("totp_two_factor_on"))
        has_wp    = bool(two_factor_info.get("whatsapp_two_factor_on"))
        has_code  = has_sms or has_totp or has_wp

        _pending_2fa = {
            "client": cl,
            "username": username,
            "password": password,
            "two_factor_info": two_factor_info,
            "has_code": has_code,
        }
        # Also store in pending_challenge so retry_challenge works too
        _pending_challenge = {
            "client": cl,
            "username": username,
            "password": password,
        }

        if has_code:
            # Trigger SMS if available, so user gets the code automatically
            if has_sms:
                try:
                    identifier = two_factor_info.get("two_factor_identifier")
                    if identifier:
                        cl.private_request("accounts/send_two_factor_login_sms/", {
                            "two_factor_identifier": identifier,
                            "username": username,
                            "device_id": cl.android_device_id,
                            "_csrftoken": cl.token,
                        })
                        logger.info("SMS automatically triggered for @%s", username)
                except Exception as ex:
                    logger.warning("Failed to auto-trigger SMS: %s", ex)
                    
            return {
                "status": "2fa_required",
                "has_sms": has_sms,
                "has_totp": has_totp,
            }
        else:
            # No code method — likely device push approval only
            return {
                "status": "challenge_required",
                "challenge_type": "device",
                "message": "Instagram başka bir cihazdan onay istiyor. Telefonunuzdaki Instagram bildirimini onaylayın, ardından 'Devam Et' butonuna basın.",
            }

    except ChallengeRequired as e:
        _pending_challenge = {
            "client": cl,
            "username": username,
            "password": password,
        }
        logger.info("ChallengeRequired for @%s", username)
        return {
            "status": "challenge_required",
            "challenge_type": "device",
            "message": "Instagram başka bir cihazdan onay istiyor. Telefonunuzdaki Instagram bildirimini onaylayın, ardından 'Devam Et' butonuna basın.",
        }
    except Exception as e:
        logger.error("Login error: %s", e)
        return {"status": "error", "message": str(e)}


def verify_2fa(code: str) -> dict:
    """Complete code-based 2FA verification (SMS/TOTP code)."""
    global _client, _pending_2fa, _pending_challenge
    if not _pending_2fa:
        return {"status": "error", "message": "Bekleyen 2FA işlemi yok."}
    cl = _pending_2fa["client"]
    username = _pending_2fa["username"]
    try:
        two_factor_info = _pending_2fa.get("two_factor_info", {})
        identifier = two_factor_info.get("two_factor_identifier")
        
        # If user has TOTP, method is 3. If SMS, method is 1.
        method = "3" if two_factor_info.get("totp_two_factor_on") else "1"
        
        import uuid
        data = {
            "verification_code": code.strip(),
            "phone_id": cl.phone_id,
            "_csrftoken": cl.token,
            "two_factor_identifier": identifier,
            "username": username,
            "trust_this_device": "1",
            "guid": cl.uuid,
            "device_id": cl.android_device_id,
            "waterfall_id": str(uuid.uuid4()),
            "verification_method": method,
        }
        
        cl.private_request("accounts/two_factor_login/", data, login=True)
        auth_header = cl.last_response.headers.get("ig-set-authorization")
        if auth_header:
            cl.authorization_data = cl.parse_authorization(auth_header)
        
        cl.last_login = time.time()
        
        # Save session BEFORE login_flow — the auth token is already valid
        _client = cl
        _pending_2fa = {}
        _pending_challenge = {}
        _save_session()
        logger.info("2FA login successful for @%s", username)
        
        # login_flow() is optional housekeeping (fetches feed, syncs features).
        # On new devices Instagram often triggers a Checkpoint here, which
        # causes JSONDecodeError. The session is already valid, so we can
        # safely ignore that error.
        try:
            cl.login_flow()
        except Exception as flow_err:
            logger.warning("login_flow() failed (session is still valid): %s", flow_err)
        
        return {"status": "ok"}
    except Exception as e:
        response_text = getattr(cl.last_response, 'text', '') if hasattr(cl, 'last_response') else ''
        logger.error("2FA code error for @%s: %s | Response: %s", username, e, response_text)
        return {"status": "error", "message": "Doğrulama kodu hatalı veya süresi dolmuş. Lütfen tekrar deneyin."}


def retry_challenge() -> dict:
    """
    Retry login after user has approved the device challenge/notification.
    Works for BOTH ChallengeRequired AND TwoFactorRequired with device approval.
    """
    global _client, _pending_challenge, _pending_2fa

    if _pending_2fa and _pending_2fa.get("two_factor_info", {}).get("pending_trusted_notification"):
        # This was a 2FA push notification approval
        cl = _pending_2fa["client"]
        username = _pending_2fa["username"]
        info = _pending_2fa["two_factor_info"]
        
        logger.info("Checking trusted notification status for @%s", username)
        try:
            # Poll the trusted notification status
            nonce = info.get("trusted_notification_polling_nonce")
            identifier = info.get("two_factor_identifier")
            
            if nonce and identifier:
                data = {
                    "two_factor_identifier": identifier,
                    "username": username,
                    "device_id": cl.android_device_id,
                    "trusted_notification_polling_nonces": f'["{nonce}"]',
                }
                res = cl.private_request("two_factor/check_trusted_notification_status/", data)
                logger.info("check_trusted_notification_status response: %s", res)
                
                if res.get("review_status") == 1:
                    logger.info("Trusted notification approved — finalizing session.")
                    
                    auth_header = cl.last_response.headers.get("ig-set-authorization")
                    logger.info("Auth header after approval: %s", auth_header[:20] if auth_header else "None")
                    
                    if auth_header:
                        cl.authorization_data = cl.parse_authorization(auth_header)
                    
                    # Check if client already has auth set (instagrapi may have set it)
                    if cl.authorization or auth_header or res.get("logged_in_user"):
                        cl.last_login = time.time()
                        _client = cl
                        _pending_2fa = {}
                        _pending_challenge = {}
                        _save_session()
                        logger.info("Session saved directly from push approval.")
                        try:
                            cl.login_flow()
                        except Exception as flow_err:
                            logger.warning("login_flow() after push approval failed (session still valid): %s", flow_err)
                        return {"status": "ok"}
                    
                    # No auth token yet — finalize via two_factor_login with verification_method=4
                    # This is the "device notification approval" method
                    import uuid
                    for attempt_method in ["4", None]:
                        try:
                            login_data = {
                                "phone_id": cl.phone_id,
                                "_csrftoken": cl.token,
                                "two_factor_identifier": identifier,
                                "username": username,
                                "trust_this_device": "1",
                                "guid": cl.uuid,
                                "device_id": cl.android_device_id,
                                "waterfall_id": str(uuid.uuid4()),
                                "trusted_notification_polling_nonces": f'["{nonce}"]',
                            }
                            if attempt_method:
                                login_data["verification_method"] = attempt_method
                                login_data["verification_code"] = ""
                            
                            logger.info("Trying two_factor_login with method=%s", attempt_method)
                            cl.private_request("accounts/two_factor_login/", login_data, login=True)
                            auth_header = cl.last_response.headers.get("ig-set-authorization")
                            if auth_header:
                                cl.authorization_data = cl.parse_authorization(auth_header)
                            cl.last_login = time.time()
                            _client = cl
                            _pending_2fa = {}
                            _pending_challenge = {}
                            _save_session()
                            logger.info("two_factor_login (method=%s) succeeded!", attempt_method)
                            try:
                                cl.login_flow()
                            except Exception as flow_err:
                                logger.warning("login_flow() failed (session valid): %s", flow_err)
                            return {"status": "ok"}
                        except Exception as e:
                            logger.warning("two_factor_login method=%s failed: %s", attempt_method, e)
                    
                    # Both attempts failed — fall back to SMS
                    logger.info("Push login failed, falling back to SMS.")
                    try:
                        cl.private_request("accounts/send_two_factor_login_sms/", {
                            "two_factor_identifier": identifier,
                            "username": username,
                            "device_id": cl.android_device_id,
                            "_csrftoken": cl.token,
                        })
                        logger.info("SMS triggered as fallback for @%s", username)
                    except Exception as sms_err:
                        logger.warning("Could not trigger SMS: %s", sms_err)
                    return {
                        "status": "2fa_required",
                        "has_sms": bool(info.get("sms_two_factor_on")),
                        "has_totp": bool(info.get("totp_two_factor_on")),
                        "message": "Bildirim onaylandı ama son adım için SMS koduna ihtiyaç var. Lütfen telefonunuza gelen SMS kodunu girin.",
                    }
                else:
                    return {
                        "status": "challenge_still_pending",
                        "message": "Instagram henüz onaylamadı. Lütfen Instagram uygulamanızdan bildirimi onaylayıp tekrar deneyin.",
                    }
        except Exception as e:
            logger.error("Error checking trusted notification: %s", e)
            return {
                "status": "error",
                "message": "Bağlantı hatası veya oturum zaman aşımına uğradı. Lütfen SMS kodu girerek veya baştan deneyin."
            }

    # If it's a simple ChallengeRequired without 2FA info, we can retry the login
    if not _pending_challenge:
        return {"status": "error", "message": "Bekleyen onay işlemi yok. Lütfen tekrar giriş yapmayı deneyin."}

    cl       = _pending_challenge["client"]
    username = _pending_challenge["username"]
    password = _pending_challenge["password"]

    logger.info("Retrying login after device approval for @%s", username)

    try:
        cl.login(username, password)
        _client = cl
        _pending_challenge = {}
        _pending_2fa = {}
        _save_session()
        logger.info("Device approval login successful for @%s", username)
        return {"status": "ok"}
    except TwoFactorRequired as e:
        _pending_2fa = {
            "client": cl,
            "username": username,
            "password": password,
            "two_factor_info": e.two_factor_info if hasattr(e, "two_factor_info") else {},
        }
        _pending_challenge = {}
        return {"status": "2fa_required"}
    except ChallengeRequired:
        # Do NOT create a new client or retry login — that sends duplicate notifications
        return {
            "status": "challenge_still_pending",
            "message": "Instagram henüz onaylamadı. Telefonunuzdan bildirimi onayladıktan sonra birkaç saniye bekleyip tekrar deneyin.",
        }
    except Exception as e:
        logger.error("Challenge retry error: %s", e)
        return {"status": "error", "message": str(e)}


def logout():
    """Logout and clear session."""
    global _client
    if _client:
        try:
            _client.logout()
        except Exception:
            pass
        _client = None
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _save_session():
    if _client:
        _client.dump_settings(str(SESSION_FILE))
        logger.info("Session saved to %s", SESSION_FILE)


def get_account_info() -> dict:
    if not _client:
        raise RuntimeError("Not logged in")
    info = _client.account_info()
    return {
        "pk": str(info.pk),
        "username": info.username,
        "full_name": info.full_name,
        "profile_pic_url": str(info.profile_pic_url) if info.profile_pic_url else None,
    }


def _with_delays(min_delay: float, max_delay: float):
    """Run an Instagram operation with the given anti-bot delay_range.

    The client's default delay_range is the short login one (interactive auth
    must feel responsive). List pagination uses the moderate scan pacing, and
    the sensitive per-user requests (status checks, unfollows) use the long
    one. instagrapi sleeps this range before EVERY request, so no extra
    explicit sleeps are needed on top.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if _client is None:
                return func(*args, **kwargs)  # let the function raise "Not logged in"
            previous = _client.delay_range
            _client.delay_range = [min_delay, max_delay]
            try:
                return func(*args, **kwargs)
            finally:
                _client.delay_range = previous
        return wrapper
    return decorator


def open_app() -> None:
    """Load the timeline the way the app does when it is brought to the front.

    A scan that opens with `friendships/<id>/followers/` as its very first
    request looks nothing like a person using Instagram; a real session always
    starts on the feed.

    This doubles as a canary: if Instagram is already throttling or challenging
    the account, it says so here, on one cheap request, and the caller must not
    go on to enumerate the entire follower list.
    """
    if not _client:
        raise RuntimeError("Not logged in")
    _client.reset_navigation()
    _client.navigate("feed_timeline")
    try:
        _client.get_timeline_feed("warm_start_fetch")
    except FATAL_SCAN_ERRORS:
        raise
    except Exception as e:
        # Anything else here is cosmetic — a slow or empty feed is no reason to
        # abandon a scan.
        logger.warning("Timeline warm-up failed (continuing): %s", e)


def _page_pause(page_index: int) -> None:
    """Idle the way a person scrolling a long list does."""
    if SCAN_PAUSE_EVERY_PAGES and page_index % SCAN_PAUSE_EVERY_PAGES == 0:
        pause = random.uniform(SCAN_PAUSE_MIN_DELAY, SCAN_PAUSE_MAX_DELAY)
        logger.info("Pausing %.1fs after %d pages", pause, page_index)
        time.sleep(pause)


def _extract_user(raw: dict) -> Optional[dict]:
    """Pull the four fields we store out of a raw v1 user object.

    Read straight from the JSON rather than through instagrapi's pydantic
    models: a single unusual account in the list would otherwise raise a
    validation error and lose the entire page.
    """
    pk = next(
        (raw[key] for key in ("pk", "pk_id", "id") if raw.get(key) is not None),
        None,
    )
    username = raw.get("username")
    if pk is None or pk == "" or not username:
        return None
    return {
        "pk": str(pk),
        "username": username,
        "full_name": raw.get("full_name") or "",
        "profile_pic_url": raw.get("profile_pic_url"),
    }


def _fetch_friendship_list(kind: str) -> list[dict]:
    """Page through followers/following on the private mobile API.

    This deliberately does not use instagrapi's `user_followers_v1` helper and
    has no web-API fallback. The helper returns a *list*, but the old code here
    treated it as a dict of pk -> user; the resulting AttributeError was
    swallowed by a broad `except`, so every scan silently paginated the whole
    list twice — once over the mobile API, then again over the logged-out web
    GraphQL endpoint with the mobile session cookie injected into a 2018
    desktop-Safari user agent, retrying each dead query hash up to nine times.
    That mismatched double enumeration is what earned the account its
    "Daha Sonra Tekrar Dene" restrictions.
    """
    if not _client:
        raise RuntimeError("Not logged in")

    _client.navigate(f"self_{kind}")

    users: list[dict] = []
    seen: set[str] = set()
    seen_cursors: set[str] = set()
    max_id = ""
    page = 0

    while page < MAX_FRIENDSHIP_PAGES:
        result = _client.private_request(
            f"friendships/{_client.user_id}/{kind}/",
            params={
                "max_id": max_id,
                "count": FRIENDSHIP_PAGE_SIZE,
                "rank_token": _client.rank_token,
                "search_surface": "follow_list_page",
                "query": "",
                "enable_groups": "true",
            },
        )
        page += 1

        for raw in result.get("users") or []:
            user = _extract_user(raw)
            if user and user["pk"] not in seen:
                seen.add(user["pk"])
                users.append(user)

        max_id = result.get("next_max_id")
        if not max_id:
            break
        # A cursor we have already followed means the server is looping us.
        # Without this the dedup above hides it: `users` stops growing while we
        # keep re-requesting the same page forever.
        max_id = str(max_id)
        if max_id in seen_cursors:
            logger.warning(
                "Repeated %s cursor after %d page(s) — stopping pagination.", kind, page
            )
            break
        seen_cursors.add(max_id)
        _page_pause(page)
    else:
        logger.warning(
            "Hit the %d-page cap while fetching %s; list may be incomplete.",
            MAX_FRIENDSHIP_PAGES, kind,
        )

    logger.info("Fetched %d %s across %d page(s)", len(users), kind, page)
    return users


@_with_delays(SCAN_MIN_DELAY, SCAN_MAX_DELAY)
def get_followers() -> list[dict]:
    """Fetch the full follower list from the private mobile API."""
    return _fetch_friendship_list("followers")


@_with_delays(SCAN_MIN_DELAY, SCAN_MAX_DELAY)
def get_following() -> list[dict]:
    """Fetch the full following list from the private mobile API."""
    return _fetch_friendship_list("following")


@_with_delays(MIN_DELAY, MAX_DELAY)
def check_user_status(user_pk: str, username: str) -> str:
    """
    Check whether a user exists and is accessible.
    Returns: 'active' | 'blocked' | 'deactivated'

    Uses `user_info_v1` rather than `user_info`, because the latter tries the
    logged-out web GraphQL API first and, when that fails, injects the mobile
    session id into the web session to retry — two extra requests per checked
    user, on a surface this account has no business touching.

    Known limitation: over the mobile API alone, a user who blocked us and a
    user whose account no longer exists are indistinguishable — both answer 404
    on `users/<pk>/info/`. Telling them apart needs a logged-out profile fetch,
    which is exactly the web-API mixing that gets this account restricted, so
    both are reported as 'deactivated'. 'blocked' is still reached for accounts
    that went private on us, which the API does report distinctly.
    """
    if not _client:
        raise RuntimeError("Not logged in")
    _client.navigate("profile")
    try:
        info = _client.user_info_v1(int(user_pk))
        if info:
            return "active"
        return "active"
    except UserNotFound:
        return "deactivated"
    except PrivateError:
        # Private account that blocked us or we can't see
        return "blocked"
    except ClientLoginRequired:
        return "blocked"
    except ClientError as e:
        msg = str(e).lower()
        if "not found" in msg or "doesn't exist" in msg:
            return "deactivated"
        if "private" in msg or "forbidden" in msg or "login" in msg:
            return "blocked"
        logger.warning("Unknown status for %s (%s): %s", username, user_pk, e)
        return "active"
    except Exception as e:
        logger.warning("Error checking user %s: %s", username, e)
        return "active"


@_with_delays(MIN_DELAY, MAX_DELAY)
def unfollow_user(user_pk: str) -> bool:
    """Unfollow a user by pk. Returns True on success."""
    if not _client:
        raise RuntimeError("Not logged in")
    try:
        result = _client.user_unfollow(int(user_pk))
        return result
    except Exception as e:
        logger.error("Error unfollowing %s: %s", user_pk, e)
        return False
