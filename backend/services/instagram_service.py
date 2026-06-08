import time
import random
import logging
from typing import Optional
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    UserNotFound,
    ClientError,
    ClientLoginRequired,
    PrivateError,
)

from config import SESSION_FILE, MIN_DELAY, MAX_DELAY

logger = logging.getLogger(__name__)

# Global client instance
_client: Optional[Client] = None
# Store pending 2FA state
_pending_2fa: dict = {}
# Store pending challenge (device approval) state
_pending_challenge: dict = {}


import json

def _new_client() -> Client:
    """Create a new instagrapi Client with persistent device settings.
    
    Reusing the same device_id/phone_id/uuid across sessions prevents
    Instagram from flagging each login as a 'new device'.
    """
    cl = Client()
    cl.delay_range = [MIN_DELAY, MAX_DELAY]
    session_path = Path(SESSION_FILE)
    if session_path.exists():
        try:
            settings = json.loads(session_path.read_text())
            # Only load device fingerprint fields, NOT auth/session tokens
            device_keys = {"uuids", "device_settings", "country", "locale", "timezone_offset", "user_agent"}
            device_settings = {k: v for k, v in settings.items() if k in device_keys}
            if device_settings:
                cl.set_settings(device_settings)
            logger.info("Loaded device settings (device_id=%s)", cl.android_device_id)
        except Exception as e:
            logger.warning("Failed to load device settings: %s", e)
    else:
        # First run: save newly generated device settings so they persist
        try:
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(json.dumps(cl.get_settings()))
            logger.info("Saved initial device settings (device_id=%s)", cl.android_device_id)
        except Exception as e:
            logger.warning("Failed to save initial device settings: %s", e)
            
    return cl


def _random_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def get_client() -> Optional[Client]:
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
    """Try to load a saved session. Returns True if successful."""
    global _client
    if not SESSION_FILE.exists():
        return False
    try:
        cl = _new_client()
        cl.load_settings(str(SESSION_FILE))
        cl.login(cl.username, cl.password)
        _client = cl
        logger.info("Session loaded successfully for @%s", cl.username)
        return True
    except Exception as e:
        logger.warning("Failed to load session: %s", e)
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        _client = None
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


def get_followers() -> list[dict]:
    """
    Fetch the full follower list.
    Primary strategy: v1 API (200 per page, more reliable).
    Fallback: GraphQL (if v1 returns suspiciously few results).
    """
    if not _client:
        raise RuntimeError("Not logged in")

    user_id = _client.user_id
    logger.info("Fetching followers via v1 API...")

    # ── Primary: v1 API ──────────────────────────────────────────────────
    try:
        users_map = _client.user_followers_v1(user_id, amount=0)  # 0 = all
        result = [
            {
                "pk": str(pk),
                "username": u.username,
                "full_name": u.full_name or "",
                "profile_pic_url": str(u.profile_pic_url) if u.profile_pic_url else None,
            }
            for pk, u in users_map.items()
        ]
        logger.info("Fetched %d followers via v1 API", len(result))
        return result
    except Exception as e:
        logger.warning("v1 followers fetch failed, falling back to GraphQL: %s", e)

    # ── Fallback: GraphQL ────────────────────────────────────────────────
    try:
        _client.inject_sessionid_to_public()
    except Exception:
        pass

    users = []
    variables = {
        "id": str(user_id),
        "include_reel": True,
        "fetch_mutual": False,
        "first": 50,
    }
    end_cursor = None

    while True:
        if end_cursor:
            variables["after"] = end_cursor
        try:
            data = _client.public_graphql_request(
                variables, query_hash="37479f2b8209594dde7facb0d904896a"
            )
        except Exception as e:
            logger.error("GraphQL followers fetch error: %s", e)
            break

        if not data.get("user"):
            break

        edge_followed_by = data["user"].get("edge_followed_by", {})
        page_info = edge_followed_by.get("page_info", {})
        edges = edge_followed_by.get("edges", [])

        for edge in edges:
            if "node" in edge:
                node = edge["node"]
                users.append({
                    "pk": str(node.get("id")),
                    "username": node.get("username"),
                    "full_name": node.get("full_name") or "",
                    "profile_pic_url": node.get("profile_pic_url"),
                })

        end_cursor = page_info.get("end_cursor")
        if not page_info.get("has_next_page") or not end_cursor:
            break

    logger.info("Fetched %d followers via GraphQL (fallback)", len(users))
    return users


def get_following() -> list[dict]:
    """
    Fetch the full following list.
    Primary strategy: v1 API (200 per page, more reliable).
    Fallback: GraphQL (if v1 fails).
    """
    if not _client:
        raise RuntimeError("Not logged in")

    user_id = _client.user_id
    logger.info("Fetching following via v1 API...")

    # ── Primary: v1 API ──────────────────────────────────────────────────
    try:
        users_map = _client.user_following_v1(user_id, amount=0)  # 0 = all
        result = [
            {
                "pk": str(pk),
                "username": u.username,
                "full_name": u.full_name or "",
                "profile_pic_url": str(u.profile_pic_url) if u.profile_pic_url else None,
            }
            for pk, u in users_map.items()
        ]
        logger.info("Fetched %d following via v1 API", len(result))
        return result
    except Exception as e:
        logger.warning("v1 following fetch failed, falling back to GraphQL: %s", e)

    # ── Fallback: GraphQL ────────────────────────────────────────────────
    try:
        _client.inject_sessionid_to_public()
    except Exception:
        pass

    users = []
    variables = {
        "id": str(user_id),
        "include_reel": True,
        "fetch_mutual": False,
        "first": 50,
    }
    end_cursor = None

    while True:
        if end_cursor:
            variables["after"] = end_cursor
        try:
            data = _client.public_graphql_request(
                variables, query_hash="58712303d941c6855d4e888c5f0cd22f"
            )
        except Exception as e:
            logger.error("GraphQL following fetch error: %s", e)
            break

        if not data.get("user"):
            break

        edge_follow = data["user"].get("edge_follow", {})
        page_info = edge_follow.get("page_info", {})
        edges = edge_follow.get("edges", [])

        for edge in edges:
            if "node" in edge:
                node = edge["node"]
                users.append({
                    "pk": str(node.get("id")),
                    "username": node.get("username"),
                    "full_name": node.get("full_name") or "",
                    "profile_pic_url": node.get("profile_pic_url"),
                })

        end_cursor = page_info.get("end_cursor")
        if not page_info.get("has_next_page") or not end_cursor:
            break

    logger.info("Fetched %d following via GraphQL (fallback)", len(users))
    return users


def check_user_status(user_pk: str, username: str) -> str:
    """
    Check whether a user exists and is accessible.
    Returns: 'active' | 'blocked' | 'deactivated'
    """
    if not _client:
        raise RuntimeError("Not logged in")
    _random_delay()
    try:
        info = _client.user_info(int(user_pk))
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


def unfollow_user(user_pk: str) -> bool:
    """Unfollow a user by pk. Returns True on success."""
    if not _client:
        raise RuntimeError("Not logged in")
    try:
        _random_delay()
        result = _client.user_unfollow(int(user_pk))
        return result
    except Exception as e:
        logger.error("Error unfollowing %s: %s", user_pk, e)
        return False
