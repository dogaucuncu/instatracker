import sys
import logging
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import database as db
from config import FRONTEND_DIR, APP_NAME, APP_VERSION
from routes.auth import router as auth_router
from routes.tracker import router as scan_router
from routes.dashboard import router as dashboard_router

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Instagram Takipçi Takip Sistemi",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(dashboard_router)

# ── Static files (frontend) ───────────────────────────────────────────────────
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{path:path}")
    def serve_spa(path: str):
        """Serve frontend SPA for all non-API routes."""
        file_path = FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    logger.info("Initializing database...")
    db.init_db()
    logger.info("Database ready.")
    logger.info("%s v%s started!", APP_NAME, APP_VERSION)
