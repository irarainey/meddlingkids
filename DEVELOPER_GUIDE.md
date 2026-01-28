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
9. [Adding New Features](#adding-new-features)

---

## Overview

Meddling Kids is a full-stack application that analyzes website tracking behavior. It consists of:

- **Client**: Vue 3 SPA that initiates analysis and displays results
- **Server**: Express.js API that orchestrates browser automation and AI analysis
- **Playwright**: Browser automation for page loading and data capture
- **Xvfb**: Virtual display that allows headed browser mode without a visible window
- **OpenAI**: AI models for consent detection and privacy analysis

> **Why Headed Mode?** Ad networks often detect and block headless browsers, refusing to serve ads. By running in headed mode on a virtual display (Xvfb), the browser appears identical to a real user's browser, allowing ads to load correctly while remaining invisible.

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
                                     │ GET /api/open-browser-stream?url=...&device=...
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                                  SERVER                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  analyze-stream.ts (Route Handler)                                   │  │
│  │  - Orchestrates the 6-phase analysis workflow                        │  │
│  │  - Sends SSE events back to client                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                       │
│          ┌─────────────────────────┼─────────────────────────┐             │
│          ▼                         ▼                         ▼             │
│  ┌───────────────────┐  ┌─────────────────────┐     ┌─────────────────┐    │
│  │ browser-session.ts│  │ consent-*.ts        │     │ analysis.ts     │    │
│  │ - Playwright      │  │ - Detection (AI)    │     │ - OpenAI        │    │
│  │ - Navigation      │  │ - Extraction (AI)   │     │ - Risk analysis │    │
│  │ - Capture         │  │ - Click strategies  │     │ - Privacy score │    │
│  │ - Per-request     │  └─────────────────────┘     └─────────────────┘    │
│  └───────────────────┘                                                     │
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

The analysis follows a 6-phase workflow, orchestrated by `analyze-stream.ts`:

### Phase 1: Browser Setup and Navigation
```
Client: User clicks "Unmask" button
   │
   ▼
analyzeUrl() in useTrackingAnalysis.ts
   │ Creates EventSource connection
   ▼
analyzeUrlStreamHandler() in analyze-stream.ts
   │
   ├── validateOpenAIConfig() → Check env vars
   ├── new BrowserSession() → Create isolated session
   ├── session.clearTrackingData() → Reset tracking arrays
   ├── session.launchBrowser(deviceType) → Start Playwright browser
   └── session.navigateTo(url) → Load target page
```

### Phase 2: Wait for Page Load and Check Access
```
navigateTo() returns
   │
   ├── Check HTTP status code
   │   └── If error → sendEvent('pageError', {...})
   │
   ├── waitForNetworkIdle(20000)
   │   └── Wait for ad/tracking scripts to load
   │   └── Extra 3s wait if network still active (for ad auctions)
   │
   ├── waitForTimeout(2000)
   │   └── Additional wait for lazy-loaded ads and deferred scripts
   │
   └── checkForAccessDenied()
       └── If blocked → sendEvent('pageError', {...}) + screenshot
```

### Phase 3: Initial Data Capture
```
Page loaded successfully
   │
   ├── captureCurrentCookies() → Intercept all cookies
   ├── captureStorage() → Read localStorage/sessionStorage
   ├── takeScreenshot() → PNG screenshot
   │
   └── sendEvent('screenshot', {
         screenshot,      // base64 PNG
         cookies,         // TrackedCookie[]
         scripts,         // TrackedScript[]
         networkRequests, // NetworkRequest[]
         localStorage,    // StorageItem[]
         sessionStorage   // StorageItem[]
       })
```

### Phase 4: Overlay Detection and Handling
```
handleOverlays() loop (up to 5 iterations)
   │
   ├── getPageContent() → Get current HTML
   ├── detectCookieConsent(screenshot, html)
   │   └── AI vision analyzes screenshot + HTML
   │       Returns: { hasConsent, overlayType, buttonLocation }
   │
   ├── If cookie consent found (first time):
   │   └── extractConsentDetails(screenshot, html)
   │       └── AI extracts partners, categories, purposes
   │       └── sendEvent('consentDetails', {...})
   │
   ├── tryClickConsentButton(detection)
   │   └── Multiple click strategies (coordinates, selectors)
   │
   ├── Wait for page changes
   │   └── captureCurrentCookies() → New cookies after consent
   │
   └── sendEvent('screenshot', {...}) → Post-consent screenshot
```

### Phase 5: AI Analysis
```
All data captured
   │
   ├── analyzeScripts(scripts, maxLLM=20)
   │   │
   │   ├── Match against TRACKING_SCRIPTS patterns (300+)
   │   ├── Match against BENIGN_SCRIPTS patterns (~55)
   │   └── LLM analysis for unknown scripts
   │
   └── runTrackingAnalysis(cookies, storage, network, scripts, url, consent)
       │
       ├── buildTrackingSummary() → Aggregate data for LLM
       │
       ├── Main analysis prompt → Full markdown report
       │
       └── Parallel:
           ├── Summary findings prompt → Structured JSON findings
           └── Privacy score prompt → 0-100 score + summary
```

### Phase 6: Complete
```
Analysis complete
   │
   └── sendEvent('complete', {
         success,
         analysis,        // Full markdown report
         summaryFindings, // Structured findings array
         privacyScore,    // 0-100
         privacySummary,  // One sentence
         consentDetails,  // Consent dialog info
         scripts          // Scripts with descriptions
       })
   │
   └── session.close() → Cleanup Playwright (in finally block)
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
networkRequests      // NetworkRequest[]
localStorage         // StorageItem[]
sessionStorage       // StorageItem[]

// Analysis results
analysisResult       // Full markdown report
summaryFindings      // Structured findings array
privacyScore         // 0-100
privacySummary       // One-sentence summary
consentDetails       // Extracted consent info

// Dialog state
showScoreDialog      // Privacy score popup
showPageErrorDialog  // Access denied popup
showErrorDialog      // Generic error popup
errorDialog          // { title, message }
pageError            // { type, message, statusCode }
```

### SSE Event Handling

```typescript
// In analyzeUrl():
const eventSource = new EventSource(`/api/open-browser-stream?url=...&device=...`)

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
    ├── SummaryTab
    ├── AnalysisTab
    ├── CookiesTab
    ├── StorageTab
    ├── NetworkTab
    ├── ScriptsTab
    └── ConsentTab
```

---

## Server Architecture

### Service Layer

| Service | Responsibility |
|---------|---------------|
| `browser-session.ts` | Playwright browser session (per-request isolation for concurrency) |
| `device-configs.ts` | Device emulation profiles (iPhone, iPad, Android, etc.) |
| `access-detection.ts` | Bot blocking and access denial detection patterns |
| `openai.ts` | OpenAI/Azure OpenAI client management |
| `analysis.ts` | Main tracking analysis with LLM |
| `script-analysis.ts` | Script identification (patterns + LLM) |
| `consent-detection.ts` | AI vision to detect consent dialogs |
| `consent-extraction.ts` | AI to extract consent details |
| `consent-click.ts` | Click strategies for consent buttons |

### Data Layer

| Module | Content |
|--------|---------|
| `data/tracking-scripts.ts` | 300+ regex patterns for known trackers |
| `data/benign-scripts.ts` | ~55 patterns for safe libraries |

### Prompt Templates

| Prompt | Purpose |
|--------|---------|
| `tracking-analysis.ts` | Main analysis, summary findings, privacy score |
| `consent-detection.ts` | AI vision for overlay detection |
| `consent-extraction.ts` | Extract consent categories/partners |
| `script-analysis.ts` | Describe unknown scripts |

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
sendEvent('screenshot', data) in analyze-stream.ts
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
buildTrackingSummary() → Formatted text for LLM
    │
    ▼
OpenAI chat completion
    │
    ▼
Parse response (markdown or JSON)
    │
    ▼
sendEvent('complete', results)
    │
    ▼
Client displays analysis
```

---

## Key Data Types

### TrackedCookie
```typescript
interface TrackedCookie {
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite: string
  timestamp: string
}
```

### TrackedScript
```typescript
interface TrackedScript {
  url: string
  domain: string
  timestamp: string
  description?: string  // Added by script analysis
}
```

### NetworkRequest
```typescript
interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
}
```

### ConsentDetails
```typescript
interface ConsentDetails {
  hasManageOptions: boolean
  categories: { name: string; description: string; enabled: boolean }[]
  partners: { name: string; purposes: string[] }[]
  purposes: { name: string; description: string }[]
}
```

---

## SSE Events Reference

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `progress` | Server → Client | `{ step, message, progress }` | Loading progress updates |
| `screenshot` | Server → Client | `{ screenshot, cookies, scripts, networkRequests, localStorage, sessionStorage }` | Page capture with all data |
| `pageError` | Server → Client | `{ type, message, statusCode, isAccessDenied?, reason? }` | Access denied or HTTP error |
| `consentDetails` | Server → Client | `ConsentDetails` | Extracted consent dialog info |
| `complete` | Server → Client | `{ success, analysis, summaryFindings, privacyScore, privacySummary, scripts, consentDetails }` | Final analysis results |
| `error` | Server → Client | `{ error }` | Error message |

---

## Adding New Features

### Adding a New Tab

1. Create `client/src/components/tabs/NewTab.vue`
2. Export from `client/src/components/tabs/index.ts`
3. Import in `App.vue`
4. Add tab button and content section
5. Add to `TabId` type in `client/src/types/tracking.ts`

### Adding a New Tracking Data Type

1. Add interface to `server/src/types.ts`
2. Add capture method in `server/src/services/browser-session.ts`
3. Include in screenshot event payload
4. Add client interface in `client/src/types/tracking.ts`
5. Add reactive state in `useTrackingAnalysis.ts`
6. Display in appropriate tab

### Adding a New AI Analysis

1. Create prompt template in `server/src/prompts/`
2. Add analysis function in `server/src/services/`
3. Wrap OpenAI calls with `withRetry()` for rate limit handling
4. Call from `analyze-stream.ts` (consider parallel execution)
5. Include in `complete` event payload
6. Display in client

### Adding a New Overlay Type

1. Update `CookieConsentDetection` type in `server/src/types.ts`
2. Update detection prompt in `server/src/prompts/consent-detection.ts`
3. Add click strategy in `server/src/services/consent-click.ts`
4. Update `getOverlayMessage()` in `analyze-helpers.ts`

---

## Development Tips

### Virtual Display Setup

The browser runs in headed mode on a virtual display (Xvfb) to avoid bot detection by ad networks. This is automatically configured in:

**VS Code Devcontainer:**
- `postCreateCommand` installs Xvfb
- `postStartCommand` starts Xvfb on display `:99`
- `.vscode/launch.json` sets `DISPLAY=:99` for the debug server

**Docker:**
- `docker-entrypoint.sh` starts Xvfb before the server
- `Dockerfile` installs Xvfb and sets `ENV DISPLAY=:99`

**Manual Setup (if not using devcontainer):**
```bash
# Install Xvfb
sudo apt-get install -y xvfb

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -ac &

