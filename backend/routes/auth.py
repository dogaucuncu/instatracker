import logging
from fastapi import APIRouter, HTTPException
from models import LoginRequest, TwoFARequest
from services import instagram_service as ig
import database as db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_and_save_account_info():
    """Try to fetch account info from Instagram. If it fails (e.g. Checkpoint),
    return basic info from the client object."""
    try:
        info = ig.get_account_info()
        db.save_account(
            pk=info["pk"],
            username=info["username"],
            full_name=info["full_name"],
            profile_pic_url=info["profile_pic_url"],
        )
        return info
    except Exception as e:
        logger.warning("get_account_info() failed (likely Checkpoint): %s", e)
        # Fall back to basic info from the client
        cl = ig.get_client()
        if cl and cl.user_id:
            basic = {
                "pk": str(cl.user_id),
                "username": cl.username or "unknown",
                "full_name": "",
                "profile_pic_url": None,
            }
            db.save_account(**basic)
            return basic
        raise


@router.get("/status")
def auth_status():
    """Check if user is currently logged in."""
    account = db.get_account()
    if account and ig.is_logged_in():
        return {
            "logged_in": True,
            "account": account,
        }
    # Try loading session from disk
    if ig.load_session():
        try:
            info = ig.get_account_info()
            db.save_account(
                pk=info["pk"],
                username=info["username"],
                full_name=info["full_name"],
                profile_pic_url=info["profile_pic_url"],
            )
            return {
                "logged_in": True,
                "account": info,
            }
        except Exception:
            pass
    return {"logged_in": False, "account": None}


@router.post("/login")
def login(req: LoginRequest):
    """Login with username and password."""
    if not req.username or not req.password:
        raise HTTPException(400, "Kullanıcı adı ve şifre gerekli.")

    result = ig.login(req.username.strip(), req.password)

    if result["status"] == "ok":
        try:
            info = _get_and_save_account_info()
            return {"status": "ok", "account": info}
        except Exception as e:
            raise HTTPException(500, f"Hesap bilgileri alınamadı: {e}")

    elif result["status"] == "2fa_required":
        return {"status": "2fa_required", "message": "2FA kodu gerekli. Lütfen doğrulama kodunuzu girin."}

    elif result["status"] == "challenge_required":
        # Return 200 so the frontend can show the device-approval UI
        return {
            "status": "challenge_required",
            "challenge_type": result.get("challenge_type", "device"),
            "message": result.get("message", "Instagram güvenlik doğrulaması gerekiyor."),
        }

    else:
        raise HTTPException(401, result.get("message", "Giriş başarısız. Kullanıcı adı veya şifre hatalı."))



@router.post("/challenge-retry")
def challenge_retry():
    """
    Called after user approves the device notification on their phone.
    Retries the login to check if challenge was resolved.
    """
    result = ig.retry_challenge()

    if result["status"] == "ok":
        try:
            info = _get_and_save_account_info()
            return {"status": "ok", "account": info}
        except Exception as e:
            raise HTTPException(500, f"Hesap bilgileri alınamadı: {e}")

    elif result["status"] == "challenge_still_pending":
        return {"status": "challenge_still_pending", "message": result.get("message")}

    elif result["status"] == "2fa_required":
        return {"status": "2fa_required", "message": "Şimdi 2FA kodu gerekiyor."}

    else:
        raise HTTPException(400, result.get("message", "Challenge doğrulaması başarısız."))


@router.post("/2fa")
def verify_2fa(req: TwoFARequest):
    """Complete 2FA verification."""
    if not req.code:
        raise HTTPException(400, "Doğrulama kodu gerekli.")

    result = ig.verify_2fa(req.code.strip())

    if result["status"] == "ok":
        try:
            info = _get_and_save_account_info()
            return {"status": "ok", "account": info}
        except Exception as e:
            raise HTTPException(500, f"Hesap bilgileri alınamadı: {e}")
    else:
        raise HTTPException(401, result.get("message", "2FA doğrulama başarısız."))


@router.post("/logout")
def logout():
    """Logout and clear session."""
    ig.logout()
    db.clear_account()
    return {"status": "ok", "message": "Çıkış yapıldı."}
