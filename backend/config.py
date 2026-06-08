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

# Rate limiting delays (seconds) - to avoid Instagram bot detection
MIN_DELAY = 3.0
MAX_DELAY = 7.0

# App info
APP_NAME = "InstaTracker"
APP_VERSION = "1.0.0"
