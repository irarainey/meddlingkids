# =============================================================================
# Meddling Kids - Multi-stage Docker Build
# =============================================================================
# This Dockerfile builds both the Vue.js client and Node.js server in a
# multi-stage build for optimal image size.
#
# Build:
#   docker build -t meddlingkids .
#
# Run with env file:
#   docker run -p 3001:3001 --env-file .env meddlingkids
#
# Run with environment variables:
#   docker run -p 3001:3001 \
#     -e AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/ \
#     -e AZURE_OPENAI_API_KEY=your-api-key \
#     -e AZURE_OPENAI_DEPLOYMENT=gpt-4o \
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
# Copy server tsconfig.json (needed by root tsconfig.json references for vue-tsc)
# and create a placeholder file to satisfy TypeScript's include pattern
COPY server/tsconfig.json ./server/
RUN mkdir -p server/src && echo "export {};" > server/src/placeholder.ts

# Build the Vue.js client (outputs to /app/dist)
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Production image with Playwright
# -----------------------------------------------------------------------------
FROM node:22-slim AS production

# Install dependencies required by Playwright browsers
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files and install production dependencies only
COPY package*.json ./
RUN npm ci --omit=dev

# Install tsx for running TypeScript directly
RUN npm install tsx

# Install Playwright browsers (Chromium only for smaller image)
RUN npx playwright install chromium

# Copy built client from builder stage
COPY --from=builder /app/dist ./dist

# Copy server source files (run TypeScript directly with Node 22)
COPY server/ ./server/

# Environment variables with defaults
ENV NODE_ENV=production
ENV PORT=3001

# Azure OpenAI configuration (pass via --env-file or -e flags)
# ENV AZURE_OPENAI_ENDPOINT=
# ENV AZURE_OPENAI_API_KEY=
# ENV AZURE_OPENAI_DEPLOYMENT=

# Expose the server port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "fetch('http://localhost:3001/').catch(() => process.exit(1))" || exit 1

# Start the server with tsx (handles TypeScript with .js imports)
CMD ["node", "--import", "tsx", "server/src/app.ts"]
