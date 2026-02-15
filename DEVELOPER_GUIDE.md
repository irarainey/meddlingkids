# Developer Guide

This guide explains the architecture, workflow, and data flow of the Meddling Kids tracking analysis application.

## Table of Contents

1. [Overview](#overview)
2. [High-Level Architecture](#high-level-architecture)
3. [Application Workflow](#application-workflow)
4. [Client Architecture](#client-architecture)
5. [Server Architecture](#server-architecture)
6. [Data Flow](#data-flow)
7. [Key Data Types](#key-data-types)
8. [SSE Events Reference](#sse-events-reference)
9. [Caching](#caching)
10. [Adding New Features](#adding-new-features)

---

## Overview

Meddling Kids is a full-stack application that analyzes website tracking behavior. It consists of:

- **Client**: Vue 3 SPA that initiates analysis and displays results
- **Server**: Python FastAPI application that orchestrates browser automation and AI analysis
- **Playwright**: Browser automation (async Python API) for page loading and data capture
- **Xvfb**: Virtual display that allows headed browser mode without a visible window
- **Microsoft Agent Framework**: AI agent infrastructure with Azure OpenAI / OpenAI backends for consent detection, script analysis, and privacy analysis

> **Why Headed Mode?** Ad networks and bot-detection services (e.g. Tollbit) often detect and block headless browsers. By running real Chrome in headed mode on a virtual display (Xvfb), with anti-bot hardening (webdriver removal, fake plugins, WebGL/AudioContext/MediaDevices spoofing), the browser appears identical to a real user's browser, allowing ads to load correctly while remaining invisible.

Communication happens via **Server-Sent Events (SSE)**, allowing real-time progress updates during the multi-step analysis process.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                  CLIENT                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  App.vue                                                             │   │
│  │  - URL input bar                                                     │   │
│  │  - Device selector                                                   │   │
│  │  - Tab navigation                                                    │   │
│  │  - Dialog components                                                 │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  useTrackingAnalysis.ts (Composable)                                 │   │
│  │  - All reactive state                                                │   │
│  │  - SSE connection management                                         │   │
│  │  - Event handlers                                                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ EventSource (SSE)
                                     │ GET /api/open-browser-stream?url=...&device=...&clear-cache=...
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                                  SERVER                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  pipeline/stream.py (SSE Orchestrator)                               │  │
│  │  - Orchestrates the 6-phase analysis workflow                        │  │
│  │  - Sends SSE events back to client                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│          ┌─────────────────────────┼─────────────────────────┐             │
│          ▼                         ▼                         ▼             │
│  ┌────────────────────┐  ┌─────────────────────┐     ┌─────────────────┐   │
│  │ browser/           │  │ consent/            │     │ analysis/       │   │
│  │ - Playwright async │  │ - Detection (AI)    │     │ - Tracking      │   │
│  │ - Navigation       │  │ - Extraction (AI)   │     │ - Risk analysis │   │
│  │ - Capture          │  │ - Click strategies  │     │ - Privacy score │   │
│  │ - Per-request      │  └─────────────────────┘     └─────────────────┘   │
│  └────────────────────┘                                                    │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SERVICES                              │
│                                                                             │
│   ┌─────────────────────┐              ┌─────────────────────┐              │
│   │  Target Website     │              │  Azure OpenAI       │              │
│   │  (via Playwright)   │              │  or OpenAI API      │              │
│   └─────────────────────┘              └─────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Application Workflow

The analysis follows a 6-phase workflow, orchestrated by `pipeline/stream.py`:

### Phase 1: Browser Setup and Navigation
```
Client: User clicks "Unmask" button
   │
   ▼
analyzeUrl() in useTrackingAnalysis.ts
   │ Creates EventSource connection
   ▼
analyze_url_stream() in pipeline/stream.py
   │
   ├── If clear_cache=True → cache_util.clear_all()
   ├── validate_openai_config() → Check env vars
   ├── BrowserSession() → Create isolated session
   ├── session.clear_tracking_data() → Reset tracking arrays
   ├── await session.launch_browser(device_type) → Start real Chrome (Chromium fallback)
   │   └── Anti-bot hardening: webdriver removal, plugins, WebGL, AudioContext, MediaDevices
   └── await session.navigate_to(url) → Load target page
```

### Phase 2: Wait for Page Load and Check Access
```
navigate_to() returns
   │
   ├── Check HTTP status code
   │   └── If error → send_event('pageError', {...})
   │
   ├── wait_for_network_idle(3000)
   │   └── Short 3s race — ad-heavy sites never fully idle
   │   └── Proceeds with loaded DOM if timeout (normal)
   │
   ├── wait_for_timeout(2000)
   │   └── Grace period for consent banners and overlays to render
   │
   └── check_for_access_denied()
       └── If blocked → send_event('pageError', {...}) + screenshot
```

### Phase 3: Initial Data Capture
```
Page loaded successfully
   │
   ├── capture_current_cookies() → Intercept all cookies
   ├── capture_storage() → Read localStorage/sessionStorage
   ├── take_screenshot() → PNG screenshot (for AI vision)
   │   └── optimize_screenshot_bytes() → Convert to JPEG (reuses PNG, no second capture)
   │
   └── send_event('screenshot', {
         screenshot,      // base64 JPEG
         cookies,         // TrackedCookie[]
         scripts,         // TrackedScript[]
         networkRequests, // NetworkRequest[]
         localStorage,    // StorageItem[]
         sessionStorage   // StorageItem[]
       })
```

### Phase 4: Overlay Detection and Handling
```
OverlayPipeline.run()
   │
   │   Sub-step functions live in overlay_steps.py;
   │   OverlayPipeline orchestrates control flow only.
   │
   ├── 1. Try cached overlays first (_try_cached_overlays)
   │   └── For each cached overlay in overlay_cache:
   │       ├── Locate cached button in DOM (by locator strategy + text)
   │       ├── _prefer_accept_button() → Replace reject-style with accept if available
   │       ├── Click → capture_after_click()
   │       └── On failure → mark as failed, fall through to vision
   │
   ├── 2. Vision detection loop (up to 5 iterations)
   │   │
   │   ├── steps.detect_overlay(screenshot)
   │   │   └── AI vision-only analysis (viewport screenshot, JPEG, max 1280px)
   │   │       Returns: { found, overlay_type, button_text, certainty }
   │   │   └── Runs concurrently with pending extraction via asyncio.gather
   │   │
   │   ├── _retry_validate_in_dom(page, detection)
   │   │   └── DOM validation with retry (4 × 1.5s) for first cookie-consent
   │   │   └── Tracks failed signatures to avoid re-detecting unclickable elements
   │   │
   │   ├── _prefer_accept_button(page, detection, found_in_frame)
   │   │   └── If button text matches reject pattern → search for accept alternative
   │   │   └── Uses REJECT_BUTTON_RE from constants.py
   │   │
   │   ├── steps.try_overlay_click(page, detection, found_in_frame)
   │   │   └── Phase 0: Try validated frame first (skip main-frame scan)
   │   │   └── Phase 1: Main frame button role match
   │   │   └── Phase 2: Consent iframes
   │   │   └── Phase 3: Generic heuristics
   │   │   └── Tri-state safety check (is_safe_to_click)
   │   │   └── Returns ClickResult (success, locator_strategy, frame_type)
   │   │
   │   ├── steps.capture_after_click(session, page, detection)
   │   │   └── Waits for DOM, captures cookies, takes screenshot
   │   │
   │   ├── If first cookie-consent overlay:
   │   │   ├── steps.capture_consent_content() → Read-only pre-dismiss capture
   │   │   │   └── Extracts text from consent iframes and main-frame containers
   │   │   │   └── Uses constants.is_consent_frame() and CONSENT_CONTAINER_SELECTORS
   │   │   └── Start extraction as asyncio.create_task (concurrent)
   │   │       └── AI extracts partners, categories, purposes
   │   │       └── Events yielded when both extraction and next detection complete
   │   │
   │   └── send_event('screenshot', {...}) → Post-dismissal screenshot
   │
   ├── overlay_cache.merge_and_save() → Persist cache for repeat visits
   │
   └── If overlays dismissed → wait for network idle (post-consent settle)
```

### Phase 5: AI Analysis
```
All data captured
   │
   ├── ┌─────────────────── Run concurrently ──────────────────┐
   │   │                                                       │
   │   │  analyze_scripts(scripts, domain)                    │
   │   │   ├── Group similar scripts (chunks, vendor bundles)  │
   │   │   ├── Match against tracking patterns (JSON)          │
   │   │   ├── Match against benign patterns (JSON)            │
   │   │   ├── Check script cache (URL + MD5 content hash)     │
   │   │   └── LLM analysis for uncached unknown scripts       │
   │   │       (concurrent with semaphore, max 10 at a time)   │
   │   │                                                       │
   │   │  stream_tracking_analysis(summary, consent, stats)    │
   │   │   ├── build_tracking_summary() → Data for LLM         │
   │   │   ├── GDPR/TCF reference data (purposes, lawful       │
   │   │   │   bases, ePrivacy categories, consent cookies)     │
   │   │   ├── Pre-consent page-load stats                     │
   │   │   ├── Media group context (if domain recognised)      │
   │   │   └── Main analysis prompt → Full markdown report     │
   │   │                                                       │
   │   │                                                       │
   │   │  calculate_privacy_score() → Deterministic 0-100      │
   │   │                                                       │
   │   │  summarise(analysis_text, score, consent, metrics)    │
   │   │   ├── Deterministic consent facts (partner counts)    │
   │   │   ├── Deterministic tracking metrics (exact counts)   │
   │   │   ├── Pre-consent page-load stats                     │
   │   │   └── Domain knowledge context                        │
   │   │                                                       │
   │   │  build_structured_report(tracking_summary, consent)   │
   │   │   ├── 9 concurrent section LLM calls                  │
   │   │   ├── GDPR/TCF reference data                         │
   │   │   ├── Deterministic overrides (partner count,         │
   │   │   │   domain count, cookie count, storage counts)      │
   │   │   └── Vendor URL enrichment from partner databases    │
   │   │                                                       │
   │   └───────────────────────────────────────────────────────┘
   │
   └── Script analysis and tracking analysis run concurrently
       Scoring, structured report, and summary run after analysis
       Both tasks share a progress queue for merged SSE updates
```

### Phase 6: Complete
```
Analysis complete
   │
   └── send_event('complete', {
         success,
         analysis,          // Full markdown report
         structuredReport,  // Per-section structured report
         summaryFindings,   // Structured findings array
         privacyScore,      // 0-100
         privacySummary,    // One sentence
         scoreBreakdown,    // Detailed score breakdown
         analysisSummary,   // Aggregate statistics
         analysisError,     // Error message if analysis failed
         consentDetails,    // Consent dialog info
         scripts,           // Scripts with descriptions
         scriptGroups,      // Grouped similar scripts
         debugLog           // Server debug log lines
       })
   │
   └── await session.close() → Cleanup Playwright (in finally block)
```

---

## Client Architecture

### State Management

All state lives in `useTrackingAnalysis.ts` composable:

```typescript
// Input state
inputValue           // URL text field
deviceType           // Selected device emulation

// Loading state
isLoading            // Analysis in progress
isComplete           // Analysis finished
statusMessage        // Current status text
progressPercent      // 0-100 progress

// Captured data
screenshots          // base64 images (up to 3)
cookies              // TrackedCookie[]
scripts              // TrackedScript[]
scriptGroups         // ScriptGroup[] (grouped similar scripts)
networkRequests      // NetworkRequest[]
localStorage         // StorageItem[]
sessionStorage       // StorageItem[]

// Analysis results
analysisResult       // Full markdown report
structuredReport     // Structured per-section report
summaryFindings      // Structured findings array
privacyScore         // 0-100
privacySummary       // One-sentence summary
consentDetails       // Extracted consent info
analysisError        // Error message if AI analysis failed
debugLog             // Server debug log lines

// Dialog state
showScoreDialog      // Privacy score popup
showPageErrorDialog  // Access denied popup
showErrorDialog      // Generic error popup
errorDialog          // { title, message }
pageError            // { type, message, statusCode }
selectedScreenshot   // Currently selected screenshot index
```

### SSE Event Handling

```typescript
// In analyzeUrl():
const eventSource = new EventSource(`/api/open-browser-stream?url=...&device=...&clear-cache=...`)

eventSource.addEventListener('progress', (e) => {
  // Update loading indicators
})

eventSource.addEventListener('screenshot', (e) => {
  // Add screenshot, update data arrays
})

eventSource.addEventListener('pageError', (e) => {
  // Show error dialog
})

eventSource.addEventListener('consentDetails', (e) => {
  // Store consent information
})

eventSource.addEventListener('complete', (e) => {
  // Store analysis results, show score dialog
})

eventSource.addEventListener('error', (e) => {
  // Show error dialog
})
```

### Component Hierarchy

```
App.vue
├── ProgressBanner (loading state)
├── ScoreDialog (privacy score popup)
├── PageErrorDialog (access denied)
├── ErrorDialog (generic errors)
├── ScreenshotGallery (thumbnail row + modal)
└── Tab Content (v-if="isComplete")
    ├── AnalysisTab
    ├── CookiesTab
    ├── StorageTab
    ├── NetworkTab
    ├── ScriptsTab
    └── DebugLogTab (debug mode only, enabled via ?debug=true in the URL)
```

---

## Server Architecture

### Agent Layer

AI interactions use the **Microsoft Agent Framework** (`agent-framework-core` package). Each agent subclasses `BaseAgent` and defines its own response model and token limits. System prompts are stored in the `agents/prompts/` directory — one module per agent — keeping prompt text separate from agent logic.

Key framework types used:
- `agent_framework.ChatAgent` — orchestrates a chat conversation with middleware
- `agent_framework.ChatClientProtocol` — abstraction over LLM backends (Azure OpenAI, OpenAI)
- `agent_framework.ChatMiddleware` — pluggable request/response pipeline
- `agent_framework.ChatMessage` / `agent_framework.Content` — message types (text + multimodal)
- `agent_framework.ChatOptions` — token limits and structured output (`response_format`)
- `agent_framework.AgentResponse` — typed response with `try_parse_value()` for Pydantic parsing

| Agent | Module | Responsibility |
|-------|--------|---------------|
| `ConsentDetectionAgent` | `consent_detection_agent.py` | Vision-only detection of blocking overlays and locate dismiss buttons |
| `ConsentExtractionAgent` | `consent_extraction_agent.py` | Extract consent dialog details (categories, partners, purposes) |
| `ScriptAnalysisAgent` | `script_analysis_agent.py` | Identify and describe unknown scripts via LLM |
| `SummaryFindingsAgent` | `summary_findings_agent.py` | Generate structured summary findings with deterministic metric anchoring |
| `StructuredReportAgent` | `structured_report_agent.py` | Generate structured privacy report with 9 concurrent section LLM calls, deterministic overrides, and vendor URL enrichment |
| `TrackingAnalysisAgent` | `tracking_analysis_agent.py` | Full privacy analysis report (streaming markdown) with GDPR/TCF context |

| Infrastructure | Module | Responsibility |
|----------------|--------|---------------|
| `BaseAgent` | `base.py` | Shared agent factory with middleware, structured output, Azure schema fixes |
| `Config` | `config.py` | LLM configuration via `pydantic-settings` `BaseSettings` (Azure / OpenAI) |
| `LLM Client` | `llm_client.py` | Chat client factory (`ChatClientProtocol`) |
| `Middleware` | `middleware.py` | `TimingChatMiddleware` (duration + token usage tracking) + `RetryChatMiddleware` with exponential backoff |
| `Observability` | `observability_setup.py` | Azure Monitor / Application Insights telemetry configuration |
| `Prompts` | `prompts/` | System prompts for each agent, one module per agent |

### Domain Packages

Domain packages orchestrate browser automation and data processing. They call agents for AI tasks.

**`browser/`** — Browser automation

| Module | Responsibility |
|--------|---------------|
| `session.py` | Playwright async browser session (per-request isolation, real Chrome with anti-bot hardening) |
| `device_configs.py` | Device emulation profiles (iPhone, iPad, Android, etc.) |
| `access_detection.py` | Bot blocking and access denial detection patterns |

**`consent/`** — Consent handling

| Module | Responsibility |
|--------|---------------|
| `detection.py` | Overlay detection orchestration |
| `extraction.py` | Consent detail extraction orchestration |
| `click.py` | Click strategies for consent buttons (per-strategy deadline checking to prevent timeout cascades) |
| `constants.py` | Shared consent-manager host keywords, exclusion lists, container selectors, reject-button regex, and `is_consent_frame()` utility |
| `overlay_cache.py` | Domain-level cache for overlay dismissal strategies — stores Playwright locator strategy, button text, and frame type per overlay (JSON) |
| `partner_classification.py` | Classify consent partners by risk level and enrich partner URLs from partner databases |

**`analysis/`** — Tracking analysis and scoring

| Module | Responsibility |
|--------|---------------|
| `tracking.py` | Main tracking analysis orchestration (streaming LLM) |
| `scripts.py` | Script identification (patterns + LLM via agent + script cache) |
| `script_cache.py` | Script analysis cache — caches LLM-generated descriptions by URL + MD5 content hash. Invalidates on hash mismatch |
| `script_grouping.py` | Group similar scripts (chunks, vendor bundles) to reduce noise |
| `tracker_patterns.py` | Regex pattern data for tracker classification (with pre-compiled combined alternation) |
| `tracking_summary.py` | Summary builder for LLM input and pre-consent stats |
| `domain_cache.py` | Domain-level knowledge cache — persists LLM classifications (tracker categories, cookie groupings, vendor roles, severity levels) for consistency across repeat analyses of the same domain. Uses merge-on-save with scan-count-based staleness pruning |
| `scoring/` | Decomposed privacy scoring package (0-100) |
| `scoring/calculator.py` | Orchestrator — calls each category scorer, applies calibration curve |
| `scoring/advertising.py` | Ad networks, retargeting cookies, RTB infrastructure |
| `scoring/consent.py` | Pre-consent tracking, partner counts/risk, disclosure quality |
| `scoring/cookies.py` | Cookie volume, third-party cookies, known tracking patterns |
| `scoring/data_collection.py` | localStorage, beacons/pixels, analytics trackers |
| `scoring/fingerprinting.py` | Session-replay, cross-device identity, behavioural tracking |
| `scoring/sensitive_data.py` | Sensitive PII (location, health, political, financial) |
| `scoring/social_media.py` | Social media pixels, SDKs, embedded plugins |
| `scoring/third_party.py` | Third-party domain count, request volume, known trackers |

**`pipeline/`** — SSE streaming orchestration

| Module | Responsibility |
|--------|---------------|
| `stream.py` | Top-level SSE endpoint orchestrator (6-phase workflow, cache clearing) |
| `browser_phases.py` | Phases 1-3: setup, navigate, initial capture |
| `overlay_pipeline.py` | Phase 4: cached overlay → vision detect → click → extract (orchestrator) |
| `overlay_steps.py` | Sub-step functions for overlay pipeline (detect, validate, click, capture content, extract) |
| `analysis_pipeline.py` | Phase 5: concurrent AI analysis and scoring |
| `sse_helpers.py` | SSE formatting and serialization helpers |

### Data Layer

| Module | Content |
|--------|--------|
| `data/loader.py` | JSON data loader with lazy loading and caching |
| `data/trackers/tracking-scripts.json` | 506 regex patterns for known trackers |
| `data/trackers/benign-scripts.json` | 51 patterns for safe libraries |
| `data/partners/*.json` | 556 partner entries across 8 risk categories |
| `data/gdpr/gdpr-reference.json` | GDPR lawful bases, principles, and ePrivacy cookie categories for LLM context |
| `data/gdpr/tcf-purposes.json` | IAB TCF v2.2 purpose definitions and special features for LLM context |
| `data/gdpr/consent-cookies.json` | Known consent-state cookie names (TCF and CMP) for LLM context |
| `data/publishers/media-groups.json` | 16 UK media group profiles (vendors, ad tech partners, data practices) |

**`utils/`** — Cross-cutting utilities

| Module | Responsibility |
|--------|---------------|
| `cache.py` | Cross-cache management — `clear_all()` deletes every file in all cache sub-directories |
| `errors.py` | Error message extraction |
| `usage_tracking.py` | Per-session LLM call count and token usage tracking (`contextvars` isolation) |
| `image.py` | Screenshot optimisation and JPEG conversion |
| `json_parsing.py` | LLM response JSON parsing |
| `logger.py` | Structured logger with colour output (`contextvars` isolation) |
| `risk.py` | Shared risk-scoring helpers (`risk_label`) |
| `serialization.py` | Pydantic model serialization helpers |
| `url.py` | URL and domain utilities |

---

## Data Flow

### From Browser to Client

```
Playwright Browser
    │
    ├── Network requests intercepted → networkRequests[]
    ├── Scripts loaded → scripts[]
    ├── Cookies set → cookies[]
    └── DOM available → localStorage[], sessionStorage[]
    │
    ▼
BrowserSession tracking arrays
    │
    ▼
send_event('screenshot', data) in pipeline/stream.py
    │
    ▼
EventSource message received in client
    │
    ▼
Vue reactive state updated
    │
    ▼
UI components re-render
```

### AI Analysis Flow

```
Tracking data collected
    │
    ▼
build_tracking_summary() → Formatted text for LLM
    │
    ▼
BaseAgent._build_agent() → Creates ChatAgent (agent_framework.ChatAgent)
    │                         with ChatClientProtocol + middleware
    │
    ├── TimingChatMiddleware → Logs duration + records token usage
    ├── RetryChatMiddleware → Handles 429/5xx with backoff
    └── ChatAgent.run() or run_stream() → LLM chat completion
    │
    ▼
Parse response (structured JSON via response_format or streamed markdown)
    │
    ├── Streamed: send_event('analysis-chunk', {text}) per token
    └── Final:    send_event('complete', results)
    │
    ▼
Client displays analysis
```

---

## Key Data Types

### TrackedCookie
```python
class TrackedCookie(BaseModel):
    name: str
    value: str
    domain: str
    path: str
    expires: float
    http_only: bool
    secure: bool
    same_site: str
    timestamp: str
```

### TrackedScript
```python
class TrackedScript(BaseModel):
    url: str
    domain: str
    timestamp: str = ""
    description: str | None = None   # Added by script analysis
    resource_type: str = "script"    # Resource type (script, xhr, etc.)
    group_id: str | None = None      # Group ID if part of a grouped category
    is_grouped: bool | None = None   # Whether this script was grouped with similar scripts
```

### ScriptGroup
```python
class ScriptGroup(BaseModel):
    id: str                # Unique identifier (e.g., 'example.com:app-chunks')
    name: str              # Human-readable name
    description: str       # What this group represents
    count: int             # Number of scripts in this group
    example_urls: list[str]  # Example URLs from the group
    domain: str            # Common domain for the grouped scripts
```

### NetworkRequest
```python
class NetworkRequest(BaseModel):
    url: str
    domain: str
    method: str
    resource_type: str
    is_third_party: bool
    timestamp: str
    status_code: int | None = None
    post_data: str | None = None
    pre_consent: bool = False
```

### ConsentPartner
```python
class ConsentPartner(BaseModel):
    name: str
    purpose: str
    data_collected: list[str]
    risk_level: str | None = None      # Set during partner classification
    risk_category: str | None = None   # Set during partner classification
    risk_score: int | None = None      # Set during partner classification
    concerns: list[str] | None = None  # Set during partner classification
    url: str = ""                      # Enriched from partner databases
```

### ConsentDetails
```python
class ConsentDetails(BaseModel):
    has_manage_options: bool
    categories: list[ConsentCategory]  # [{name, description, required}]
    partners: list[ConsentPartner]     # [{name, purpose, data_collected, ...}]
    purposes: list[str]
    raw_text: str
    claimed_partner_count: int | None = None
```

---

## SSE Events Reference

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `progress` | Server → Client | `{ step, message, progress }` | Loading progress updates |
| `screenshot` | Server → Client | `{ screenshot, cookies, scripts, networkRequests, localStorage, sessionStorage }` | Page capture with all data |
| `screenshotUpdate` | Server → Client | `{ screenshot }` | Replaces the most recent screenshot (background refresh as ads/content load) |
| `pageError` | Server → Client | `{ type, message, statusCode, isAccessDenied?, isOverlayBlocked?, reason? }` | Access denied, HTTP error, or overlay blocked |
| `consentDetails` | Server → Client | `ConsentDetails` | Extracted consent dialog info |
| `analysis-chunk` | Server → Client | `{ text }` | Streamed token from tracking analysis (real-time LLM output) |
| `complete` | Server → Client | `{ success, analysis, structuredReport, summaryFindings, privacyScore, privacySummary, scoreBreakdown, analysisSummary, analysisError, consentDetails, scripts, scriptGroups, debugLog }` | Final analysis results |
| `error` | Server → Client | `{ error }` | Error message |

---

## Caching

Three per-domain caches live under `server/.cache/` (gitignored).
They reduce LLM calls and improve analysis speed on repeat visits
to the same domain.

### Script Analysis Cache (`script_cache.py`)

Caches the LLM-generated description for each unknown script.

- **Key:** Script URL + MD5 hex digest of its fetched content.
- **Hit:** URL and hash both match → cached description is used,
  no LLM call.
- **Miss:** URL is not in the cache → script is sent to the LLM.
- **Invalidation:** URL is found but the hash differs (content
  changed) → the stale entry is removed and the script is
  re-analysed.
- **Merge:** On save, newly analysed entries are merged with
  existing entries whose URLs were not re-analysed this run
  (carried forward).

```
Cold run:  72 LLM script calls,  24.6s script analysis
Warm run:   0 LLM script calls,   1.4s script analysis
Overall:  ~14% faster (111.8s → 95.9s)
```

### Domain Knowledge Cache (`domain_cache.py`)

Caches LLM-generated classifications so subsequent analyses of
the same domain produce consistent labels.

- **Stored:** Tracker categories, cookie groupings, vendor roles,
  data collection categories, severity levels.
- **Anchoring:** Cached knowledge is formatted as a context block
  and injected into the LLM prompt. The model is instructed to
  reuse established names and classifications.
- **Merge-on-save:** New findings are merged with the existing
  cache rather than overwriting it. Items present in the latest
  report update their `last_seen_scan` timestamp.
- **Staleness pruning:** Items not seen for 3 consecutive scans
  are automatically removed.
- **Fuzzy deduplication:** Near-duplicate names like "Comscore"
  and "Scorecard Research (Comscore)" are matched via normalised
  tokens and parenthetical cross-matching.

### Overlay Dismissal Cache (`overlay_cache.py`)

Caches successful consent-dismiss strategies per domain so
repeat visits skip the LLM vision detection step.

- **Stored:** Overlay type, button text, CSS selector, Playwright
  locator strategy (`role-button`, `text-exact`, `css`, etc.),
  frame type (`main` or `consent-iframe`).
- **Hit:** Cached overlay is found in the DOM → click it directly.
- **Miss:** Not found in DOM → skipped but kept in cache for other
  pages on the domain.
- **Invalidation:** Cached click fails → overlay type is added to
  `_failed_cache_types` and dropped on merge.
- **Reject → Accept override:** Cached reject-style entries are
  replaced when an accept alternative is found.

### Cache Management

All caches can be cleared before analysis:

- **Page URL:** Add `?clear-cache=true` to the browser URL
  (e.g. `http://localhost:5173/?clear-cache=true`). The client
  reads this query parameter on load and forwards it to the API.
- **API:** Pass `?clear-cache=true` in the API query string.
- **Code:** Call `src.utils.cache.clear_all()`.

The `clear_all()` function removes every JSON file in all three
sub-directories and logs the count of files removed per directory.

### Logging

Every cache operation is logged:

| Operation | Log Level | Where |
|-----------|-----------|-------|
| Load (read) | `info` | Each cache module's `load()` |
| Save (write) | `info` | Each cache module's `save()` or `save_from_report()` |
| Hit | `info` | `scripts.py` (aggregate), `overlay_pipeline.py` (per-overlay) |
| Miss | `info` / `debug` | `scripts.py` (aggregate), `script_cache.py` (per-URL debug) |
| Invalidation | `info` | `script_cache.py` (hash mismatch), `domain_cache.py` (stale prune), `overlay_pipeline.py` (click fail) |
| Clear | `info` / `success` | `utils/cache.py` |
| Merge | `info` | `overlay_cache.py` (carried/new/dropped counts), `script_cache.py` (new/carried/total) |
| Error | `warn` | Each cache module (read/write failures) |

---

## Adding New Features

### Adding a New Tab

1. Create `client/src/components/tabs/NewTab.vue`
2. Export from `client/src/components/tabs/index.ts`
3. Import in `App.vue`
4. Add tab button and content section
5. Add to `TabId` type in `client/src/types/tracking.ts`

### Adding a New Tracking Data Type

1. Add Pydantic model to the appropriate file in `server/src/models/`
2. Add capture method in `server/src/browser/session.py`
3. Include in screenshot event payload
4. Add client interface in `client/src/types/tracking.ts`
5. Add reactive state in `useTrackingAnalysis.ts`
6. Display in appropriate tab

### Adding a New AI Analysis

1. Create an agent class in `server/src/agents/` subclassing `BaseAgent`
2. Create a prompt module in `server/src/agents/prompts/` with the system prompt
3. Define `agent_name`, `instructions` (imported from the prompt module), `max_tokens`, and optionally `response_model`
3. Add an orchestration function in the relevant domain package (`server/src/analysis/`, `server/src/consent/`, etc.) that calls the agent
4. Call from `stream.py` in `server/src/pipeline/` (consider `asyncio.gather()` for parallel execution)
5. Include in `complete` event payload
6. Display in client

### Adding a New Overlay Type

1. Update `CookieConsentDetection` type in `server/src/models/consent.py`
2. Update detection instructions in `server/src/agents/prompts/consent_detection.py`
3. Add click strategy in `server/src/consent/click.py`
4. Update `get_overlay_message()` in `server/src/pipeline/overlay_steps.py`

---

## Development Tips

### Linting and Formatting

The server uses [ruff](https://docs.astral.sh/ruff/) for linting/formatting and
[mypy](https://mypy.readthedocs.io/) for static type checking, orchestrated by
[poethepoet](https://poethepoet.naber.dev/).

```bash
cd server

poe lint          # Run all linting (ruff check + format check + mypy)
poe lint:ruff     # Run ruff linter and format check only
poe lint:mypy     # Run mypy type checking only
poe format        # Auto-fix ruff lint issues and format code
poe test          # Run unit tests
poe test:cov      # Run unit tests with coverage summary
```

All tool configuration (ruff rules, mypy settings, poe tasks) lives in `server/pyproject.toml`.

### Virtual Display Setup

The browser runs in headed mode on a virtual display (Xvfb) to avoid bot detection by ad networks. This is automatically configured in:

**VS Code Devcontainer:**
- `containerEnv` in `devcontainer.json` sets `DISPLAY=:99`
- `postStartCommand` runs `.devcontainer/init.sh` which:
  - Installs npm dependencies if needed
  - Installs Python dependencies via `uv sync`
  - Installs real Chrome for Python with system dependencies (`--with-deps`)
  - Installs Chromium as fallback for Python
  - Installs Xvfb if not present
  - Cleans up stale lock files and starts Xvfb on display `:99` if not already running
- `.vscode/launch.json` also sets `DISPLAY=:99` for the debug server

**Docker:**
- `docker-entrypoint.sh` cleans up stale lock files and starts Xvfb before the server
- `Dockerfile` installs Xvfb and sets `ENV DISPLAY=:99`

**Manual Setup (if not using devcontainer):**
```bash
# Install Xvfb
sudo apt-get install -y xvfb

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -ac &

# Set DISPLAY before running the server
export DISPLAY=:99
cd server
uv run uvicorn src.main:app --reload --port 3001 --env-file ../.env
```

### Debugging SSE

Enable browser DevTools → Network tab → Filter by "EventStream" to see SSE messages.

### Server Logging

The server includes verbose logging with timestamps and timing information. Logs are colorized and grouped by module:

```
────────────────────────────────────────────────────────────────
  Analyzing: https://example.com
────────────────────────────────────────────────────────────────

[12:34:56.789] ℹ [Analyze] Request received url="https://example.com" device="ipad"
[12:34:56.790] ⏱ [Analyze] Starting: total-analysis

  ▸ Phase 1: Browser Setup

[12:34:56.791] ⏱ [Analyze] Starting: browser-launch
[12:34:57.234] ⏱ [Analyze] Browser launched took 443ms
```

**Log Levels:**
- `ℹ` Info - General information
- `✓` Success - Operation completed successfully
- `⚠` Warning - Non-critical issues
- `✗` Error - Errors and failures
- `•` Debug - Detailed debugging info
- `⏱` Timing - Operation duration measurements

**Using the Logger:**
```python
from src.utils import logger

log = logger.create_logger('MyModule')

log.info('Starting operation', {'param': value})
log.start_timer('my-operation')
# ... do work ...
log.end_timer('my-operation', 'Operation complete')
log.success('Done!', {'result': data})
```

**File Output:**

Set `WRITE_TO_FILE=true` in your environment to write logs and reports to files. Folders are created automatically if they don't exist.

- **Logs** are saved to the `/.logs` folder. Each analysis creates a new log file named after the domain being analyzed. File logs are plain text with ANSI color codes stripped for readability.
- **Reports** are saved to the `/.reports` folder. Each analysis creates a text file containing the final structured report.

```bash
# Enable file output
WRITE_TO_FILE=true npm run dev:server
```

Files are named `<domain>_YYYY-MM-DD_HH-MM-SS` with `.log` or `.txt` extensions (e.g., `example.com_2026-01-29_11-32-57.log`).

### Concurrency

- Each request creates its own `BrowserSession` instance
- Sessions are fully isolated — no shared state between requests
- Logger state (timers, log buffer, file handle) uses `contextvars.ContextVar` for async-safe per-session isolation
- Multiple users can analyze different URLs simultaneously
- Browser cleanup happens in `finally` block to prevent leaks

### Performance

- Script analysis uses pattern matching first, LLM only for unknowns
- Script patterns are pre-compiled to regex at load time (no re-compilation per match)
- Scripts are grouped (chunks, vendor bundles) to reduce noise and LLM calls
- Unknown scripts are analyzed individually with bounded concurrency (semaphore, max 10 at a time)
- Script analysis results are cached per domain by URL + MD5 content hash; warm runs skip LLM calls entirely for unchanged scripts
- Script content fetches share a single `aiohttp.ClientSession` for connection reuse
- Script analysis and tracking analysis run concurrently via `asyncio`
- Screenshots are captured once as PNG; JPEG conversion reuses the bytes (no second browser capture)
- Vision API calls (detection, extraction) convert PNG to JPEG and downscale to max 1280px wide
- Overlay detection uses viewport-only screenshots (not full page) for faster capture and smaller payloads
- Overlay cache stores successful dismiss strategies per domain (Playwright locator strategy, button text, frame type), skipping LLM vision detection on repeat visits
- Domain knowledge cache stores LLM-generated classifications (tracker categories, cookie groupings, vendor roles) per domain, anchoring subsequent analyses to established labels for consistency. New findings are **merged** with the existing cache rather than overwriting it; items not seen for 3 consecutive scans are automatically pruned
- Consent extraction runs concurrently with the next detection call via `asyncio.create_task`
- Cookie capture uses O(1) dict index for upserts instead of linear scan
- `blob:` URLs are filtered from script tracking (unfetchable browser-internal scripts)
- Network request tracking uses O(1) set/dict indexes for script dedup and response matching
- Privacy score is calculated deterministically (no LLM variance) via 8 decomposed category scorers
- Tracker classification patterns (~80+) are merged into combined alternation regexes for single-pass matching per URL/cookie
- Tracking arrays have limits (5000 requests, 1000 scripts) per session

### LLM Usage Tracking

Every LLM call is automatically tracked for call count and token usage via `usage_tracking.py`. The counters are session-scoped (using `contextvars`) so concurrent analyses don't interfere.

- **Per-call logging:** After each LLM call, `TimingChatMiddleware` extracts `usage_details` from the response and logs a running tally:
  ```
  [12:35:02.456] ℹ [LLM-Usage] LLM call #3 (ScriptAnalysis) callTokens=1842 callInput=1200 callOutput=642 runningCalls=3 runningTokens=6218
  ```
- **End-of-scan summary:** At the end of each analysis run, a final summary is logged:
  ```
  [12:36:14.789] ℹ [LLM-Usage] LLM usage summary totalCalls=7 totalInputTokens=18400 totalOutputTokens=9200 totalTokens=27600
  ```
- **Reset:** Counters are reset at the start of every `analyze_url_stream()` call.
- **Log only:** Usage data appears in the console, debug tab, and log files. It is not included in the analysis report.

### Rate Limit Handling

All LLM calls are wrapped by `RetryChatMiddleware` (in `server/src/agents/middleware.py`), which provides automatic retry with exponential backoff:

- **Retryable errors:** 429 (rate limit), 5xx (server errors), network failures
- **Backoff strategy:** Starts at 1s, doubles each retry, max 30s
- **Jitter:** ±20% randomization to prevent thundering herd
- **Max retries:** 5 (configurable per agent via `max_retries`)

The middleware is automatically applied to every agent via `BaseAgent`. No manual wrapping is required — simply subclass `BaseAgent` and call `run()`.

When rate limits are hit, you'll see logs like:
```
[12:34:56.789] ⚠ [Agent-Middleware] Retrying after transient error agent="TrackingAnalysisAgent" attempt=1/5 delay_ms=1200 is_rate_limit=True
```

### Observability

The Agent Framework supports OpenTelemetry-based observability. When configured, traces, logs, and metrics from all agent calls are exported to Azure Application Insights.

**Setup:** Observability is configured automatically at startup in `server/src/agents/observability_setup.py`. The module reads the `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variable and creates Azure Monitor exporters (traces, logs, metrics) that are passed to the Agent Framework's `configure_otel_providers()` function.

If the connection string is not set, telemetry is silently disabled and the application runs without any observability overhead.

**Environment variable:**
```env
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...;IngestionEndpoint=...
```

**What is captured:**
- **Traces** — Spans for each agent invocation including model, token usage, and duration
- **Logs** — Agent Framework internal logging (chat completions, middleware events)
- **Metrics** — GenAI semantic convention metrics (`gen_ai.*` and `agent_framework.*` prefixes)

All telemetry flows through the standard OpenTelemetry SDK pipeline, so custom exporters or additional providers can be added alongside Azure Monitor if needed.
