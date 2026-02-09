"""
Server entry point — FastAPI app setup and route configuration.
Sets up the FastAPI server with CORS, static file serving, and all API routes.
"""

from __future__ import annotations

import os
from pathlib import Path

import dotenv
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from src.routes.analyze_stream import analyze_url_stream
from src.utils.logger import create_logger

dotenv.load_dotenv()

log = create_logger("Server")
app = FastAPI(title="Meddling Kids Python Server")

HOST = os.environ.get("UVICORN_HOST", "0.0.0.0")
PORT = int(os.environ.get("UVICORN_PORT", "3001"))

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
) -> EventSourceResponse:
    """
    Analyze tracking on a URL with streaming progress via SSE.
    """
    async def event_generator():
        async for event_str in analyze_url_stream(url, device):
            # The analyze_url_stream already produces formatted SSE strings
            # EventSourceResponse expects raw data; we yield the pre-formatted strings
            yield {"data": "", "event": "", "_raw": event_str}

    # Use a raw SSE approach since our events are pre-formatted
    async def raw_generator():
        async for event_str in analyze_url_stream(url, device):
            yield event_str

    from starlette.responses import StreamingResponse
    return StreamingResponse(
        raw_generator(),
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

if os.environ.get("NODE_ENV") == "production" and dist_path.exists():
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
    log.section("Meddling Kids Python Server Started")
    log.success(f"Server listening on {HOST}:{PORT}")
    log.info("Environment", {"env": os.environ.get("NODE_ENV", "development")})
    log.info("Open your browser", {"url": f"http://localhost:{PORT}"})

    uvicorn.run(
        "src.app:app",
        host=HOST,
        port=PORT,
        reload=os.environ.get("NODE_ENV") != "production",
    )


if __name__ == "__main__":
    main()
