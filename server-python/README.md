# Meddling Kids - Python Server

Alternative Python server implementation that mirrors the functionality of the Node.js server.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Playwright (with Chromium browser)

## Setup

```bash
cd server-python
uv sync
uv run playwright install chromium
```

## Environment Variables

### Azure OpenAI (checked first)
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI resource endpoint URL
- `AZURE_OPENAI_API_KEY` - API key for authentication
- `AZURE_OPENAI_DEPLOYMENT` - Name of the deployed model
- `OPENAI_API_VERSION` - API version (default: `2024-12-01-preview`)

### Standard OpenAI (fallback)
- `OPENAI_API_KEY` - API key for authentication
- `OPENAI_MODEL` - Model name (default: `gpt-5.1-chat`)
- `OPENAI_BASE_URL` - Optional custom base URL

### Other
- `PORT` - Server port (default: `3001`)
- `NODE_ENV` - Set to `production` for static file serving
- `WRITE_LOG_TO_FILE` - Set to `true` to enable file logging

## Running

```bash
# Development
uv run python -m src.app

# Or with uvicorn directly
uv run uvicorn src.app:app --host 0.0.0.0 --port 3001 --reload
```
