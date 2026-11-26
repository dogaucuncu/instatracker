import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.parent

# Data directory for DB and session files
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Database
DB_PATH = DATA_DIR / "instatracker.db"

# Session file
SESSION_FILE = DATA_DIR / "session.json"

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))

# Frontend static files
FRONTEND_DIR = BASE_DIR / "frontend"

# Pacing (seconds) between follower/following page fetches during a scan.
# Each page carries FRIENDSHIP_PAGE_SIZE users, which is about as far as a
# person scrolls in a few seconds, so this is roughly real-time.
SCAN_MIN_DELAY = 2.0
SCAN_MAX_DELAY = 5.0

# Users per follower/following page. 200 is what both instagrapi and the
# Android app request, and larger pages mean fewer requests for the same data.
FRIENDSHIP_PAGE_SIZE = 200

# Hard ceiling on pages per list, so a stuck cursor can never turn pagination
# into an endless request loop. 200 pages x 200 users = 40k accounts, far above
# anything this tool is meant for.
MAX_FRIENDSHIP_PAGES = 200

# Nobody scrolls a long list at a constant rate — every few pages a real user
# stops to look at someone. Without this the request timing is a flat
# distribution, which is trivial to spot server-side.
SCAN_PAUSE_EVERY_PAGES = 3
SCAN_PAUSE_MIN_DELAY = 8.0
SCAN_PAUSE_MAX_DELAY = 20.0

# Minimum gap between two full scans. Repeatedly enumerating the whole follower
# and following list is the single behaviour most likely to earn the account a
# multi-day "Daha Sonra Tekrar Dene" restriction, so the app refuses to do it
# back-to-back. Set to 0 to disable the guard.
MIN_SCAN_INTERVAL_MINUTES = 20

# Longer pacing for the more sensitive per-user requests (status checks on
# lost followers, unfollows). Individual user_info lookups are the calls that
# pattern-match scraping, and there are only a handful of them per scan.
MIN_DELAY = 5.0
MAX_DELAY = 11.0

# Delays for the interactive login/auth sequence. The real app fires its login
# chain (launcher sync → login → reels tray → timeline) back-to-back within a
# couple of seconds, so pausing 5-11s between those requests is both slow for
# the user AND less realistic. Keep only a short human-like gap here.
LOGIN_MIN_DELAY = 1.0
LOGIN_MAX_DELAY = 2.5

# Extra pause (seconds) between the followers fetch and the following fetch in
# a single scan — like a user switching from the "followers" tab to the
# "following" tab after a few seconds.
INTER_FETCH_MIN_DELAY = 8.0
INTER_FETCH_MAX_DELAY = 20.0

# ── Instagram device fingerprint ─────────────────────────────────────────────
# instagrapi's built-in default device ("Pixel 8 Pro / husky", en_US) is the
# most-flagged bot signature on Instagram — every uncustomized instagrapi login
# uses it. We replace the hardware half with a real, internally consistent
# Turkish-region Android phone so logins look like an ordinary device.
# NOTE: instagrapi can only impersonate Android, not iOS, so an iPhone account
# will still see this as a "new Android device" on first login (approve once).
# This block (Samsung Galaxy S23+, Android 14) is a real captured profile; only
# the model is set to the international variant (SM-S916B, same "dm2q"
# codename) instead of the US carrier one, to match a Turkish user's phone.
IG_HARDWARE = {
    "android_version": 34,
    "android_release": "14",
    "dpi": "510dpi",
    "resolution": "1080x2113",
    "manufacturer": "samsung",
    "device": "dm2q",
    "model": "SM-S916B",
    "cpu": "qcom",
}

# ── Instagram app build ──────────────────────────────────────────────────────
# app_version, version_code and bloks_versioning_id are ONE unit: all three
# have to come from the same real Instagram build. Writing them out by hand is
# how this broke before — an app_version carrying a second build's version code
# and a third build's Bloks hash, which Instagram answers with "Kullandığın
# Instagram sürümü güncel değil" (error_type needs_upgrade).
#
# So they are not written here at all: they are read from instagrapi, which
# ships the build it is actually tested against and bumps it every release.
# That makes the build impossible to mismatch, and `pip install -r
# requirements.txt` after a version bump is all that keeps it current.
try:
    from instagrapi import config as _ig_config

    _APP_BUILD = {
        k: v
        for k, v in _ig_config.APP_SETTINGS[_ig_config.DEFAULT_APP_VERSION].items()
        if k in ("app_version", "version_code", "bloks_versioning_id")
    }
except Exception:  # pragma: no cover - only if the library moves its table
    # instagrapi 3.1.0's shipped default, kept verbatim so config stays
    # importable if a future release renames APP_SETTINGS.
    _APP_BUILD = {
        "app_version": "449.0.0.52.84",
        "version_code": "1079242191",
        "bloks_versioning_id": (
            "799db3e387d7a21a19c72918b8698b6cd28a1516ade363792c100ed45a0f9f0b"
        ),
    }

IG_DEVICE = {**IG_HARDWARE, **_APP_BUILD}

IG_LOCALE = "tr_TR"
IG_COUNTRY = "TR"
IG_COUNTRY_CODE = 90
IG_TIMEZONE_OFFSET = 10800  # Europe/Istanbul, UTC+3

# App info
APP_NAME = "InstaTracker"
APP_VERSION = "1.0.0"
