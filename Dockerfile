# =============================================================================
# Meddling Kids - Multi-stage Docker Build
# =============================================================================
# This Dockerfile builds the Vue.js client and runs the Python FastAPI server
# in a multi-stage build for optimal image size.
#
# Build:
#   docker build -t meddlingkids .
#
# Run with env file (default port 3001):
#   docker run -p 3001:3001 --env-file .env meddlingkids
#
# Run on a custom port (e.g., 8080):
#   docker run -p 8080:8080 -e UVICORN_PORT=8080 --env-file .env meddlingkids
#
# Run with environment variables:
#   docker run -p 3001:3001 \
#     -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/ \
#     -e AZURE_OPENAI_API_KEY=your-api-key \
#     -e AZURE_OPENAI_DEPLOYMENT=gpt-5.1-chat \
#     meddlingkids
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Build the client
# -----------------------------------------------------------------------------
FROM node:22-slim AS builder

WORKDIR /app

# Copy package files for dependency installation
COPY package*.json ./

# Install all dependencies (including devDependencies for building)
RUN npm ci

# Copy source files needed for client build
COPY tsconfig*.json vite.config.ts ./
COPY client/ ./client/

# Build the Vue.js client (outputs to /app/dist)
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Production image with Python and Playwright
# -----------------------------------------------------------------------------
FROM python:3.13-slim AS production

# Install dependencies required by Playwright browsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Init process for proper signal handling
    tini \
    # Xvfb for virtual display (allows headed browser without visible window)
    xvfb \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # Fonts
    fonts-liberation \
    fonts-noto-color-emoji \
    # Utilities
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy Python server files and install dependencies
COPY server/pyproject.toml server/uv.lock* server/README.md ./server/
RUN cd server && uv sync --frozen --no-dev

# Copy Python server source
COPY server/src/ ./server/src/

# Create non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --shell /bin/bash --create-home appuser

# Set Playwright browsers path to a shared location
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# Install Playwright browsers (Chromium only for smaller image)
RUN cd server && .venv/bin/playwright install chromium && \
    chmod -R 755 /opt/playwright-browsers

# Copy built client from builder stage
COPY --from=builder /app/dist ./dist

# Copy and prepare entrypoint script
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Change ownership to non-root user
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Environment variables with defaults
ENV NODE_ENV=production
ENV UVICORN_HOST=0.0.0.0
ENV UVICORN_PORT=3001
ENV DISPLAY=:99

# Azure OpenAI configuration (pass via --env-file or -e flags)
# ENV AZURE_OPENAI_ENDPOINT=
# ENV AZURE_OPENAI_API_KEY=
# ENV AZURE_OPENAI_DEPLOYMENT=

# Health check using the UVICORN_PORT environment variable
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${UVICORN_PORT:-3001}/ || exit 1

# Use tini as init process for proper signal handling (CTRL+C)
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start Xvfb and the server via entrypoint script
CMD ["./docker-entrypoint.sh"]
