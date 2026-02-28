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
11. [Browser Resilience](#browser-resilience)

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
   ├── await launch_browser(session, device_type) → Start real Chrome (Chromium fallback)
   │   ├── Anti-bot hardening: webdriver removal, plugins, WebGL, AudioContext, MediaDevices
   │   ├── Playwright startup timeout (15s) prevents indefinite hangs
   │   └── Retry: up to 2 attempts with cleanup between retries (see Browser Resilience)
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
   ├── take_screenshot() → JPEG screenshot (quality 72, for AI vision)
   │   └── optimize_screenshot_bytes() → Downscale JPEG for LLM vision
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
   │       └── On failure → mark as failed, fall through to CMP / vision
   │
   ├── 2. CMP platform detection (_try_cmp_specific_dismiss)
   │   ├── Only runs when cache missed (no overlays dismissed)
   │   ├── Detect CMP from domain (media group lookup → consent_platform field)
   │   ├── Probe DOM via platform container selectors (fast, ~50-100ms)
   │   ├── If known CMP found → try deterministic accept button click
   │   ├── Authoritative platform identity: if the domain lookup identifies
   │   │   one CMP (e.g. Sourcepoint) but the DOM contains a different
   │   │   CMP’s selectors (e.g. InMobi Choice embedded via
   │   │   Sourcepoint), the media-group identity is preserved for
   │   │   reporting while the DOM CMP’s selectors are used for button
   │   │   click
   │   └── Skips LLM vision entirely if successful
   │
   ├── 3. Vision detection loop (up to 5 iterations)
   │   │
   ├── steps.detect_overlay(screenshot)
   │   │   └── AI vision-only analysis (viewport screenshot, JPEG, max 1280px)
   │   │       Returns: { found, overlay_type, button_text, certainty }
   │   │   └── Screenshot failures return not-found (analysis continues)
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
   │   │   └── Screenshot failures produce an empty image (analysis continues)
   │   │
   │   ├── If first cookie-consent overlay:
   │   │   ├── steps.capture_consent_content() → Read-only pre-dismiss capture
   │   │   │   └── Extracts text from consent iframes and main-frame containers
   │   │   │   └── Uses constants.is_consent_frame() and CONSENT_CONTAINER_SELECTORS
   │   │   │   └── Evaluates get_consent_bounds.js → consent dialog bounding box
   │   │   │   └── Returns (text, screenshot, consent_bounds)
   │   │   └── Start extraction as asyncio.create_task (concurrent)
   │   │       └── Screenshot cropped to consent_bounds before LLM call
   │   │       └── Local regex parser (text_parser) runs alongside LLM
   │   │       └── Results merged (LLM authoritative; local supplements)
   │   │       └── If vision times out, text-only LLM fallback (10 s) before falling to local parse
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
   │   │  analyze_scripts(scripts)                             │
   │   │   ├── Group similar scripts (chunks, vendor bundles)  │
   │   │   ├── Match against tracking patterns (JSON)          │
   │   │   ├── Match against benign patterns (JSON)            │
   │   │   ├── Deduplicate by base URL (strip query strings)   │
   │   │   ├── Check per-script-domain cache (URL + MD5 hash)  │
   │   │   ├── LLM analysis for uncached unknown scripts       │
   │   │   │   (concurrent with semaphore, max 10 at a time)   │
   │   │   │   Uses per-agent deployment override when set     │
   │   │   │   (AZURE_OPENAI_SCRIPT_DEPLOYMENT)                │
   │   │   └── Incremental cache save after each LLM result    │
   │   │                                                       │
   │   │  run_tracking_analysis(summary, consent, stats)       │
   │   │   ├── build_tracking_summary() → Data for LLM         │
   │   │   ├── GDPR/TCF reference data (purposes, lawful       │
   │   │   │   bases, ePrivacy categories, consent cookies)    │
   │   │   ├── Pre-consent page-load stats                     │
   │   │   ├── Media group context (if domain recognised)      │
   │   │   └── Main analysis prompt → Structured JSON result   │
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
   │   │   ├── 10 concurrent section LLM calls                 │
   │   │   ├── GDPR/TCF reference data                         │
   │   │   ├── Deterministic overrides (partner count,         │
   │   │   │   domain count, cookie count, storage counts)     │
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
         message,           // Completion message
         structuredReport,  // Per-section structured report
         summaryFindings,   // Structured findings array
         privacyScore,      // 0-100
         privacySummary,    // One sentence
         analysisError,     // Error message if analysis failed
         consentDetails,    // Consent dialog info
         cookies,           // Final cookie snapshot
         networkRequests,   // Network requests
         localStorage,      // localStorage items
         sessionStorage,    // sessionStorage items
         scripts,           // Scripts with descriptions
         scriptGroups,      // Grouped similar scripts
         debugLog           // Server debug log lines
       })
   │
   └── await session.close() → Cleanup Playwright (in finally block)
       ├── Per-step timeouts (5s each): context.close → browser.close → playwright.stop
       ├── Force-kills browser process (SIGKILL) if graceful close fails
       └── Outer 30s timeout in stream.py prevents indefinite cleanup hangs
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
screenshots          // base64 images (initial + one per overlay dismissed)
cookies              // TrackedCookie[]
scripts              // TrackedScript[]
scriptGroups         // ScriptGroup[] (grouped similar scripts)
networkRequests      // NetworkRequest[]
localStorage         // StorageItem[]
sessionStorage       // StorageItem[]

