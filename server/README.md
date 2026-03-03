# Meddling Kids - Server

Python FastAPI backend that orchestrates browser automation and AI-powered tracking analysis. A single Chrome instance is started at app startup via `PlaywrightManager` and shared across all requests; each request gets an isolated `BrowserContext` (~50 ms to create). Uses Playwright (async API) in headed mode on a virtual display (Xvfb) to avoid bot detection. Real Chrome is preferred over bundled Chromium for genuine TLS fingerprints that bypass CDN-level bot detectors. AI agents are built on the **Microsoft Agent Framework** (`agent-framework-core` package).

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Playwright (with Chrome browser; falls back to bundled Chromium)

## Setup

```bash
cd server
uv sync
uv run playwright install --with-deps chrome
uv run playwright install chromium
```

## Environment Variables

### Azure OpenAI (checked first)
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI resource endpoint URL
- `AZURE_OPENAI_API_KEY` - API key for authentication
- `AZURE_OPENAI_DEPLOYMENT` - Name of the deployed model (must support vision, e.g., `gpt-5.2-chat`)
- `OPENAI_API_VERSION` - API version (default: `2024-12-01-preview`)

### Per-Agent Deployment Overrides
- `AZURE_OPENAI_SCRIPT_DEPLOYMENT` - Alternative deployment for the `ScriptAnalysisAgent` (e.g., `gpt-5.1-codex-mini`). Falls back to `AZURE_OPENAI_DEPLOYMENT` when unset

### Standard OpenAI (fallback)
- `OPENAI_API_KEY` - API key for authentication
- `OPENAI_MODEL` - Model name (must support vision, e.g., `gpt-5.2-chat`)
- `OPENAI_BASE_URL` - Optional custom base URL

### Server
- `UVICORN_HOST` - Server host (default: `0.0.0.0`)
- `UVICORN_PORT` - Server port (default: `3001`)
- `WRITE_TO_FILE` - Set to `true` to write logs and reports to files
- `MAX_CONCURRENT_SESSIONS` - Maximum number of concurrent analysis sessions (default: `3`)
- `SHOW_UI` - Set to `true` to serve the built client UI from the server (default: `false`)
- `CORS_ALLOWED_ORIGINS` - Comma-separated list of allowed CORS origins (default: `http://localhost:5173,http://localhost:4173`)

### Observability (Optional)
- `APPLICATIONINSIGHTS_CONNECTION_STRING` - Azure Application Insights connection string for Agent Framework telemetry (traces, logs, metrics)

## Running

```bash
# Development
cd server
uv run uvicorn src.main:app --reload --port 3001 --env-file ../.env
```

## Architecture

