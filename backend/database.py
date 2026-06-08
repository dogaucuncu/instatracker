import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager
from config import DB_PATH


def get_connection():
    """Return a new SQLite connection with row_factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize all database tables."""
    with db() as conn:
        conn.executescript("""
            -- Authenticated account info
            CREATE TABLE IF NOT EXISTS account (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                pk          TEXT NOT NULL,
                username    TEXT NOT NULL,
                full_name   TEXT,
                profile_pic_url TEXT,
                updated_at  TEXT NOT NULL
            );

            -- Follower snapshots (one per scan)
            CREATE TABLE IF NOT EXISTS follower_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id         INTEGER,
                taken_at        TEXT NOT NULL,
                follower_count  INTEGER NOT NULL DEFAULT 0
            );

            -- Individual followers per snapshot
            CREATE TABLE IF NOT EXISTS followers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL REFERENCES follower_snapshots(id) ON DELETE CASCADE,
                user_pk     TEXT NOT NULL,
                username    TEXT NOT NULL,
                full_name   TEXT,
                profile_pic_url TEXT
            );

            -- Following snapshots (one per scan)
            CREATE TABLE IF NOT EXISTS following_snapshots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id         INTEGER,
                taken_at        TEXT NOT NULL,
                following_count INTEGER NOT NULL DEFAULT 0
            );

            -- Individual users I follow per snapshot
            CREATE TABLE IF NOT EXISTS following (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL REFERENCES following_snapshots(id) ON DELETE CASCADE,
                user_pk     TEXT NOT NULL,
                username    TEXT NOT NULL,
                full_name   TEXT,
                profile_pic_url TEXT
            );

            -- Events detected (unfollows, blocks, deactivations)
            CREATE TABLE IF NOT EXISTS events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_pk         TEXT NOT NULL,
                username        TEXT NOT NULL,
                full_name       TEXT,
                profile_pic_url TEXT,
                event_type      TEXT NOT NULL,   -- unfollowed | blocked | deactivated | new_follower | reactivated
                still_following INTEGER NOT NULL DEFAULT 0,  -- 1 if I still follow this person
                detected_at     TEXT NOT NULL,
                details         TEXT             -- JSON string for extra info
            );

            -- Scan history
            CREATE TABLE IF NOT EXISTS scan_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TEXT NOT NULL,
                completed_at    TEXT,
                status          TEXT NOT NULL DEFAULT 'running',  -- running | completed | failed
                new_followers   INTEGER DEFAULT 0,
                lost_followers  INTEGER DEFAULT 0,
                error_message   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_detected ON events(detected_at);
            CREATE INDEX IF NOT EXISTS idx_events_user_pk ON events(user_pk);
            CREATE INDEX IF NOT EXISTS idx_followers_snapshot ON followers(snapshot_id);
            CREATE INDEX IF NOT EXISTS idx_following_snapshot ON following(snapshot_id);
        """)


# ── Account ──────────────────────────────────────────────────────────────────

def save_account(pk: str, username: str, full_name: str, profile_pic_url: str):
    with db() as conn:
        conn.execute("""
            INSERT INTO account (id, pk, username, full_name, profile_pic_url, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                pk=excluded.pk,
                username=excluded.username,
                full_name=excluded.full_name,
                profile_pic_url=excluded.profile_pic_url,
                updated_at=excluded.updated_at
        """, (pk, username, full_name, profile_pic_url, datetime.utcnow().isoformat()))


def get_account():
    with db() as conn:
        row = conn.execute("SELECT * FROM account WHERE id=1").fetchone()
        return dict(row) if row else None


def clear_account():
    with db() as conn:
        conn.execute("DELETE FROM account")


# ── Snapshots ─────────────────────────────────────────────────────────────────

def save_follower_snapshot(scan_id: int, users: list[dict]) -> int:
    """Save a follower snapshot and return its id."""
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO follower_snapshots (scan_id, taken_at, follower_count) VALUES (?,?,?)",
            (scan_id, datetime.utcnow().isoformat(), len(users))
        )
        snapshot_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO followers (snapshot_id, user_pk, username, full_name, profile_pic_url) VALUES (?,?,?,?,?)",
            [(snapshot_id, u["pk"], u["username"], u.get("full_name"), u.get("profile_pic_url")) for u in users]
        )
        return snapshot_id


def save_following_snapshot(scan_id: int, users: list[dict]) -> int:
    """Save a following snapshot and return its id."""
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO following_snapshots (scan_id, taken_at, following_count) VALUES (?,?,?)",
            (scan_id, datetime.utcnow().isoformat(), len(users))
        )
        snapshot_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO following (snapshot_id, user_pk, username, full_name, profile_pic_url) VALUES (?,?,?,?,?)",
            [(snapshot_id, u["pk"], u["username"], u.get("full_name"), u.get("profile_pic_url")) for u in users]
        )
        return snapshot_id


