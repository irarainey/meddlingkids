#!/bin/bash
# =============================================================================
# Docker Entrypoint Script
# =============================================================================
# Starts Xvfb (virtual display) and then the Python FastAPI server.
# This allows the browser to run in headed mode without a visible window,
# which helps ads load (ad networks often block automated/headless browsers).
# =============================================================================

set -e

# Remap appuser UID/GID to match the host user when UID_GID is set.
# This ensures files written to bind-mounted volumes are readable on the host.
if [[ -n "${UID_GID:-}" ]]; then
    IFS=':' read -r HOST_UID HOST_GID <<< "$UID_GID"
    if [[ -n "$HOST_GID" ]] && [[ "$HOST_GID" != "$(id -g appuser)" ]]; then
        groupmod -g "$HOST_GID" appgroup
    fi
    if [[ -n "$HOST_UID" ]] && [[ "$HOST_UID" != "$(id -u appuser)" ]]; then
        usermod -u "$HOST_UID" appuser
    fi
    echo "Mapped appuser to UID=${HOST_UID}, GID=${HOST_GID}"
fi

# Fix .output directory permissions for volume mounts, then drop to appuser.
# When a host directory is bind-mounted, Docker creates it as root — this
# ensures appuser can write cache, logs, and reports.
OUTPUT_DIR=/app/server/.output
mkdir -p "$OUTPUT_DIR/cache" "$OUTPUT_DIR/logs" "$OUTPUT_DIR/reports"
chown -R appuser:appgroup "$OUTPUT_DIR"

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

if [[ "${SHOW_UI,,}" == "true" ]]; then
    echo "Open the client UI at: http://localhost:${UI_PORT:-3002}"
fi

cd /app/server

# Drop to non-root user and start the server.
# Always bind to 0.0.0.0 inside Docker so the server is reachable from the host.
# UVICORN_HOST from .env is intentionally ignored here — containers must listen
# on all interfaces for port-forwarding to work.
exec su -s /bin/bash appuser -c ".venv/bin/uvicorn src.main:app --host 0.0.0.0 --port ${UVICORN_PORT:-3001}"