```
src/
├── main.py                          # FastAPI app entry point (lifespan: starts/stops PlaywrightManager, CORS, cache-control middleware, API routes)
├── agents/                          # AI agents (Microsoft Agent Framework)
│   ├── base.py                      # BaseAgent with structured output support
│   ├── config.py                    # LLM configuration (pydantic-settings BaseSettings) with per-agent deployment overrides and cached validation
│   ├── llm_client.py                # Chat client factory (supports per-agent deployment overrides and Responses API)
│   ├── middleware.py                # Timing & retry middleware (token estimation, OutputTruncatedError)
│   ├── consent_detection_agent.py   # Vision agent for page overlays (consent, sign-in, newsletter, paywall); reason field constrained to max 120 chars / 15 words
│   ├── consent_extraction_agent.py  # Extract consent details agent
│   ├── script_analysis_agent.py     # Script identification agent (Responses API for codex deployments)
│   ├── structured_report_agent.py   # Structured privacy report agent
│   ├── summary_findings_agent.py    # Summary findings agent
│   ├── tracking_analysis_agent.py   # Main tracking analysis agent
│   ├── cookie_info_agent.py         # Cookie information lookup agent (LLM fallback)
│   ├── storage_info_agent.py        # Storage key information lookup agent (LLM fallback)
│   ├── observability_setup.py       # Azure Monitor / App Insights telemetry setup
│   ├── gdpr_context.py              # Shared GDPR/TCF reference builder for agent prompts
│   ├── prompts/                     # System prompts (one module per agent)
│   │   ├── consent_detection.py     # Consent detection prompt
│   │   ├── consent_extraction.py    # Consent extraction prompt
│   │   ├── cookie_info.py           # Cookie information lookup prompt
│   │   ├── script_analysis.py       # Script analysis prompt
│   │   ├── storage_info.py          # Storage key information lookup prompt
│   │   ├── structured_report.py     # Structured report section prompts
│   │   ├── summary_findings.py      # Summary findings prompt
│   │   └── tracking_analysis.py     # Tracking analysis prompt
│   └── scripts/                     # JavaScript snippets evaluated in-browser
│       ├── extract_consent_text.js  # Extract consent dialog text from DOM
│       ├── extract_iframe_text.js   # Extract text from consent iframes
│       └── get_consent_bounds.js    # Locate consent dialog bounding box for screenshot cropping
├── browser/                         # Browser automation
│   ├── manager.py                   # PlaywrightManager singleton — shared Chrome lifecycle (start once, create isolated BrowserContext per request, auto-recovery on crash)
│   ├── session.py                   # Per-request BrowserSession wrapping an isolated BrowserContext (context-only cleanup, screenshot timeout config, initiator domain & redirect chain capture)
│   ├── access_detection.py          # Bot blocking / CAPTCHA detection
│   └── device_configs.py            # Device emulation profiles
├── consent/                         # Consent handling
│   ├── click.py                     # Multi-strategy consent button clicker (deadline-based timeout management)
│   ├── constants.py                 # Shared consent-manager detection constants, selectors, and utilities
│   ├── detection.py                 # Overlay detection orchestration
│   ├── extraction.py                # Consent detail extraction orchestration
│   ├── overlay_cache.py             # Domain-level cache for overlay strategies (locator strategy, frame type, consent platform, JSON); includes backfill_consent_platform() for late CMP detection
│   ├── partner_classification.py    # Consent partner risk classification and URL enrichment
│   ├── platform_detection.py        # CMP detection (cookies, media groups, DOM) and deterministic button selectors
│   └── text_parser.py               # Local regex-based consent text parser (categories, TCF purposes, partners, CMP platform detection)
├── analysis/                        # Tracking analysis & scoring
│   ├── tracking.py                  # Streaming LLM tracking analysis
│   ├── scripts.py                   # Script identification (patterns → cache → LLM helpers)
│   │                                #   _match_known_patterns() + _analyze_unknowns()
│   │                                #   Incremental cache saves (each script saved immediately after LLM analysis)
│   ├── script_cache.py              # Script analysis cache per script domain (base URL + MD5 hash, cross-site, JSON)
│   ├── script_grouping.py           # Group similar scripts to reduce noise
│   ├── tracker_patterns.py          # Regex patterns for tracker classification (with combined alternation)
│   ├── tracking_summary.py          # Summary builder for LLM input & pre-consent stats
│   ├── domain_cache.py              # Domain knowledge cache for cross-run consistency (merge-on-save, JSON)
│   ├── cookie_lookup.py             # Cookie info lookup (consent DB → tracking patterns → LLM fallback)
│   ├── storage_lookup.py            # Storage key info lookup (tracking patterns → LLM fallback)
│   ├── tcf_lookup.py                # TCF purpose matching (purpose strings → IAB TCF v2.2 taxonomy)
│   ├── tc_string.py                 # TC/AC String decoder & 5-tier discovery (cookies → CMP profile → JSON storage → heuristic → JSON heuristic)
│   ├── tc_validation.py             # TC String validation (cross-references consent signals with observed tracking)
│   ├── vendor_lookup.py             # Vendor name resolution (GVL vendor IDs + Google ATP provider IDs → names)
│   ├── cookie_decoders.py           # Structured cookie decoders (OneTrust, Cookiebot, GA, FB, Google Ads, USP, GPC/DNT, GPP)
│   ├── domain_classifier.py         # Three-tier domain classification (Disconnect + partner DBs + keyword heuristics, no LLM)
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
│   ├── stream.py                    # Top-level SSE orchestrator (_StreamContext + phase generators); late CMP detection with consent_platform backfill
│   ├── browser_phases.py            # Phases 1-3: navigate, page load, access check, initial data capture
│   ├── overlay_pipeline.py          # Phase 4: run() → _try_cmp_specific_dismiss() → _run_vision_loop() → _click_and_capture()
│   ├── overlay_steps.py             # Sub-step functions for overlay pipeline (screenshot error recovery)
│   ├── analysis_pipeline.py         # Phase 5: concurrent AI analysis & scoring
│   └── sse_helpers.py               # SSE formatting, serialization helpers & screenshot capture with error recovery
├── models/                          # Pydantic data models
│   ├── tracking_data.py             # Cookies, scripts, storage, network models
│   ├── consent.py                   # Consent detection & extraction models
│   ├── analysis.py                  # Analysis results & scoring models
│   ├── partners.py                  # Partner classification models
│   ├── report.py                    # Structured report section models
│   └── browser.py                   # Navigation, access denial & device models
├── data/                            # Static data and reference databases
│   ├── loader.py                    # JSON data loader with caching
│   ├── consent/                     # Consent and GDPR/TCF reference data
│   │   ├── consent-platforms.json   # 19 CMP profiles with DOM selectors, button patterns, and cookie indicators
│   │   ├── consent-cookies.json     # Known consent-state cookie names (TCF and CMP)
│   │   ├── gdpr-reference.json      # GDPR lawful bases, principles, and ePrivacy cookie categories
│   │   ├── tcf-purposes.json        # IAB TCF v2.2 purpose definitions and special features
│   │   ├── gvl-vendors.json         # IAB Global Vendor List — 1,111 vendor ID→name mappings
│   │   └── google-atp-providers.json # Google Additional Consent providers — 598 provider ID→name mappings
│   ├── partners/                    # Partner risk databases (8 JSON files, 574 entries)
│   ├── publishers/                  # Media group profiles
│   │   └── media-groups.json        # 16 UK media group profiles (vendors, ad tech, data practices)
│   └── trackers/                    # Tracking pattern databases (7 JSON files)
│       ├── tracking-scripts.json    # 493 regex patterns for known trackers
│       ├── benign-scripts.json      # 52 patterns for safe libraries
│       ├── tracking-cookies.json    # Known tracking cookie definitions (137 cookies)
│       ├── tracking-storage.json    # Known storage key definitions (185 keys)
│       ├── tracker-domains.json     # Known tracker domain database (4,644 domains)
│       ├── cname-domains.json       # CNAME cloaking tracker domains (122,018 domains)
│       └── disconnect-services.json # Disconnect Tracking Protection list (4,370 domains)
└── utils/                           # Cross-cutting utilities
    ├── cache.py                     # Cross-cache management (clear_all) and atomic file writes (atomic_write_text)
    ├── errors.py                    # Error message extraction and client-safe error sanitisation
    ├── image.py                     # Screenshot optimisation, JPEG conversion & consent dialog cropping
    ├── json_parsing.py              # LLM response JSON parsing
    ├── logger.py                    # Structured logger with colour output (contextvars isolation)
    ├── risk.py                      # Shared risk-scoring helpers (risk_label)
    ├── serialization.py             # Pydantic model serialization helpers
    ├── url.py                       # URL / domain utilities and SSRF prevention (validate_analysis_url)
    └── usage_tracking.py            # Per-session LLM call count and token usage tracking
```

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/open-browser-stream` | SSE endpoint for real-time URL analysis (params: `url`, `device`, `clear-cache`) |
| POST | `/api/clear-cache` | Clears all analysis caches (scripts, domain, overlay) |
| POST | `/api/cookie-info` | Looks up cookie information (database-first, LLM fallback) |
| POST | `/api/storage-info` | Looks up storage key information (database-first, LLM fallback) |
| POST | `/api/storage-key-info` | Looks up storage key information (alias) |
| POST | `/api/domain-info` | Looks up domain information |
| POST | `/api/tcf-purposes` | Maps consent purpose strings to IAB TCF v2.2 taxonomy |
| POST | `/api/tc-string-decode` | Decodes an IAB TCF v2 TC String (deterministic, no LLM) |
| POST | `/api/fetch-script` | Fetches remote JavaScript source for the script viewer (512 KB cap, 10 s timeout) |
| GET | `/{full_path:path}` | SPA catch-all — serves the built client UI (when `SHOW_UI=true`) |

## Linting and Formatting

The server uses [ruff](https://docs.astral.sh/ruff/) for linting/formatting and
[mypy](https://mypy.readthedocs.io/) for static type checking, orchestrated by
[poethepoet](https://poethepoet.naber.dev/) task runner.

```bash
cd server

