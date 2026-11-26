import sys
import logging
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

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
# OpenAPI docs disabled — this is a local-only personal tool,
# no need to expose interactive API documentation.
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Instagram Takipçi Takip Sistemi",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── Security Headers Middleware ───────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Prevent the browser from MIME-sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Block the page from being loaded in an iframe (clickjacking)
    response.headers["X-Frame-Options"] = "DENY"
    # Basic XSS protection for older browsers
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Only send referrer for same-origin requests
    response.headers["Referrer-Policy"] = "same-origin"
    return response

# ── CORS ─────────────────────────────────────────────────────────────────────
# Restricted to localhost only — this app is never meant to be
# accessed from a remote origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
        """Serve frontend SPA for all non-API routes.

        Security: resolve the requested path and verify it stays inside
        FRONTEND_DIR to prevent path-traversal attacks (e.g. /../../../etc/passwd).
        """
        try:
            # Resolve to an absolute path and confirm it is inside the frontend
            # directory. is_relative_to() compares whole path components, where
            # a string prefix test would also accept a sibling directory whose
            # name merely starts with the same characters ("frontend-backup").
            root = FRONTEND_DIR.resolve()
            requested = (root / path).resolve()
            if not requested.is_relative_to(root):
                # Path traversal attempt — say nothing about what is there.
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        except Exception:
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        if requested.exists() and requested.is_file():
            return FileResponse(str(requested))
        return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    logger.info("Initializing database...")
    db.init_db()
    logger.info("Database ready.")
    logger.info("%s v%s started!", APP_NAME, APP_VERSION)
