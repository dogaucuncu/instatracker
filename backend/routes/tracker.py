import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from services import instagram_service as ig
from services import tracker_service
import database as db

router = APIRouter(prefix="/api/scan", tags=["scan"])
logger = logging.getLogger(__name__)

# Global scan state
_scan_state: dict = {"running": False, "result": None, "error": None}


def _do_scan():
    global _scan_state
    try:
        result = tracker_service.run_scan()
        _scan_state["result"] = result
        _scan_state["error"] = None
    except Exception as e:
        _scan_state["error"] = str(e)
        _scan_state["result"] = None
    finally:
        _scan_state["running"] = False


@router.post("/start")
def start_scan(background_tasks: BackgroundTasks):
    """Start a new follower scan in the background."""
    global _scan_state

    if not ig.is_logged_in():
        raise HTTPException(401, "Önce giriş yapmalısınız.")

    if _scan_state["running"]:
        raise HTTPException(409, "Zaten bir tarama çalışıyor. Lütfen bekleyin.")

    _scan_state = {"running": True, "result": None, "error": None}
    background_tasks.add_task(_do_scan)

    return {"status": "started", "message": "Tarama başlatıldı. Bu işlem birkaç dakika sürebilir..."}


@router.get("/status")
def scan_status():
    """Get current scan status."""
    global _scan_state

    if _scan_state["running"]:
        return {"status": "running", "message": "Tarama devam ediyor..."}

    if _scan_state["error"]:
        return {"status": "error", "message": _scan_state["error"]}

    if _scan_state["result"]:
        return {"status": "completed", "result": _scan_state["result"]}

    return {"status": "idle", "message": "Tarama bekleniyor."}


@router.get("/history")
def scan_history(limit: int = 20):
    """Get scan history."""
    return db.get_scan_history(limit)
