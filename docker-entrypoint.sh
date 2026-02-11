#!/bin/bash
# =============================================================================
# Docker Entrypoint Script
# =============================================================================
# Starts Xvfb (virtual display) and then the Python FastAPI server.
# This allows the browser to run in headed mode without a visible window,
# which helps ads load (ad networks often block automated/headless browsers).
# =============================================================================

set -e

# Start Xvfb on display :99 in the background
echo "Starting Xvfb virtual display on :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &

# Wait for Xvfb to be ready
sleep 1

# Export DISPLAY so the browser uses the virtual display
export DISPLAY=:99

echo "Starting server..."
echo "Open your browser: http://localhost:${UVICORN_PORT:-3001}"
cd /app/server
exec .venv/bin/uvicorn src.main:app --host "${UVICORN_HOST:-0.0.0.0}" --port "${UVICORN_PORT:-3001}"
