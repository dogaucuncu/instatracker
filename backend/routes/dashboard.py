from fastapi import APIRouter, HTTPException
from models import UnfollowRequest
from services import instagram_service as ig
import database as db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats")
def dashboard_stats():
    """Get overall dashboard statistics."""
    return db.get_dashboard_stats()


@router.get("/events")
def get_all_events(limit: int = 200):
    """Get all events."""
    return db.get_events(limit=limit)


@router.get("/events/unfollowers")
def get_unfollowers(limit: int = 200):
    """Get users who unfollowed."""
    return db.get_events(event_type="unfollowed", limit=limit)


@router.get("/events/blockers")
def get_blockers(limit: int = 200):
    """Get users who blocked."""
    return db.get_events(event_type="blocked", limit=limit)


@router.get("/events/deactivated")
def get_deactivated(limit: int = 200):
    """Get users whose accounts were deactivated."""
    return db.get_events(event_type="deactivated", limit=limit)


@router.get("/events/new-followers")
def get_new_followers(limit: int = 200):
    """Get new followers."""
    return db.get_events(event_type="new_follower", limit=limit)


@router.get("/followers/current")
def current_followers():
    """Get the latest follower snapshot list."""
    return db.get_latest_follower_snapshot_users()


@router.get("/following/current")
def current_following():
    """Get the latest following snapshot list."""
    # Reuse follower snapshot utility for following
    import database
    import sqlite3
    from config import DB_PATH
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    snap = conn.execute("SELECT id FROM following_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not snap:
        conn.close()
        return []
    rows = conn.execute(
        "SELECT user_pk, username, full_name, profile_pic_url FROM following WHERE snapshot_id=?",
        (snap["id"],)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/actions/unfollow")
def unfollow_user(req: UnfollowRequest):
    """Unfollow a specific user."""
    if not ig.is_logged_in():
        raise HTTPException(401, "Önce giriş yapmalısınız.")

    success = ig.unfollow_user(req.user_pk)
    if success:
        # Update still_following flag in DB
        db.update_event_still_following(req.user_pk, False)
        return {"status": "ok", "message": f"@{req.username} kullanıcısını takipten çıktınız."}
    else:
        raise HTTPException(500, f"@{req.username} kullanıcısını takipten çıkarken hata oluştu.")