// Analysis results
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

// 15-second connection timeout safety net — if no events arrive,
// the connection is aborted and an error dialog is shown.

eventSource.addEventListener('progress', (e) => {
  // Update loading indicators — monotonic: status message and
  // progress bar only advance forward.  Concurrent pipeline stages
  // may emit events out of order; lower-percentage events are
  // silently ignored to prevent the status text from jumping
  // backward (e.g. a script analysis event at 84% arriving after
  // a report event at 91%).
})

eventSource.addEventListener('screenshot', (e) => {
  // Add screenshot, update data arrays
})

eventSource.addEventListener('screenshotUpdate', (e) => {
  // Replace most recent screenshot (background refresh)
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
  // Show error dialog with categorized title:
  //   "Analysis Timed Out"  — timeout errors (server reports actual elapsed time)
  //   "Browser Error"       — Playwright / display failures
  //   "Configuration Error" — missing API keys or setup issues
  //   "Analysis Error"      — all other server errors
})

// onerror handler provides contextual messages based on the
// current progress step (browser launch, page load, AI analysis, etc.).
// Server-sent error events take priority — onerror will not overwrite them.
```

### Component Hierarchy

```
App.vue
├── ProgressBanner (loading state)
├── ScoreDialog (privacy score popup)
├── PageErrorDialog (access denied)
├── ErrorDialog (generic errors)
├── ScreenshotGallery (thumbnail row + modal)
├── TrackerCategorySection (reusable tracker category block)
└── Tab Content (v-if="isComplete")
    ├── AnalysisTab (uses TrackerCategorySection ×5)
    ├── ConsentTab (visible when consent dialog detected)
    ├── CookiesTab
    ├── StorageTab
    ├── NetworkTab
    ├── TrackerGraphTab (D3.js force-directed network graph)
    ├── ScriptsTab
    └── DebugLogTab (debug mode only, enabled via ?debug=true in the URL)