poe lint          # Run all linting (ruff check + format check + mypy)
poe lint:ruff     # Run ruff linter and format check only
poe lint:mypy     # Run mypy type checking only
poe format        # Auto-fix ruff lint issues and format code
poe test          # Run unit tests
```

Configuration for all tools is in `pyproject.toml`.

## Microsoft Agent Framework

The server uses the [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) (`agent-framework-core` package) for all AI-powered analysis.  All agents subclass `BaseAgent`, which provides shared infrastructure for creating `Agent` instances with middleware, structured output, and LLM client management.

### How It Works

1. `BaseAgent.initialise()` creates a `SupportsChatGetResponse` client via the `llm_client` factory (supports Azure OpenAI and standard OpenAI)
2. `BaseAgent._build_agent()` constructs an `Agent` with the agent's system prompt, `ChatOptions` (including `response_format` for structured JSON output), and middleware (`RetryChatMiddleware`, `TimingChatMiddleware`)
3. Agents call `_complete()` for text-only prompts or `_complete_vision()` for multimodal prompts (screenshot + text)
4. Responses are parsed into Pydantic models via `BaseAgent._parse_response()`, which calls `model.model_validate_json(response.text)` directly

### Agents

| Agent | Input | Output | Description |
|-------|-------|--------|-------------|
| `ConsentDetectionAgent` | Screenshot | `CookieConsentDetection` | Vision-only detection of page overlays (consent, sign-in, newsletter, paywall) and their dismiss buttons. Uses a 30 s per-call timeout and 2 retries. Returns `error=True` on timeout (distinct from "not found"). The `reason` field is constrained to max 120 characters / 15 words for concise output |
| `ConsentExtractionAgent` | Screenshot + DOM text + consent bounds | `ConsentDetails` | Three-tier consent extraction: a local regex parser (`text_parser`) always runs alongside the LLM vision call. Screenshots are cropped to the dialog bounding box when bounds are available. The LLM is authoritative for categories, partners, and purposes; the local parse supplements `has_manage_options` and `claimed_partner_count`. If the LLM vision call times out, a text-only LLM fallback (10 s timeout) is attempted before falling to the local parse as sole source |
| `ScriptAnalysisAgent` | Script URL + content | `str` description | Identifies and describes unknown JavaScript files. Uses the Responses API when targeting a codex deployment |
| `StructuredReportAgent` | Tracking data + consent + GDPR/TCF reference | `StructuredReport` | Generates structured privacy report with 9 concurrent section LLM calls (2 waves) and deterministic overrides. Uses a 60 s per-call timeout (large prompts on complex sites) |
| `SummaryFindingsAgent` | Analysis markdown + consent details + tracking metrics | `list[SummaryFinding]` | Distils full analysis into 6 prioritized findings with deterministic metric anchoring |
| `TrackingAnalysisAgent` | Tracking summary + GDPR/TCF reference | Markdown report | Comprehensive privacy analysis with GDPR/ePrivacy context (supports streaming via `run(stream=True)` with a 60 s inactivity timeout) |
| `CookieInfoAgent` | Cookie name + domain + value | `CookieInfoResult` | Explains individual cookies (purpose, who sets it, risk level, privacy note). LLM fallback for cookies not found in known databases |
| `StorageInfoAgent` | Storage key + type + value | `StorageInfoResult` | Explains individual storage keys (purpose, who sets it, risk level, privacy note). LLM fallback for keys not found in known databases |

### Infrastructure

| Module | Purpose |
|--------|---------|
| `base.py` | `BaseAgent` — shared agent factory with structured output, Azure schema fixes, configurable `call_timeout` (default 30 s) passed to `RetryChatMiddleware`, and `use_responses_api` flag for Responses API client selection |
| `config.py` | LLM configuration via `pydantic-settings` `BaseSettings` (Azure OpenAI / standard OpenAI) with per-agent deployment overrides (`get_agent_deployment()`). `validate_llm_config()` is cached with `@functools.lru_cache(maxsize=1)` |
| `llm_client.py` | Chat client factory using `agent_framework.azure` and `agent_framework.openai` — supports `deployment_override` for per-agent model selection and `use_responses_api` for creating `AzureOpenAIResponsesClient` instances (auto-upgrades API version to `2025-03-01-preview` minimum when needed) |
| `middleware.py` | `TimingChatMiddleware` (logs duration + token estimation before each call) + `RetryChatMiddleware` (exponential backoff for 429/5xx, per-call timeout via `asyncio.wait_for`, global concurrency semaphore limiting to 10 in-flight LLM calls). Raises `OutputTruncatedError` (non-retryable) when `finish_reason=length` produces an empty response |
| `gdpr_context.py` | Shared GDPR/TCF reference builder — assembles TCF purposes, consent cookies, lawful bases, and ePrivacy categories into a compact reference block for agent prompts |
