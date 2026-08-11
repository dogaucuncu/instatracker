"""Scan-logic regression tests.

Run from the backend directory:  py -3.10 -m pytest tests -q
These use a throwaway SQLite file and a stubbed Instagram layer, so they never
touch the network or the real database.
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture
def scan_env(monkeypatch):
    """A fresh database plus a fake Instagram account we can drive."""
    db_path = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)

    import database as db
    from services import instagram_service
    import services.tracker_service as tracker

    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()

    users = {
        "1": {"pk": "1", "username": "ayse", "full_name": "Ayşe", "profile_pic_url": None},
        "2": {"pk": "2", "username": "mehmet", "full_name": "Mehmet", "profile_pic_url": None},
    }
    state = {"followers": [], "following": []}

    monkeypatch.setattr(instagram_service, "open_app", lambda: None)
    monkeypatch.setattr(instagram_service, "get_followers",
                        lambda: [users[p] for p in state["followers"]])
    monkeypatch.setattr(instagram_service, "get_following",
                        lambda: [users[p] for p in state["following"]])
    monkeypatch.setattr(instagram_service, "check_user_status",
                        lambda pk, username: "active")
    # The rate guard has its own test below; here it would block every scan
    # after the first one, so keep a handle on the real thing and stub it out.
    real_check_scan_allowed = tracker.check_scan_allowed
    monkeypatch.setattr(tracker, "check_scan_allowed", lambda: None)
    # Real scans idle for tens of seconds between the two enumerations.
    monkeypatch.setattr(tracker, "INTER_FETCH_MIN_DELAY", 0.0)
    monkeypatch.setattr(tracker, "INTER_FETCH_MAX_DELAY", 0.0)

    def set_lists(followers, following):
        state["followers"] = followers
        state["following"] = following

    def flag_for(pk):
        rows = [e for e in db.get_events(limit=100)
                if e["user_pk"] == pk and e["event_type"] == "unfollowed"]
        return rows[0]["still_following"] if rows else None

    yield type("ScanEnv", (), {
        "db": db, "tracker": tracker, "set_lists": staticmethod(set_lists),
        "flag_for": staticmethod(flag_for), "scan": staticmethod(tracker.run_scan),
        "check_scan_allowed": staticmethod(real_check_scan_allowed),
    })


def test_still_following_clears_after_unfollowing_on_the_phone(scan_env):
    """The badge must not survive an unfollow made outside the app.

    Regression: still_following was only recomputed for people who left the
    follower list during that same scan, so once @ayse was recorded she was
    never looked at again and kept her original flag forever.
    """
    scan_env.set_lists(["1", "2"], ["1", "2"])
    assert scan_env.scan()["status"] == "first_scan"

    # @ayse unfollows us; we still follow her.
    scan_env.set_lists(["2"], ["1", "2"])
    scan_env.scan()
    assert scan_env.flag_for("1") is True

    # We unfollow her from the phone. A later scan must notice.
    scan_env.set_lists(["2"], ["2"])
    scan_env.scan()
    assert scan_env.flag_for("1") is False

    # ...and notice again if we follow her back.
    scan_env.set_lists(["2"], ["1", "2"])
    scan_env.scan()
    assert scan_env.flag_for("1") is True


def test_empty_following_fetch_is_rejected(scan_env):
    """A soft-blocked account returns 200 with an empty list.

    Trusting it would wipe every still_following flag and record a zero
    following_count over good data.
    """
    scan_env.set_lists(["1", "2"], ["1", "2"])
    scan_env.scan()
    scan_env.set_lists(["2"], ["1", "2"])
    scan_env.scan()
    assert scan_env.flag_for("1") is True

    scan_env.set_lists(["2"], [])
    with pytest.raises(scan_env.tracker.EmptyFetch):
        scan_env.scan()

    assert scan_env.flag_for("1") is True
    assert scan_env.db.get_dashboard_stats()["following_count"] == 2


def test_empty_follower_fetch_does_not_mass_unfollow(scan_env):
    """An empty follower list must not look like everyone unfollowed at once."""
    scan_env.set_lists(["1", "2"], ["1", "2"])
    scan_env.scan()

    scan_env.set_lists([], ["1", "2"])
    with pytest.raises(scan_env.tracker.EmptyFetch):
        scan_env.scan()

    assert scan_env.db.get_dashboard_stats()["unfollowed"] == 0
    assert scan_env.db.get_dashboard_stats()["follower_count"] == 2


def test_scan_cooldown(scan_env, monkeypatch):
    """Back-to-back full enumerations are what get the account restricted."""
    db, tracker = scan_env.db, scan_env.tracker
    check = scan_env.check_scan_allowed
    monkeypatch.setattr(tracker, "MIN_SCAN_INTERVAL_MINUTES", 20)

    check()  # no history yet

    scan_id = db.create_scan()
    db.complete_scan(scan_id, 0, 0)
    with pytest.raises(tracker.ScanTooSoon):
        check()

    # A scan aborted mid-run stays on 'running' and must still hold the guard.
    with db.db() as conn:
        conn.execute("UPDATE scan_history SET status='running', completed_at=NULL")
    with pytest.raises(tracker.ScanTooSoon):
        check()

    # The cooldown counts from when the scan finished, not when it started.
    with db.db() as conn:
        conn.execute(
            "UPDATE scan_history SET status='completed', started_at=?, completed_at=?",
            ((datetime.utcnow() - timedelta(minutes=40)).isoformat(),
             (datetime.utcnow() - timedelta(minutes=5)).isoformat()),
        )
    with pytest.raises(tracker.ScanTooSoon):
        check()

    with db.db() as conn:
        conn.execute("UPDATE scan_history SET completed_at=?",
                     ((datetime.utcnow() - timedelta(minutes=25)).isoformat(),))
    check()