# Set DISPLAY before running the server
export DISPLAY=:99
npm run dev:server
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
```typescript
import { createLogger } from '../utils/index.js'

const log = createLogger('MyModule')

log.info('Starting operation', { param: value })
log.startTimer('my-operation')
// ... do work ...
log.endTimer('my-operation', 'Operation complete')
log.success('Done!', { result: data })
```

### Concurrency

- Each request creates its own `BrowserSession` instance
- Sessions are fully isolated - no shared state between requests
- Multiple users can analyze different URLs simultaneously
- Browser cleanup happens in `finally` block to prevent leaks

### Performance

- Script analysis uses pattern matching first, LLM only for unknowns
- Main analysis runs first, then summary + score in parallel
- Tracking arrays have limits (5000 requests, 1000 scripts) per session

### Rate Limit Handling

All OpenAI API calls use automatic retry with exponential backoff:

- **Retryable errors:** 429 (rate limit), 5xx (server errors), network failures
- **Backoff strategy:** Starts at 1s, doubles each retry, max 30s
- **Jitter:** ±20% randomization to prevent thundering herd
- **Header support:** Respects `Retry-After` headers from the API

```typescript
import { withRetry } from '../utils/index.js'

const result = await withRetry(
  () => client.chat.completions.create({ ... }),
  { 
    context: 'Main analysis',  // For logging
    maxRetries: 3,             // Default: 3
    initialDelayMs: 1000,      // Default: 1000
    maxDelayMs: 30000,         // Default: 30000
  }
)
```

When rate limits are hit, you'll see logs like:
```
[12:34:56.789] ⚠ [Retry] Retrying after transient error context="Main analysis" attempt=1 maxRetries=3 delayMs=1200 isRateLimit=true
```
