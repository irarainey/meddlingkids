# Meddling Kids - Server

Python FastAPI backend that orchestrates browser automation and AI-powered tracking analysis. Uses Playwright (async API) for browser automation with headed mode on a virtual display (Xvfb) to avoid bot detection. Real Chrome is preferred over bundled Chromium for genuine TLS fingerprints that bypass CDN-level bot detectors. AI agents are built on the **Microsoft Agent Framework** (`agent-framework-core` package).

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Playwright (with Chrome browser; falls back to bundled Chromium)

## Setup

```bash
cd server
uv sync
uv run playwright install chrome
uv run playwright install chromium
```

## Environment Variables

### Azure OpenAI (checked first)
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI resource endpoint URL
- `AZURE_OPENAI_API_KEY` - API key for authentication
- `AZURE_OPENAI_DEPLOYMENT` - Name of the deployed model (must support vision, e.g., `gpt-5.2-chat`)
- `OPENAI_API_VERSION` - API version (default: `2024-12-01-preview`)

### Standard OpenAI (fallback)
- `OPENAI_API_KEY` - API key for authentication
- `OPENAI_MODEL` - Model name (must support vision, default: `gpt-5.2-chat`)
- `OPENAI_BASE_URL` - Optional custom base URL

### Server
- `UVICORN_HOST` - Server host (default: `0.0.0.0`)
- `UVICORN_PORT` - Server port (default: `3001`)
- `WRITE_LOG_TO_FILE` - Set to `true` to enable file logging

### Observability (Optional)
- `APPLICATIONINSIGHTS_CONNECTION_STRING` - Azure Application Insights connection string for Agent Framework telemetry (traces, logs, metrics)

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
├── main.py                          # FastAPI application entry point
├── agents/                          # AI agents (Microsoft Agent Framework)
│   ├── base.py                      # BaseAgent with structured output support
│   ├── config.py                    # LLM configuration (Azure / OpenAI)
│   ├── llm_client.py                # Chat client factory
│   ├── middleware.py                # Timing & retry middleware
│   ├── consent_detection_agent.py   # Vision agent for consent dialogs
│   ├── consent_extraction_agent.py  # Extract consent details agent
│   ├── script_analysis_agent.py     # Script identification agent
│   ├── summary_findings_agent.py    # Summary findings agent
│   ├── tracking_analysis_agent.py   # Main tracking analysis agent
│   └── scripts/                     # JavaScript snippets evaluated in-browser
├── browser/                         # Browser automation
│   ├── session.py                   # Playwright async browser session
│   ├── access_detection.py          # Bot blocking / CAPTCHA detection
│   └── device_configs.py            # Device emulation profiles
├── consent/                         # Consent handling
│   ├── click.py                     # Multi-strategy consent button clicker
│   ├── detection.py                 # Consent dialog detection orchestration
│   ├── extraction.py                # Consent detail extraction orchestration
│   ├── overlay_cache.py             # Domain-level cache for overlay strategies (JSON)
│   └── partner_classification.py    # Consent partner risk classification
├── analysis/                        # Tracking analysis & scoring
│   ├── tracking.py                  # Streaming LLM tracking analysis
│   ├── scripts.py                   # Script identification (patterns + LLM)
│   ├── script_grouping.py           # Group similar scripts to reduce noise
│   ├── tracker_patterns.py          # Regex patterns for tracker classification
│   ├── tracking_summary.py          # Summary builder for LLM input & pre-consent stats
│   └── scoring/                     # Decomposed privacy scoring package (0-100)
│       ├── calculator.py            # Orchestrator: calls category scorers, applies curve
│       ├── advertising.py           # Ad networks, retargeting, RTB infrastructure
│       ├── consent.py               # Pre-consent tracking, partner risk, disclosure
│       ├── cookies.py               # Cookie volume, 3P cookies, known trackers
│       ├── data_collection.py       # localStorage, beacons/pixels, analytics
│       ├── fingerprinting.py        # Session-replay, cross-device, behavioural
│       ├── sensitive_data.py        # Sensitive PII (location, health, financial)
│       ├── social_media.py          # Social media pixels, SDKs, plugins
│       └── third_party.py           # 3P domain count, request volume, known services
├── pipeline/                        # SSE streaming orchestration
│   ├── stream.py                    # Top-level SSE endpoint orchestrator
│   ├── browser_phases.py            # Phases 1-3: setup, navigate, initial capture
│   ├── overlay_pipeline.py          # Phase 4: overlay detect → click → extract
│   ├── overlay_steps.py             # Sub-step functions for overlay pipeline
│   ├── analysis_pipeline.py         # Phase 5: concurrent AI analysis & scoring
│   └── sse_helpers.py               # SSE formatting & serialization helpers
├── models/                          # Pydantic data models
│   ├── tracking_data.py             # Cookies, scripts, storage, network models
│   ├── consent.py                   # Consent detection & extraction models
│   ├── analysis.py                  # Analysis results & scoring models
│   ├── partners.py                  # Partner classification models
│   └── browser.py                   # Navigation, access denial & device models
├── data/                            # Static pattern databases
│   ├── loader.py                    # JSON data loader with caching
│   ├── partners/                    # Partner risk databases (8 JSON files)
│   └── trackers/                    # Script pattern databases (2 JSON files)
└── utils/                           # Cross-cutting utilities
    ├── errors.py                    # Error message extraction
    ├── image.py                     # Screenshot optimisation & JPEG conversion
    ├── json_parsing.py              # LLM response JSON parsing
    ├── logger.py                    # Structured logger with colour output
    ├── serialization.py             # Pydantic model serialization helpers
    └── url.py                       # URL / domain utilities
