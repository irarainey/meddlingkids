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
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvfb :99 -screen 0 1920x1080x24 -ac &
echo $! > /tmp/xvfb.pid

# Wait for Xvfb to be ready
sleep 1

if ! kill -0 "$(cat /tmp/xvfb.pid 2>/dev/null)" 2>/dev/null; then
    echo "ERROR: Xvfb failed to start"
    exit 1
fi

# Export DISPLAY so the browser uses the virtual display
export DISPLAY=:99

echo "Starting server..."
echo "Open your browser: http://localhost:${UVICORN_PORT:-3001}"
cd /app/server
exec .venv/bin/uvicorn src.main:app --host "${UVICORN_HOST:-0.0.0.0}" --port "${UVICORN_PORT:-3001}"
