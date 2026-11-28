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
    # Instagram's own answer to "does this person still follow me". Default
    # True = confirmed gone, which is what the pre-existing tests assume; the
    # confirmation tests below override it per case.
    confirm = {"answer": True}
    monkeypatch.setattr(instagram_service, "confirms_unfollow",
                        lambda pk, username: confirm["answer"])
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

    def set_confirmation(answer):
        confirm["answer"] = answer

    yield type("ScanEnv", (), {
        "db": db, "tracker": tracker, "set_lists": staticmethod(set_lists),
        "flag_for": staticmethod(flag_for), "scan": staticmethod(tracker.run_scan),
        "check_scan_allowed": staticmethod(real_check_scan_allowed),
        "set_confirmation": staticmethod(set_confirmation),
    })


def _events_of(db, event_type):
    return [e for e in db.get_events(limit=100) if e["event_type"] == event_type]


def test_missing_from_listing_but_still_following_records_nothing(scan_env):
    """One enumeration dropping a follower must not become an unfollow.

    Regression: a person Instagram simply omitted from the paged follower list
    was written down as "unfollowed" on that evidence alone. Here Instagram
    answers that they still follow, so nothing may be recorded.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()

    scan_env.set_confirmation(False)   # "no, they still follow you"
    scan_env.set_lists(["1"], [])      # @mehmet vanishes from the listing
    result = scan_env.scan()

    assert _events_of(scan_env.db, "unfollowed") == []
    assert result["lost_followers"] == 0
    assert result["missing_but_following"] == 1


def test_unverifiable_absence_is_left_for_the_next_scan(scan_env):
    """A check that cannot answer is not evidence of a departure."""
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()

    scan_env.set_confirmation(None)    # the check failed
    scan_env.set_lists(["1"], [])
    result = scan_env.scan()

    assert _events_of(scan_env.db, "unfollowed") == []
    assert result["unverified"] == 1


def test_event_carries_the_window_between_two_scans(scan_env):
    """Instagram records no unfollow moment, so an event has to carry a span.

    The lower bound is the *start* of the last completed scan before the event:
    that scan is where the person was last seen present, and using its finish
    time instead would exclude a departure that happened while it was running.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()
    first = scan_env.db.get_scan_history(limit=10)[0]

    scan_env.set_lists(["1"], [])
    scan_env.scan()

    event = _events_of(scan_env.db, "unfollowed")[0]
    assert event["window_start"] == first["started_at"]
    assert event["window_start"] < event["detected_at"]


def test_window_ignores_a_failed_scan(scan_env, monkeypatch):
    """A scan that failed saved no snapshot, so it cannot narrow the window."""
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()
    baseline = scan_env.db.get_scan_history(limit=10)[0]

    # A scan that dies after creating its row: it must not become the bound.
    failed_id = scan_env.db.create_scan()
    scan_env.db.fail_scan(failed_id, "deneme hatasi")

    scan_env.set_lists(["1"], [])
    scan_env.scan()

    event = _events_of(scan_env.db, "unfollowed")[0]
    assert event["window_start"] == baseline["started_at"],         "basarisiz tarama araligi daraltmamali"


def test_returning_follower_closes_the_departure(scan_env):
    """Someone back in the follower list stops being listed as gone.

    Regression: departure events were never revisited, so a person who
    returned — or who was only ever missing by accident — stayed on the
    "unfollowed" list for good and kept being counted.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()

    scan_env.set_lists(["1"], [])      # confirmed gone (fixture default)
    scan_env.scan()
    assert len(_events_of(scan_env.db, "unfollowed")) == 1
    assert scan_env.db.get_dashboard_stats()["unfollowed"] == 1

    scan_env.set_lists(["1", "2"], [])  # back again
    result = scan_env.scan()

    assert _events_of(scan_env.db, "unfollowed") == [], "kapanan kayıt listede kalmamalı"
    assert scan_env.db.get_dashboard_stats()["unfollowed"] == 0
    assert result["returned"] == 1
    # The row itself survives for the history.
    history = [e for e in scan_env.db.get_events(limit=100, include_returned=True)
               if e["event_type"] == "unfollowed"]
    assert len(history) == 1
    assert history[0]["returned_at"]


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


def test_unverified_absence_is_recorded_once_it_can_be_confirmed(scan_env):
    """"Left for the next scan" has to mean the next scan looks again.

    Regression: an absence that could not be verified was skipped, but the
    snapshot was still saved without the person — so the next scan compared
    two lists that both lacked them, saw no change, and the departure was
    never recorded at all.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()

    scan_env.set_confirmation(None)          # the check cannot answer
    scan_env.set_lists(["1"], [])
    scan_env.scan()
    assert _events_of(scan_env.db, "unfollowed") == []

    scan_env.set_confirmation(True)          # now Instagram confirms it
    scan_env.scan()
    assert len(_events_of(scan_env.db, "unfollowed")) == 1


def test_listing_dropout_does_not_return_as_a_new_follower(scan_env):
    """Someone who never left must not be announced as a new follower.

    Regression: a person Instagram confirmed still follows was kept out of the
    events, but not out of the snapshot. When the listing included them again
    the next scan saw them "arrive" and recorded a new_follower event.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()

    scan_env.set_confirmation(False)         # "they still follow you"
    scan_env.set_lists(["1"], [])            # but the listing dropped them
    scan_env.scan()

    scan_env.set_lists(["1", "2"], [])       # the listing has them again
    scan_env.scan()

    assert _events_of(scan_env.db, "new_follower") == []


def test_window_starts_at_the_last_real_sighting(scan_env):
    """A scan that could not verify someone kept them without seeing them.

    That row exists only so the next scan looks again; it is not a sighting.
    Taking it as one would start the window after the moment the person may
    already have been gone, and the interface would show a span that is too
    short to contain the truth.
    """
    scan_env.set_lists(["1", "2"], [])
    scan_env.scan()
    sighting = scan_env.db.get_scan_history(limit=10)[0]

    scan_env.set_confirmation(None)          # absent, and cannot be checked
    scan_env.set_lists(["1"], [])
    scan_env.scan()

    scan_env.set_confirmation(True)          # absent, and confirmed gone
    scan_env.scan()

    event = _events_of(scan_env.db, "unfollowed")[0]
    assert event["window_start"] == sighting["started_at"]