```

## Microsoft Agent Framework

The server uses the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (`agent-framework-core` package) for all AI-powered analysis.  All agents subclass `BaseAgent`, which provides shared infrastructure for creating `ChatAgent` instances with middleware, structured output, and LLM client management.

### How It Works

1. `BaseAgent.initialise()` creates a `ChatClientProtocol` via the `llm_client` factory (supports Azure OpenAI and standard OpenAI)
2. `BaseAgent._build_agent()` constructs a `ChatAgent` with the agent's system prompt, `ChatOptions` (including `response_format` for structured JSON output), and middleware (`RetryChatMiddleware`, `TimingChatMiddleware`)
3. Agents call `_complete()` for text-only prompts or `_complete_vision()` for multimodal prompts (screenshot + text)
4. Responses are parsed into Pydantic models via `AgentResponse.try_parse_value()`

### Agents

| Agent | Input | Output | Description |
|-------|-------|--------|-------------|
| `ConsentDetectionAgent` | Screenshot | `CookieConsentDetection` | Vision-only detection of consent dialogs and overlay dismiss buttons |
| `ConsentExtractionAgent` | Screenshot + DOM text | `ConsentDetails` | Extracts consent categories, partners, purposes from consent dialogs |
| `ScriptAnalysisAgent` | Script URL + content | `str` description | Identifies and describes unknown JavaScript files |
| `SummaryFindingsAgent` | Analysis markdown | `list[SummaryFinding]` | Distils full analysis into 5-7 prioritized findings |
| `TrackingAnalysisAgent` | Tracking summary | Markdown report | Comprehensive privacy analysis (supports streaming via `run_stream()`) |

### Infrastructure

| Module | Purpose |
|--------|---------|
| `base.py` | `BaseAgent` — shared agent factory with structured output and Azure schema fixes |
| `config.py` | LLM configuration from environment variables (Azure OpenAI / standard OpenAI) |
| `llm_client.py` | Chat client factory using `agent_framework.azure` and `agent_framework.openai` |
| `middleware.py` | `TimingChatMiddleware` (logs duration) + `RetryChatMiddleware` (exponential backoff for 429/5xx) |