```

---

## Server Architecture

### Agent Layer

AI interactions use the **Microsoft Agent Framework** (`agent-framework-core` package). Each agent subclasses `BaseAgent` and defines its own response model and token limits. System prompts are stored in the `agents/prompts/` directory — one module per agent — keeping prompt text separate from agent logic.

Key framework types used:
- `agent_framework.Agent` — orchestrates a chat conversation with middleware
- `agent_framework.SupportsChatGetResponse` — abstraction over LLM backends (Azure OpenAI, OpenAI)
- `agent_framework.ChatMiddleware` — pluggable request/response pipeline
- `agent_framework.Message` / `agent_framework.Content` — message types (text + multimodal)
- `agent_framework.ChatOptions` — token limits and structured output (`response_format`)
- `agent_framework.AgentResponse` — typed response wrapper (structured output is parsed via `model.model_validate_json(response.text)` in `BaseAgent._parse_response()`)
- `agent_framework.AgentSession` — lightweight session container (replaces threads)

| Agent | Module | Responsibility |
|-------|--------|---------------|
| `ConsentDetectionAgent` | `consent_detection_agent.py` | Vision-only detection of blocking overlays and locate dismiss buttons. Uses a 30 s per-call timeout and 2 retries. Returns `error=True` on timeout (distinct from "not found") |
| `ConsentExtractionAgent` | `consent_extraction_agent.py` | Three-tier consent extraction: a local regex parser (`text_parser`) always runs alongside the LLM vision call. Screenshots are cropped to the dialog bounding box when bounds are available. LLM is authoritative; local parse supplements `has_manage_options` and `claimed_partner_count`. If the LLM vision call times out, a text-only LLM fallback (10 s timeout) is attempted before falling to the local parse as sole source |
| `ScriptAnalysisAgent` | `script_analysis_agent.py` | Identify and describe unknown scripts via LLM. Supports a per-agent deployment override (`AZURE_OPENAI_SCRIPT_DEPLOYMENT`) for using a code-optimised model |
| `SummaryFindingsAgent` | `summary_findings_agent.py` | Generate structured summary findings with deterministic metric anchoring |
| `StructuredReportAgent` | `structured_report_agent.py` | Generate structured privacy report with 10 concurrent section LLM calls (2 waves), deterministic overrides, and vendor URL enrichment. Uses a 60 s per-call timeout (large prompts on complex sites) |
| `TrackingAnalysisAgent` | `tracking_analysis_agent.py` | Full privacy analysis report (streaming markdown) with GDPR/TCF context. Uses `run(stream=True)` with a 60 s streaming inactivity timeout — raises `TimeoutError` if no token arrives within 60 s (covers both time-to-first-token and mid-stream stalls) |
| `CookieInfoAgent` | `cookie_info_agent.py` | Explain individual cookies (purpose, who sets it, risk level, privacy note). LLM fallback for cookies not in known databases |
| `StorageInfoAgent` | `storage_info_agent.py` | Explain individual storage keys (purpose, who sets it, risk level, privacy note). LLM fallback for keys not in known databases |

| Infrastructure | Module | Responsibility |
|----------------|--------|---------------|
| `BaseAgent` | `base.py` | Shared agent factory with middleware, structured output, Azure schema fixes, configurable `call_timeout` (default 30 s) passed to `RetryChatMiddleware`, and per-agent deployment override support via `config.get_agent_deployment()` |
| `Config` | `config.py` | LLM configuration via `pydantic-settings` `BaseSettings` (Azure / OpenAI) with per-agent deployment overrides (`get_agent_deployment()`, `_AGENT_DEPLOYMENT_OVERRIDES`) |
| `LLM Client` | `llm_client.py` | Chat client factory (`SupportsChatGetResponse`) with `deployment_override` support for per-agent model selection |
| `Middleware` | `middleware.py` | `TimingChatMiddleware` (duration + token usage tracking) + `RetryChatMiddleware` with exponential backoff, per-call timeout via `asyncio.wait_for()`, and a global concurrency semaphore (max 10 in-flight LLM calls) to prevent overwhelming the endpoint |
| `Observability` | `observability_setup.py` | Azure Monitor / Application Insights telemetry configuration |
| `GDPR Context` | `gdpr_context.py` | Shared GDPR/TCF reference builder — assembles TCF purposes, consent cookies, lawful bases, and ePrivacy categories into a compact reference block for agent prompts |
| `Prompts` | `prompts/` | System prompts for each agent, one module per agent |

### Domain Packages

Domain packages orchestrate browser automation and data processing. They call agents for AI tasks.

**`browser/`** — Browser automation

| Module | Responsibility |
|--------|---------------|
| `session.py` | Playwright async browser session (per-request isolation, real Chrome with anti-bot hardening, per-step cleanup timeouts, OS-level force-kill fallback, async context manager). Captures `initiator_domain` from the requesting frame and `redirected_from_url` from redirect chains. `take_screenshot()` accepts a configurable `timeout` (default 15s) and `optimize_screenshot_bytes()` gracefully handles empty input |
| `device_configs.py` | Device emulation profiles (iPhone, iPad, Android, etc.) |
| `access_detection.py` | Bot blocking and access denial detection patterns |

**`consent/`** — Consent handling

| Module | Responsibility |
|--------|---------------|
| `detection.py` | Overlay detection orchestration |
| `extraction.py` | Consent detail extraction orchestration |
| `click.py` | Click strategies for consent buttons (per-strategy deadline checking to prevent timeout cascades) |
| `constants.py` | Shared consent-manager host keywords, exclusion lists, container selectors, reject-button regex, and `is_consent_frame()` utility |
| `overlay_cache.py` | Domain-level cache for overlay dismissal strategies — stores Playwright locator strategy, button text, frame type, and consent platform per overlay (JSON) |
| `partner_classification.py` | Classify consent partners by risk level and enrich partner URLs from partner databases |
| `platform_detection.py` | CMP detection via cookies, media group profiles, and page DOM; provides deterministic accept/reject button selectors for 19 known consent platforms |
| `text_parser.py` | Local regex-based consent text parser — extracts cookie categories (7 patterns), IAB TCF purposes (15 patterns including special purposes and features), manage-options indicators, partner names, claimed partner counts, and consent platform (10 known CMPs) from DOM text without any LLM call |

**`analysis/`** — Tracking analysis and scoring

| Module | Responsibility |
|--------|---------------|
| `tracking.py` | Main tracking analysis orchestration (streaming LLM) |
| `scripts.py` | Script identification — `analyze_scripts()` delegates to `_match_known_patterns()` (regex) and `_analyze_unknowns()` (cache + LLM) |
| `script_cache.py` | Script analysis cache — caches LLM-generated descriptions per **script domain** (e.g. `s0.2mdn.net.json`) by base URL (query strings stripped) + MD5 content hash. Enables cross-site cache hits. Invalidates on hash mismatch |
| `script_grouping.py` | Group similar scripts (chunks, vendor bundles) to reduce noise |
| `tracker_patterns.py` | Regex pattern data for tracker classification (with pre-compiled combined alternation) |
| `tracking_summary.py` | Summary builder for LLM input and pre-consent stats |
| `domain_cache.py` | Domain-level knowledge cache — persists LLM classifications (tracker categories, cookie groupings, vendor roles, severity levels) for consistency across repeat analyses of the same domain. Uses merge-on-save with scan-count-based staleness pruning |
| `cookie_lookup.py` | Cookie information lookup service — checks consent cookie database and tracking cookie patterns first, falls back to `CookieInfoAgent` LLM for unrecognised cookies. Main function: `get_cookie_info()` |
| `storage_lookup.py` | Storage key information lookup service — checks tracking storage patterns first, falls back to `StorageInfoAgent` LLM for unrecognised keys. Main function: `get_storage_info()` |
| `tcf_lookup.py` | TCF purpose matching service — maps consent purpose strings to the IAB TCF v2.2 taxonomy. Fuzzy-matches purposes, special purposes, features, and special features. Deterministic — no LLM calls. Main function: `lookup_purposes()` |
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
| `stream.py` | Top-level SSE endpoint orchestrator — `analyze_url_stream()` delegates to `_run_phases_1_to_3()`, `_run_phase_4_overlays()`, and `_run_phase_5_analysis()` async generators that share a `_StreamContext` dataclass |
| `browser_phases.py` | Phases 1-3: setup (with browser launch retry), navigate, initial capture |
| `overlay_pipeline.py` | Phase 4: `run()` orchestrator delegates to `_try_cmp_specific_dismiss()` (deterministic CMP-based dismiss), `_run_vision_loop()` (detection iterations), and `_click_and_capture()` (click + post-click capture) |
| `overlay_steps.py` | Sub-step functions for overlay pipeline (detect, validate, click, capture content, extract). `detect_overlay()` speculatively crops the viewport screenshot to the consent dialog bounding box (via `get_consent_bounds.js`) before sending to the LLM, preventing content-filter rejections from background imagery. `capture_consent_content()` returns a 3-tuple `(text, screenshot, consent_bounds)` where `ConsentBounds = tuple[int, int, int, int] | None` is obtained by evaluating `get_consent_bounds.js` in the browser. Screenshot calls are wrapped with try/except to prevent a single timeout from crashing the analysis |
| `analysis_pipeline.py` | Phase 5: concurrent AI analysis and scoring |
| `sse_helpers.py` | SSE formatting, serialization helpers, and screenshot capture with error recovery |

### Data Layer

| Module | Content |
|--------|--------|
| `data/loader.py` | JSON data loader with caching (`functools.cache`) |
| `data/trackers/tracking-scripts.json` | 493 regex patterns for known trackers |
| `data/trackers/benign-scripts.json` | 51 patterns for safe libraries |
| `data/trackers/tracking-cookies.json` | Known tracking cookie definitions (137 cookies) with regex patterns, descriptions, purposes, risk levels, and privacy notes |
| `data/trackers/tracking-storage.json` | Known tracking storage key definitions (185 keys) with regex patterns, descriptions, purposes, risk levels, and privacy notes |
| `data/trackers/tracker-domains.json` | Known tracker domain database (4,644 domains) from Privacy Badger |
| `data/trackers/cname-domains.json` | CNAME cloaking tracker domains (122,014 domains) from Privacy Badger and AdGuard |
| `data/trackers/disconnect-services.json` | Disconnect Tracking Protection list (4,370 domains) |
| `data/partners/*.json` | 574 partner entries across 8 risk categories |
| `data/consent/gdpr-reference.json` | GDPR lawful bases, principles, and ePrivacy cookie categories for LLM context |
| `data/consent/tcf-purposes.json` | IAB TCF v2.2 purpose definitions and special features for LLM context |
| `data/consent/consent-cookies.json` | Known consent-state cookie names (TCF and CMP) for LLM context |
| `data/consent/consent-platforms.json` | 19 CMP profiles with DOM selectors, iframe patterns, cookie indicators, and button strategies |
| `data/publishers/media-groups.json` | 16 UK media group profiles (vendors, ad tech partners, data practices) |

**`utils/`** — Cross-cutting utilities

| Module | Responsibility |
|--------|---------------|
| `cache.py` | Cross-cache management — `clear_all()` and `atomic_write_text()` for crash-safe file writes |
| `errors.py` | Error message extraction and client-safe error sanitisation (`get_safe_client_message()`) |
| `usage_tracking.py` | Per-session LLM call count and token usage tracking (`contextvars` isolation) |
| `image.py` | Screenshot optimisation, JPEG conversion, and consent dialog cropping (`crop_jpeg()`, `optimize_for_llm()` with `crop_box` parameter) |
| `json_parsing.py` | LLM response JSON parsing |
| `logger.py` | Structured logger with colour output (`contextvars` isolation) |
| `risk.py` | Shared risk-scoring helpers (`risk_label`) |
| `serialization.py` | Pydantic model serialization helpers |
| `url.py` | URL and domain utilities, SSRF prevention (`validate_analysis_url()`) |

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
BaseAgent._build_agent() → Creates Agent (agent_framework.Agent)
    │                         with SupportsChatGetResponse client + middleware
    │
    ├── TimingChatMiddleware → Logs duration + records token usage
    ├── RetryChatMiddleware → Handles 429/5xx with backoff + per-call timeout
    │                         + global concurrency limit (max 10 in-flight)
    └── Agent.run() or run(stream=True) → LLM chat completion
    │
    ▼
Parse response (model.model_validate_json via BaseAgent._parse_response)
    │
    └── send_event('complete', results)
    │
    ▼
Client displays analysis
```

---

## Key Data Types

### StorageItem
```python
class StorageItem(BaseModel):
    key: str
    value: str
    timestamp: str
```

### CapturedStorage
```python
class CapturedStorage(BaseModel):
    """localStorage and sessionStorage captured from the browser."""
    local_storage: list[StorageItem] = []
    session_storage: list[StorageItem] = []
```

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
    initiator_domain: str | None = None
    redirected_from_url: str | None = None
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
    privacy_url: str = ""              # Partner's privacy policy URL
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
    consent_platform: str | None = None  # Detected CMP platform name
```

### NamedEntity (Report Model)
```python
class NamedEntity(BaseModel):
    """A company or service name with an optional URL.

    Used in shared_with lists and third-party service lists
    so the client can render names as clickable links.
    """
    name: str
    url: str = ""
```

### TrackerEntry (Report Model)
```python
class TrackerEntry(BaseModel):
    """A single identified tracking technology in the structured report."""
    name: str
    domains: list[str]
    cookies: list[str] = []
    storage_keys: list[str] = []
    purpose: str
    url: str = ""              # Enriched from partner databases
```

### DataCollectionItem (Report Model)
```python
class DataCollectionItem(BaseModel):
    """A type of data being collected."""
    category: str
    details: list[str]
    risk: Literal["low", "medium", "high", "critical"]
    sensitive: bool = False
    shared_with: list[NamedEntity] = []  # Companies with optional URLs for clickable links
```

### ThirdPartyGroup (Report Model)
```python
class ThirdPartyGroup(BaseModel):
    """A categorised group of third-party services."""
    category: str
    services: list[NamedEntity] = []     # Services with optional URLs for clickable links
    privacy_impact: str
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
| `complete` | Server → Client | `{ message, structuredReport, summaryFindings, privacyScore, privacySummary, analysisError, consentDetails, cookies, networkRequests, localStorage, sessionStorage, scripts, scriptGroups, debugLog }` | Final analysis results |
| `error` | Server → Client | `{ error }` | Error message |

---

## Caching

Three caches live under `server/.output/cache/` (gitignored).
They reduce LLM calls and improve analysis speed on repeat
visits — and, for scripts, across different sites.

### Script Analysis Cache (`script_cache.py`)

Caches the LLM-generated description for each unknown script.

- **Keyed by script domain:** Each cache file is named after the
  script’s own domain (e.g. `s0.2mdn.net.json`,
  `cdn.flashtalking.com.json`), not the website being scanned.
  This means a Google Ads script analysed during a scan of
  site-A.com is an immediate cache hit when site-B.com loads the
  same script.
- **URL normalisation:** Query strings and fragments are stripped
  before comparison. The same `.js` file served with different
  ad-targeting parameters, cache-busters, or impression IDs is
  treated as a single cache entry.
- **Content hash:** Each entry stores the MD5 hex digest of the
  fetched script content.
- **Hit:** Base URL and hash both match → cached description is
  used, no LLM call.
- **Miss:** Base URL is not in the cache → script is sent to the
  LLM.
- **Invalidation:** Base URL is found but the hash differs
  (content changed) → the stale entry is removed and the script
  is re-analysed.
- **Merge:** On save, newly analysed entries are merged with
  existing entries whose URLs were not re-analysed this run
  (carried forward).
- **Deduplication:** Within a single scan, scripts sharing the
  same base URL (different query strings) are fetched and
  analysed only once. The result is applied to all variants.

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
  frame type (`main` or `consent-iframe`), consent platform key
  (e.g. `sourcepoint`, `onetrust`).
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
  (e.g. `http://localhost:5173/?clear-cache=true`). On page load the
  client immediately calls `POST /api/clear-cache` to wipe all cached
  data, then forwards the flag to the SSE analysis stream as a query
  parameter.
- **POST endpoint:** Call `POST /api/clear-cache` directly (returns
  `{"success": true, "filesRemoved": N}`).
- **API query param:** Pass `?clear-cache=true` in the SSE stream URL.
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

## Browser Resilience

The browser lifecycle includes several safeguards to handle crashes, hangs, and resource leaks.

### Browser Launch Retry

`browser_phases.launch_browser()` retries browser startup on failure:

- **Max attempts:** 2
- **Delay between retries:** 2 seconds
- **Cleanup between attempts:** `session.close()` is called (with a 10-second timeout) to tear down any partially-initialized Playwright state before the next attempt
- **Cleanup failures are non-fatal:** If cleanup between attempts fails, the retry still proceeds
- **Final failure:** If all attempts fail, the last exception is raised to the caller

```
launch_browser()
   │
   ├── Attempt 1: session.launch_browser(device_type)
   │   └── Success → return
   │
   ├── On failure:
   │   ├── Log warning
   │   ├── session.close() (10s timeout, errors swallowed)
   │   └── Sleep 2s
   │
   └── Attempt 2: session.launch_browser(device_type)
       └── Success → return
       └── Failure → raise
```

### Playwright Startup Timeout

`session.launch_browser()` wraps the `async_playwright().start()` call in a 15-second timeout. This prevents indefinite hangs when Playwright or Xvfb is unresponsive. The browser PID is captured after launch for force-kill fallback.

### Session Cleanup

`session.close()` performs a layered teardown with per-step timeouts:

1. **Remove event listeners** — prevents callbacks from firing during teardown
2. **Close browser context** — 5-second timeout
3. **Close browser** — 5-second timeout
4. **Stop Playwright** — 5-second timeout

If any step times out, the remaining steps still execute. After all steps complete, `_force_kill_browser_process()` sends `SIGKILL` to the browser PID if it was captured during launch. Tracking data arrays are cleared at the end regardless of errors.

### Stream-Level Timeout

The top-level orchestrator in `stream.py` wraps `session.close()` in a 30-second outer timeout within the `finally` block. This prevents the entire SSE connection from hanging if cleanup itself gets stuck. Log file finalization (`logger.end_log_file()`) runs after cleanup so that teardown activity is captured in the log.

### Screenshot Resilience

Ad-heavy pages can become temporarily unresponsive after a consent overlay is dismissed (dozens of tracking scripts load at once). To prevent a single screenshot timeout from crashing the entire analysis:

- **Configurable timeout** — `session.take_screenshot()` accepts a `timeout` parameter (default 15 000 ms, reduced from Playwright's default 30 000 ms) so the pipeline fails fast.
- **Graceful fallback in overlay detection** — `detect_overlay()` catches screenshot exceptions and returns a `CookieConsentDetection.not_found()` result. When detection times out, it returns `CookieConsentDetection.failed()` with `error=True`, distinguishing a timeout from a clean "not found". The overlay loop exits cleanly instead of raising.
- **Graceful fallback in consent capture** — `capture_consent_content()` catches screenshot exceptions and falls back to `b""`. Consent extraction can still proceed using extracted DOM text alone.
- **Graceful fallback in SSE screenshot events** — `take_screenshot_event()` catches screenshot exceptions and falls back to `b""`. Post-click captures produce an empty image rather than crashing.
- **Empty-bytes guard** — `optimize_screenshot_bytes()` returns an empty string for empty bytes input, preventing a downstream Pillow crash when any of the above fallbacks flow through the optimization pipeline.
- **Background refresher** — The screenshot refresher in `stream.py` already catches all exceptions and skips the update (this was implemented before the above changes).

### Client Error Reporting

The client (`useTrackingAnalysis.ts`) provides context-aware error messages:

- **Server-sent errors take priority** — a `hasServerError` flag prevents the SSE `onerror` handler from overwriting specific error messages sent by the server
- **Categorized error titles:**
  - "Analysis Timed Out" for timeout errors
  - "Browser Error" for Playwright or display failures
  - "Configuration Error" for missing API keys or setup issues
- **Contextual connection-loss messages** — when the SSE connection drops, the error message reflects the current progress step (e.g., "lost while launching the browser", "lost while loading the page", "lost during AI analysis")
- **Completed analyses are not interrupted** — connection drops after the `complete` event are silently ignored

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

- **Logs** are saved to the `server/.output/logs/` folder. Each analysis creates a new log file named after the domain being analyzed. File logs are plain text with ANSI color codes stripped for readability.
- **Reports** are saved to the `server/.output/reports/` folder. Each analysis creates a text file containing the final structured report.

```bash
# Enable file output
cd server
WRITE_TO_FILE=true uv run uvicorn src.main:app --reload --port 3001 --env-file ../.env
```

Files are named `<domain>_YYYY-MM-DD_HH-MM-SS` with `.log` or `.txt` extensions (e.g., `example.com_2026-01-29_11-32-57.log`).

### Concurrency

- Each request creates its own `BrowserSession` instance
- Sessions are fully isolated — no shared state between requests
- Logger state (timers, log buffer, file handle) uses `contextvars.ContextVar` for async-safe per-session isolation
- Multiple users can analyze different URLs simultaneously
- Browser cleanup happens in `finally` block to prevent leaks:
  - Each cleanup step (`context.close`, `browser.close`, `playwright.stop`) has a 5-second timeout
  - If the browser process does not exit gracefully, it is force-killed via `SIGKILL`
  - The outer `finally` block in `stream.py` wraps `session.close()` in a 30-second timeout

### Performance

- Script analysis uses pattern matching first, LLM only for unknowns
- Script patterns are pre-compiled to regex at load time (no re-compilation per match)
- Scripts are grouped (chunks, vendor bundles) to reduce noise and LLM calls
- Unknown scripts are analyzed individually with bounded concurrency (semaphore, max 10 at a time)
- Script analysis results are cached per **script domain** (not per site) by base URL (query strings stripped) + MD5 content hash; a script analysed on one site is an immediate cache hit on any other site that loads it. Within a single scan, scripts sharing the same base URL are deduplicated (fetched and analysed once)
- Script content fetches share a single `aiohttp.ClientSession` for connection reuse
- Script analysis and tracking analysis run concurrently via `asyncio`
- Screenshots are captured once as JPEG (quality 72) by Playwright — no format conversion needed
- Vision API calls (detection, extraction) downscale JPEG to max 1280px wide
- Overlay detection uses viewport-only screenshots (not full page) for faster capture and smaller payloads
- Overlay cache stores successful dismiss strategies per domain (Playwright locator strategy, button text, frame type, consent platform), skipping LLM vision detection on repeat visits
- CMP platform detection identifies 19 known consent platforms by cookies, media group profile, or DOM selectors; when matched, the pipeline attempts a deterministic button click before falling back to LLM vision
- Domain knowledge cache stores LLM-generated classifications (tracker categories, cookie groupings, vendor roles) per domain, anchoring subsequent analyses to established labels for consistency. New findings are **merged** with the existing cache rather than overwriting it; items not seen for 3 consecutive scans are automatically pruned
- Consent extraction runs concurrently with the next detection call via `asyncio.create_task`
- Cookie capture uses O(1) dict index for upserts instead of linear scan
- `blob:` URLs are filtered from script tracking (unfetchable browser-internal scripts)
- Network request tracking uses O(1) set/dict indexes for script dedup and response matching
- Privacy score is calculated deterministically (no LLM variance) via 8 decomposed category scorers
- Tracker classification patterns (493 tracking + 51 benign) are merged into combined alternation regexes for single-pass matching per URL/cookie
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
