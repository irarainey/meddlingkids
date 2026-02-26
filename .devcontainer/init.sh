#!/bin/bash
# =============================================================================
# Dev Container Initialization Script
# =============================================================================
# Runs on every container start. Installs dependencies if needed and ensures
# Xvfb is running for Playwright browser automation.
# =============================================================================

set -e

# Install GitHub Copilot CLI if not present
if ! command -v github-copilot-cli &> /dev/null && ! command -v copilot &> /dev/null; then
    echo "🤖 Installing GitHub Copilot CLI..."
    curl -fsSL https://gh.io/copilot-install | bash
fi

# Upgrade npm to the latest version
echo "📦 Upgrading npm to latest..."
npm install -g npm@latest

# Install Node.js dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "🔧 Installing npm dependencies..."
    npm install
fi

# Install Python server dependencies via uv
if [ -f "server/pyproject.toml" ]; then
    echo "🐍 Installing Python dependencies via uv..."
    (cd server && uv sync)
fi

# Install Playwright browsers if not present
if [ ! -d "/home/node/.cache/ms-playwright" ]; then
    echo "🎭 Installing real Chrome for Python (preferred for TLS fingerprint)..."
    (cd server && .venv/bin/python -m playwright install --with-deps chrome)
    echo "🎭 Installing Chromium fallback for Python..."
    (cd server && .venv/bin/python -m playwright install chromium)
fi

# Install Xvfb if not present
if ! command -v Xvfb &> /dev/null; then
    echo "🖥️ Installing Xvfb for virtual display..."
    sudo apt-get update
    sudo apt-get install -y xvfb
fi

# Start Xvfb if not running
if ! pgrep -x Xvfb > /dev/null; then
    # Remove stale lock files from a previous container session
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
    echo "🖥️ Starting Xvfb virtual display on :99..."
    nohup Xvfb :99 -screen 0 1920x1080x24 -ac > /tmp/xvfb.log 2>&1 &
    sleep 1
    if pgrep -x Xvfb > /dev/null; then
        echo "✅ Xvfb started"
    else
        echo "❌ Xvfb failed to start — check /tmp/xvfb.log"
    fi
else
    echo "✅ Xvfb already running"
fi

echo "✅ Dev container ready!"
