from fastapi import APIRouter, HTTPException
from models import UnfollowRequest
from services import instagram_service as ig
import database as db

router = APIRouter(prefix="/api", tags=["dashboard"])

# Maximum number of records that can be requested in one call
_MAX_LIMIT = 500


def _require_login():
    """Raise 401 if the user is not logged in."""
    if not ig.is_logged_in():
        raise HTTPException(401, "Önce giriş yapmalısınız.")


@router.get("/dashboard/stats")
def dashboard_stats():
    """Get overall dashboard statistics."""
    _require_login()
    return db.get_dashboard_stats()


@router.get("/events")
def get_all_events(limit: int = 200):
    """Get all events."""
    _require_login()
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.get_events(limit=limit)


@router.get("/events/unfollowers")
def get_unfollowers(limit: int = 200):
    """Get users who unfollowed."""
    _require_login()
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.get_events(event_type="unfollowed", limit=limit)


@router.get("/events/blockers")
def get_blockers(limit: int = 200):
    """Get users who blocked."""
    _require_login()
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.get_events(event_type="blocked", limit=limit)


@router.get("/events/deactivated")
def get_deactivated(limit: int = 200):
    """Get users whose accounts were deactivated."""
    _require_login()
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.get_events(event_type="deactivated", limit=limit)


@router.get("/events/new-followers")
def get_new_followers(limit: int = 200):
    """Get new followers."""
    _require_login()
    limit = min(max(1, limit), _MAX_LIMIT)
    return db.get_events(event_type="new_follower", limit=limit)


@router.get("/followers/current")
def current_followers():
    """Get the latest follower snapshot list."""
    _require_login()
    return db.get_latest_follower_snapshot_users()


@router.get("/following/current")
def current_following():
    """Get the latest following snapshot list."""
    _require_login()
    return db.get_latest_following_snapshot_users()


@router.post("/actions/unfollow")
def unfollow_user(req: UnfollowRequest):
    """Unfollow a specific user."""
    _require_login()

    success = ig.unfollow_user(req.user_pk)
    if success:
        # Update still_following flag in DB
        db.update_event_still_following(req.user_pk, False)
        return {"status": "ok", "message": f"@{req.username} kullanıcısını takipten çıktınız."}
    else:
        raise HTTPException(500, f"@{req.username} kullanıcısını takipten çıkarırken hata oluştu.")
