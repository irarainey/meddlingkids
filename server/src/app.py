"""
Server entry point — FastAPI app setup and route configuration.
Sets up the FastAPI server with CORS, static file serving, and all API routes.
"""

from __future__ import annotations

import os
from pathlib import Path

import dotenv
import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

from src.routes.analyze_stream import analyze_url_stream
from src.utils.logger import create_logger

dotenv.load_dotenv()

log = create_logger("Server")
app = FastAPI(title="Meddling Kids Python Server")

HOST = os.environ.get("UVICORN_HOST", "0.0.0.0")
PORT = int(os.environ.get("UVICORN_PORT", "3001"))
IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development") == "production"

# ============================================================================
# Middleware
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# API Routes
# ============================================================================


@app.get("/api/open-browser-stream")
async def analyze_endpoint(
    url: str = Query(..., description="The URL to analyze"),
    device: str = Query("ipad", description="Device type to emulate"),
) -> StreamingResponse:
    """
    Analyze tracking on a URL with streaming progress via SSE.
    """
    async def event_generator():
        async for event_str in analyze_url_stream(url, device):
            yield event_str

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


# ============================================================================
# Static File Serving (Production)
# ============================================================================

dist_path = Path(__file__).resolve().parent.parent.parent / "dist"

if IS_PRODUCTION and dist_path.exists():
    log.info("Serving static files", {"path": str(dist_path)})
    app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """SPA fallback - serve index.html for all non-API routes."""
        file_path = dist_path / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist_path / "index.html"))


# ============================================================================
# Start Server
# ============================================================================

def main() -> None:
    """Entry point for running the server."""
    log.section("Meddling Kids Server Started")
    log.success(f"Server listening on {HOST}:{PORT}")
    log.info("Environment", {"env": "production" if IS_PRODUCTION else "development"})
    log.info("Open your browser", {"url": f"http://localhost:{PORT}"})

    uvicorn.run(
        "src.app:app",
        host=HOST,
        port=PORT,
        reload=not IS_PRODUCTION,
    )


if __name__ == "__main__":
    main()