def get_latest_follower_snapshot_users() -> list[dict]:
    """
    Return all users from the PREVIOUS (second-most-recent) follower snapshot.

    This function is called in tracker_service BEFORE the new snapshot is saved,
    so the DB still contains snapshots from previous runs only.
    OFFSET 1 is intentionally NOT used here — we simply return the most recent
    snapshot at call-time, which is the baseline for comparison.

    If no previous snapshot exists (first scan), returns an empty list.
    """
    with db() as conn:
        snap = conn.execute(
            "SELECT id FROM follower_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not snap:
            return []
        rows = conn.execute(
            "SELECT user_pk, username, full_name, profile_pic_url FROM followers WHERE snapshot_id=?",
            (snap["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


def get_previous_follower_snapshot_users() -> list[dict]:
    """Return all users from the second-most-recent follower snapshot (for comparison)."""
    with db() as conn:
        snap = conn.execute(
            "SELECT id FROM follower_snapshots ORDER BY id DESC LIMIT 1 OFFSET 1"
        ).fetchone()
        if not snap:
            return []
        rows = conn.execute(
            "SELECT user_pk, username, full_name, profile_pic_url FROM followers WHERE snapshot_id=?",
            (snap["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_following_snapshot_users() -> list[dict]:
    """Return all users from the most recent following snapshot."""
    with db() as conn:
        snap = conn.execute(
            "SELECT id FROM following_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not snap:
            return []
        rows = conn.execute(
            "SELECT user_pk, username, full_name, profile_pic_url FROM following WHERE snapshot_id=?",
            (snap["id"],)
        ).fetchall()
        return [dict(r) for r in rows]


def get_snapshot_count() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM follower_snapshots").fetchone()
        return row["c"] if row else 0


# ── Events ────────────────────────────────────────────────────────────────────

def save_event(user_pk: str, username: str, full_name: str, profile_pic_url: str,
               event_type: str, still_following: bool = False, details: dict = None):
    with db() as conn:
        conn.execute("""
            INSERT INTO events
              (user_pk, username, full_name, profile_pic_url, event_type, still_following, detected_at, details)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            user_pk, username, full_name, profile_pic_url,
            event_type, 1 if still_following else 0,
            datetime.utcnow().isoformat(),
            json.dumps(details) if details else None
        ))


def get_events(event_type: str = None, limit: int = 200) -> list[dict]:
    with db() as conn:
        if event_type:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type=? ORDER BY detected_at DESC LIMIT ?",
                (event_type, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY detected_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["still_following"] = bool(d["still_following"])
            d["details"] = json.loads(d["details"]) if d.get("details") else None
            result.append(d)
        return result


def event_exists_today(user_pk: str, event_type: str) -> bool:
    """Check if this event type was already recorded for user today."""
    today = datetime.utcnow().date().isoformat()
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM events WHERE user_pk=? AND event_type=? AND detected_at LIKE ?",
            (user_pk, event_type, f"{today}%")
        ).fetchone()
        return row is not None


def update_event_still_following(user_pk: str, still_following: bool):
    """Update still_following flag for a user's latest event."""
    with db() as conn:
        conn.execute(
            "UPDATE events SET still_following=? WHERE user_pk=? AND event_type IN ('unfollowed','blocked','deactivated')",
            (1 if still_following else 0, user_pk)
        )


def get_dashboard_stats() -> dict:
    with db() as conn:
        total_events = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        unfollowed = conn.execute("SELECT COUNT(*) as c FROM events WHERE event_type='unfollowed'").fetchone()["c"]
        blocked = conn.execute("SELECT COUNT(*) as c FROM events WHERE event_type='blocked'").fetchone()["c"]
        deactivated = conn.execute("SELECT COUNT(*) as c FROM events WHERE event_type='deactivated'").fetchone()["c"]
        new_followers = conn.execute("SELECT COUNT(*) as c FROM events WHERE event_type='new_follower'").fetchone()["c"]
        still_following = conn.execute(
            "SELECT COUNT(*) as c FROM events WHERE still_following=1 AND event_type IN ('unfollowed','blocked','deactivated')"
        ).fetchone()["c"]

        # Latest follower count
        snap = conn.execute("SELECT follower_count FROM follower_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        follower_count = snap["follower_count"] if snap else 0

        # Latest following count
        fsnap = conn.execute("SELECT following_count FROM following_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        following_count = fsnap["following_count"] if fsnap else 0

        total_scans = conn.execute("SELECT COUNT(*) as c FROM scan_history WHERE status='completed'").fetchone()["c"]
        last_scan = conn.execute(
            "SELECT completed_at FROM scan_history WHERE status='completed' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        return {
            "total_events": total_events,
            "unfollowed": unfollowed,
            "blocked": blocked,
            "deactivated": deactivated,
            "new_followers": new_followers,
            "still_following_count": still_following,
            "follower_count": follower_count,
            "following_count": following_count,
            "total_scans": total_scans,
            "last_scan": last_scan["completed_at"] if last_scan else None,
        }


# ── Scan history ──────────────────────────────────────────────────────────────

def create_scan() -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO scan_history (started_at, status) VALUES (?,?)",
            (datetime.utcnow().isoformat(), "running")
        )
        return cur.lastrowid


def complete_scan(scan_id: int, new_followers: int, lost_followers: int):
    with db() as conn:
        conn.execute(
            "UPDATE scan_history SET status='completed', completed_at=?, new_followers=?, lost_followers=? WHERE id=?",
            (datetime.utcnow().isoformat(), new_followers, lost_followers, scan_id)
        )


def fail_scan(scan_id: int, error: str):
    with db() as conn:
        conn.execute(
            "UPDATE scan_history SET status='failed', completed_at=?, error_message=? WHERE id=?",
            (datetime.utcnow().isoformat(), error, scan_id)
        )


def get_scan_history(limit: int = 20) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_current_scan() -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM scan_history WHERE status='running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
