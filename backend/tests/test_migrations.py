"""init_db() must upgrade a database created by an older version in place.

CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so a
column added later reaches existing installs only through the migration in
init_db(). Run from the backend directory:  py -3.10 -m pytest tests -q
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database  # noqa: E402

# The two tables as the first release created them, before returned_at and
# assumed existed.
OLD_SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_pk TEXT NOT NULL,
    username TEXT NOT NULL, full_name TEXT, profile_pic_url TEXT,
    event_type TEXT NOT NULL, still_following INTEGER NOT NULL DEFAULT 0,
    detected_at TEXT NOT NULL, details TEXT
);
CREATE TABLE followers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER NOT NULL,
    user_pk TEXT NOT NULL, username TEXT NOT NULL, full_name TEXT,
    profile_pic_url TEXT
);
INSERT INTO events (user_pk, username, event_type, detected_at)
     VALUES ('1', 'ayse', 'unfollowed', '2026-06-30T10:00:00');
INSERT INTO followers (snapshot_id, user_pk, username) VALUES (1, '1', 'ayse');
"""


def _columns(path, table):
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_old_database_gains_the_new_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    monkeypatch.setattr(database, "DB_PATH", path)

    database.init_db()

    assert "returned_at" in _columns(path, "events")
    assert "assumed" in _columns(path, "followers")
    with sqlite3.connect(path) as conn:
        # Rows written before the column existed were real observations.
        assert conn.execute("SELECT assumed FROM followers").fetchone()[0] == 0
        # An old departure is still open, not silently closed by the upgrade.
        assert conn.execute("SELECT returned_at FROM events").fetchone()[0] is None


def test_running_the_migration_twice_is_harmless(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(OLD_SCHEMA)
    monkeypatch.setattr(database, "DB_PATH", path)

    database.init_db()
    database.init_db()

    assert "assumed" in _columns(path, "followers")
