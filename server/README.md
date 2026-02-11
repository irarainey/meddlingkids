# Meddling Kids - Server

Python FastAPI backend that orchestrates browser automation and AI-powered tracking analysis. Uses Playwright (async API) for browser automation with headed mode on a virtual display (Xvfb) to avoid bot detection.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Playwright (with Chromium browser)

## Setup

```bash
cd server
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

### Server
- `UVICORN_HOST` - Server host (default: `0.0.0.0`)
- `UVICORN_PORT` - Server port (default: `3001`)
- `WRITE_LOG_TO_FILE` - Set to `true` to enable file logging

## Running

```bash
# Development (from project root)
npm run dev:server

# Or directly
cd server
uv run uvicorn src.main:app --host 0.0.0.0 --port 3001 --reload --env-file ../.env
```

## Architecture

```
src/
├── main.py                   # FastAPI application entry point
├── routes/
│   ├── analyze_stream.py     # SSE streaming endpoint
│   └── analyze_helpers.py    # Route helper utilities
├── agents/                   # AI agents (Microsoft Agent Framework)
│   ├── base.py               # BaseAgent with structured output support
│   ├── config.py             # LLM configuration (Azure / OpenAI)
│   ├── llm_client.py         # Chat client factory
│   ├── middleware.py          # Timing & retry middleware
│   ├── consent_detection_agent.py   # Vision agent for consent dialogs
│   ├── consent_extraction_agent.py  # Extract consent details agent
│   ├── script_analysis_agent.py     # Script identification agent
│   ├── summary_findings_agent.py    # Summary findings agent
│   └── tracking_analysis_agent.py   # Main tracking analysis agent
├── services/
│   ├── browser_session.py    # Playwright async browser session
│   ├── analysis.py           # Main tracking analysis orchestration
│   ├── script_analysis.py    # Script identification (patterns + LLM)
│   ├── script_grouping.py    # Group similar scripts to reduce noise
│   ├── consent_detection.py  # Consent dialog detection orchestration
│   ├── consent_extraction.py # Consent detail extraction orchestration
│   ├── consent_click.py      # Click strategies for consent buttons
│   ├── access_detection.py   # Bot blocking detection
│   ├── device_configs.py     # Device emulation profiles
│   ├── partner_classification.py  # Consent partner risk classification
│   ├── privacy_score.py      # Deterministic privacy scoring
│   └── tracker_patterns.py   # Regex patterns for tracker classification
├── data/
│   ├── loader.py             # JSON data loader with caching
│   ├── partners/             # Partner risk databases (8 JSON files)
│   └── trackers/             # Script pattern databases (2 JSON files)
├── types/
│   ├── tracking_data.py       # Cookies, scripts, storage, network models
│   ├── consent.py             # Consent detection & extraction models
│   ├── analysis.py            # Analysis results & scoring models
│   ├── partners.py            # Partner classification models
│   └── browser.py             # Navigation, access denial & device models
└── utils/
    ├── errors.py             # Error utilities
    ├── logger.py             # Structured logger with color output
    ├── tracking_summary.py   # Summary builder for LLM
    └── url.py                # URL utilities
```
