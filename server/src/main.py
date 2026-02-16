"""
Server entry point — FastAPI app setup and route configuration.
Sets up the FastAPI server with CORS, static file serving, and all API routes.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
from collections.abc import AsyncGenerator

import dotenv
import fastapi
from fastapi import staticfiles
from fastapi.middleware import cors
from starlette import responses

from src.agents import observability_setup
from src.pipeline import stream
from src.utils import cache, logger


def _bootstrap() -> None:
    """Load environment and configure observability (called once at startup)."""
    dotenv.load_dotenv()
    observability_setup.setup()


_bootstrap()

log = logger.create_logger("Server")

IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development") == "production"


@contextlib.asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> AsyncGenerator[None]:
    """Log server start on startup."""
    log.section("Meddling Kids Server Started")
    log.info("Environment", {"env": "production" if IS_PRODUCTION else "development"})
    yield


app = fastapi.FastAPI(title="Meddling Kids Python Server", lifespan=lifespan)

# ============================================================================
# Middleware
# ============================================================================

_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:4173",
).split(",")

app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# API Routes
# ============================================================================


@app.post("/api/clear-cache")
async def clear_cache_endpoint() -> dict[str, object]:
    """Delete all cached data (domain, overlay, scripts)."""
    removed = cache.clear_all()
    log.success("Cache cleared via API", {"filesRemoved": removed})
    return {"success": True, "filesRemoved": removed}


@app.get("/api/open-browser-stream")
async def analyze_endpoint(
    url: str = fastapi.Query(..., description="The URL to analyze"),
    device: str = fastapi.Query("ipad", description="Device type to emulate"),
    clear_cache: bool = fastapi.Query(False, alias="clear-cache", description="Clear all caches before analysis"),
) -> responses.StreamingResponse:
    """
    Analyze tracking on a URL with streaming progress via SSE.
    """
    log.info("Incoming analysis request", {"url": url, "device": device, "clearCache": clear_cache})

    async def event_generator():
        async for event_str in stream.analyze_url_stream(url, device, clear_cache=clear_cache):
            yield event_str

    return responses.StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ============================================================================
# Static File Serving (Production)
# ============================================================================

dist_path = pathlib.Path(__file__).resolve().parent.parent.parent / "dist"

if IS_PRODUCTION and dist_path.exists():
    log.info("Serving static files", {"path": str(dist_path)})
    app.mount("/assets", staticfiles.StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> responses.FileResponse:
        """SPA fallback - serve index.html for all non-API routes."""
        file_path = (dist_path / full_path).resolve()
        if file_path.is_relative_to(dist_path) and file_path.exists() and file_path.is_file():
            return responses.FileResponse(str(file_path))
        return responses.FileResponse(str(dist_path / "index.html"))
