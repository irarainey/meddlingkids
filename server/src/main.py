"""
Server entry point — FastAPI app factory, middleware, and static files.

Route handlers live in :mod:`src.api_routes`.  This module is responsible
for bootstrapping the application, wiring middleware (CORS, GZip,
optional OAuth2), and mounting the SPA static files.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
from collections.abc import AsyncGenerator

import dotenv
import fastapi
from fastapi import staticfiles
from fastapi.middleware import cors, gzip
from starlette import responses
from starlette.middleware import sessions

from src import api_routes
from src.agents import observability_setup
from src.auth import auth_routes, config, middleware
from src.browser import manager
from src.utils import logger


def _bootstrap() -> None:
    """Load environment and configure observability (called once at startup)."""
    dotenv.load_dotenv()
    observability_setup.setup()


_bootstrap()

log = logger.create_logger("Server")

SHOW_UI = os.environ.get("SHOW_UI", "false").lower() == "true"

_ALLOWED_ORIGINS = config.get_allowed_origins()


# ============================================================================
# App factory & lifespan
# ============================================================================


@contextlib.asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> AsyncGenerator[None]:
    """Start shared browser on startup, stop on shutdown."""
    log.section("Meddling Kids Server Started")
    log.info(
        "Configuration",
        {
            "showUi": SHOW_UI,
            "corsOrigins": _ALLOWED_ORIGINS,
            "authEnabled": config.is_auth_enabled(),
        },
    )

    # Start the shared Playwright + Chrome instance once.
    # All analysis requests will reuse this browser and
    # create lightweight, isolated contexts per scan.
    pw_manager = manager.PlaywrightManager.get_instance()
    await pw_manager.start()

    yield

    # Graceful shutdown: close the shared browser + Playwright.
    await pw_manager.stop()


app = fastapi.FastAPI(title="Meddling Kids Python Server", lifespan=lifespan)


@app.exception_handler(json.JSONDecodeError)
async def _json_decode_error_handler(
    _request: fastapi.Request,
    _exc: json.JSONDecodeError,
) -> fastapi.responses.JSONResponse:
    """Return 400 for malformed JSON request bodies."""
    return fastapi.responses.JSONResponse(
        status_code=400,
        content={"detail": "Invalid JSON in request body"},
    )


# ============================================================================
# Middleware
# ============================================================================

app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=config.is_auth_enabled(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip-compress responses above 500 bytes.  SSE tracking events
# (JSON arrays of cookies/requests) compress ~85-90 %, keeping
# even extreme sites well under browser EventSource limits.
app.add_middleware(gzip.GZipMiddleware, minimum_size=500)


# ── Optional OAuth2 authentication ─────────────────────────────────────
# Enabled only when OAUTH_ISSUER, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET,
# and SESSION_SECRET are all set in the environment.
if config.is_auth_enabled():
    _auth_cfg = config.get_oauth_config()

    @app.middleware("http")
    async def _auth_guard_middleware(
        request: fastapi.Request,
        call_next,  # type: ignore[no-untyped-def]
    ) -> fastapi.Response:
        return await middleware.auth_guard(request, call_next)

    # SessionMiddleware must be added AFTER the auth guard so it is the
    # outermost layer (Starlette uses LIFO ordering).  This ensures the
    # session cookie is decoded before the guard reads request.session.

    app.add_middleware(
        sessions.SessionMiddleware,
        secret_key=_auth_cfg["session_secret"],
        session_cookie="mk_session",
        max_age=24 * 60 * 60,  # 24 hours
        same_site="lax",
        https_only=os.environ.get("SESSION_SECURE", "").lower() == "true",
    )

    log.info("OAuth2 authentication enabled", {"issuer": _auth_cfg["issuer"]})


# Auth routes are always registered so /auth/me can report "disabled"
# instead of being swallowed by the SPA catch-all.
app.include_router(auth_routes.router)


@app.middleware("http")
async def disable_static_cache(
    request: fastapi.Request,
    call_next,
) -> fastapi.Response:
    """Prevent browsers from serving stale static assets from the Docker build."""
    response: fastapi.Response = await call_next(request)
    if request.url.path.startswith("/assets"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ============================================================================
# API Routes
# ============================================================================

app.include_router(api_routes.router)


# ============================================================================
# Static File Serving (Production)
# ============================================================================

dist_path = pathlib.Path(__file__).resolve().parent.parent.parent / "dist"

if SHOW_UI and dist_path.exists():
    log.info("Serving static files", {"path": str(dist_path)})
    app.mount("/assets", staticfiles.StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> responses.FileResponse:
        """SPA fallback - serve index.html for all non-API routes."""
        file_path = (dist_path / full_path).resolve()
        if file_path.is_relative_to(dist_path) and file_path.exists() and file_path.is_file():
            return responses.FileResponse(str(file_path))
        return responses.FileResponse(str(dist_path / "index.html"))
