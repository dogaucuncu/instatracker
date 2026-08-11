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
# instagrapi's built-in default ("OnePlus 6T Dev / devitron", app v269, Android
# 8, en_US) is the single most-flagged bot signature on Instagram — every
# uncustomized instagrapi login uses it. We replace it with a real, internally
# consistent Turkish-region Android device so logins look like an ordinary phone.
# NOTE: instagrapi can only impersonate Android, not iOS, so an iPhone account
# will still see this as a "new Android device" on first login (approve once).
# Values below are taken verbatim from a real captured Instagram-for-Android
# user agent (Samsung Galaxy S23+, Android 14, app 309.0.0.40.113) so the
# app_version + version_code pair stays internally consistent. Only the model
# is set to the international variant (SM-S916B, same "dm2q" codename) instead
# of the US carrier one, to match a Turkish user's phone.
IG_DEVICE = {
    "app_version": "309.0.0.40.113",
    "android_version": 34,
    "android_release": "14",
    "dpi": "510dpi",
    "resolution": "1080x2113",
    "manufacturer": "samsung",
    "device": "dm2q",
    "model": "SM-S916B",
    "cpu": "qcom",
    "version_code": "536988425",
}
IG_LOCALE = "tr_TR"
IG_COUNTRY = "TR"
IG_COUNTRY_CODE = 90
IG_TIMEZONE_OFFSET = 10800  # Europe/Istanbul, UTC+3

# App info
APP_NAME = "InstaTracker"
APP_VERSION = "1.0.0"
