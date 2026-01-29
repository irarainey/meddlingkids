# Tracking Analysis Server

A Node.js server that analyzes website tracking and privacy practices using browser automation and AI-powered analysis.

## Overview

This server provides a streaming API endpoint that:

1. **Launches a browser** using Playwright (headed mode on virtual display)
2. **Navigates to a URL** and waits for content to load
3. **Detects cookie consent banners** using AI vision analysis
4. **Extracts consent details** (partners, categories, purposes) before accepting
5. **Clicks "Accept All"** to see what tracking activates
6. **Captures tracking data** (cookies, scripts, network requests, storage)
7. **Generates an AI privacy analysis** with risk assessment

All progress is streamed to the client via Server-Sent Events (SSE).

## Architecture

```
server/src/
├── app.ts                    # Express server entry point
├── types.ts                  # TypeScript interfaces
├── routes/
│   ├── index.ts              # Route exports
│   ├── analyze-stream.ts     # Main SSE streaming endpoint
│   └── analyze-helpers.ts    # Helper functions for streaming
├── services/
│   ├── browser-session.ts    # Playwright browser session (per-request isolation)
│   ├── device-configs.ts     # Device emulation profiles
│   ├── access-detection.ts   # Bot blocking detection patterns
│   ├── openai.ts             # Azure OpenAI / OpenAI client
│   ├── analysis.ts           # AI tracking analysis
│   ├── privacy-score.ts      # Deterministic privacy score calculation
│   ├── script-analysis.ts    # Script identification & LLM analysis
│   ├── consent-detection.ts  # AI consent banner detection
│   ├── consent-extraction.ts # AI consent details extraction
│   └── consent-click.ts      # Consent button click strategies
├── data/
│   ├── index.ts              # Data exports
│   ├── types.ts              # Type definitions for data structures
│   ├── loader.ts             # JSON data loader with lazy loading & caching
│   ├── partners/             # Partner risk classification databases
│   │   ├── ad-networks.json        # 106 advertising networks
│   │   ├── analytics-trackers.json # 72 analytics providers
│   │   ├── consent-platforms.json  # 33 consent management platforms
│   │   ├── data-brokers.json       # 89 data brokers
│   │   ├── identity-trackers.json  # 54 identity resolution providers
│   │   ├── mobile-sdk-trackers.json# 46 mobile tracking SDKs
│   │   ├── session-replay.json     # 61 session replay tools
│   │   └── social-trackers.json    # 43 social media trackers
│   └── trackers/             # Script pattern databases
│       ├── tracking-scripts.json   # 495 known tracking script patterns
│       └── benign-scripts.json     # 51 known benign library patterns
├── prompts/
│   ├── index.ts              # Prompt exports
│   ├── consent-detection.ts  # Detection system prompt
│   ├── consent-extraction.ts # Extraction system prompt
│   ├── script-analysis.ts    # Script analysis system prompt
│   └── tracking-analysis.ts  # Analysis system prompts
└── utils/
    ├── index.ts              # Utility exports
    ├── url.ts                # Domain/URL utilities
    ├── errors.ts             # Error handling
    ├── logger.ts             # Logging with timestamps and timing
    ├── retry.ts              # Retry with exponential backoff for API calls
    └── tracking-summary.ts   # Data aggregation for LLM
```

## API Endpoint

### `GET /api/open-browser-stream?url={url}&device={device}`

Analyzes tracking on the specified URL with real-time progress updates.

**Query Parameters:**
- `url` (required): The URL to analyze
- `device` (optional): Device to emulate. One of: `iphone`, `ipad`, `android-phone`, `android-tablet`, `windows-chrome`, `macos-safari`. Default: `ipad`

**Response:** Server-Sent Events stream

**Events Emitted:**

| Event | Data | Description |
|-------|------|-------------|
| `progress` | `{ step, message, progress }` | Progress updates (0-100%) |
| `screenshot` | `{ screenshot, cookies, scripts, networkRequests, localStorage, sessionStorage }` | Page capture with tracking data |
| `consentDetails` | `{ categories, partners, purposes, hasManageOptions }` | Extracted consent dialog info |
| `consent` | `{ detected, clicked, details }` | Consent handling result |
| `pageError` | `{ type, message, statusCode, isAccessDenied?, reason? }` | Access denied or server error detected |
| `complete` | `{ success, message, analysis, summaryFindings, privacyScore, privacySummary, analysisSummary, analysisError?, consentDetails, scripts }` | Final analysis results with privacy score and analyzed scripts |
| `error` | `{ error }` | Error message if something fails |

**Example:**
```javascript
const eventSource = new EventSource(
  `http://localhost:3001/api/open-browser-stream?url=${encodeURIComponent('https://example.com')}`
)

eventSource.addEventListener('progress', (event) => {
  const { step, message, progress } = JSON.parse(event.data)
  console.log(`[${progress}%] ${message}`)
})

eventSource.addEventListener('complete', (event) => {
  const { analysis, summaryFindings } = JSON.parse(event.data)
  console.log('Analysis:', analysis)
  eventSource.close()
})
```

## Services

### Browser Session (`services/browser-session.ts`)

Manages Chromium browser sessions via Playwright. Runs in headed mode on a virtual display (Xvfb) to avoid bot detection by ad networks. Each `BrowserSession` instance is isolated, enabling concurrent URL analyses without interference.

**Class: `BrowserSession`**

- **`launchBrowser(deviceType)`** - Launch browser with device emulation
- **`close()`** - Close browser and clean up all resources
- **`navigateTo(url, waitUntil)`** - Navigate to URL with timeout
- **`waitForNetworkIdle(timeout)`** - Wait for network activity to settle
- **`captureCurrentCookies()`** - Capture all cookies from browser context
- **`captureStorage()`** - Capture localStorage and sessionStorage
- **`takeScreenshot(fullPage)`** - Take PNG screenshot
- **`getPageContent()`** - Get full HTML content
- **`checkForAccessDenied()`** - Detect bot protection or access denied pages
- **`clearTrackingData()`** - Reset all tracked data arrays
- **`setCurrentPageUrl(url)`** - Set URL for third-party detection
- **`getTrackedCookies/Scripts/NetworkRequests()`** - Get tracked data arrays
- **`getPage()`** - Get the Playwright Page instance
- **`isActive()`** - Check if browser session is active

**Concurrency Support:** Each request creates its own `BrowserSession` instance, allowing multiple analyses to run simultaneously without shared state conflicts.

**Tracking Limits:** Each session enforces limits to prevent memory issues:
- Maximum 5,000 network requests tracked
- Maximum 1,000 scripts tracked

**Supported Device Types:**
- `iphone` - iPhone 15 Pro Max (Safari)
- `ipad` - iPad Pro 12.9" (Safari)
- `android-phone` - Pixel 8 Pro (Chrome)
- `android-tablet` - Samsung Galaxy Tab S9 (Chrome)
- `windows-chrome` - Windows 11 (Chrome)
- `macos-safari` - macOS Sonoma (Safari)

### Analysis Service (`services/analysis.ts`)

Runs AI-powered tracking analysis:

- **`runTrackingAnalysis(...)`** - Analyzes all tracking data and generates:
  - Full markdown privacy report (AI-generated)
  - Summary findings for the summary tab (AI-generated)
  - Privacy score (0-100) calculated deterministically
  - Tracking data summary

### Privacy Score Service (`services/privacy-score.ts`)

Calculates a **deterministic privacy score** (0-100) based on quantifiable factors. This ensures consistent scores across repeated scans of the same site.

**Scoring Categories (max 100 points):**

| Category | Max Points | Factors |
|----------|------------|---------|
| Cookies | 15 | Total count, third-party cookies, tracking cookies, long-lived cookies |
| Third-Party Trackers | 20 | Number of domains, request count, known trackers |
| Data Collection | 10 | Storage usage, tracking beacons, POST requests |
| Fingerprinting | 15 | Session replay tools, device fingerprinting, cross-device tracking |
| Advertising | 15 | Ad networks count, retargeting cookies, programmatic bidding |
| Social Media | 10 | Social trackers, embedded plugins |
| Sensitive Data | 10 | Location tracking, political profiling, identity resolution |
| Consent Issues | 10 | Partner count, pre-consent tracking, vague purposes |

**Known Trackers Identified:**
- 495 tracking script patterns (Google, Facebook, Criteo, etc.)
- 504 classified partners across 8 risk categories
- High-risk trackers: session replay (Hotjar, FullStory), fingerprinting, data brokers
- Advertising networks: Google Ads, Facebook Ads, Amazon, programmatic exchanges
- Social media: Facebook SDK, Twitter widgets, LinkedIn Insight

### Consent Services

- **`consent-detection.ts`** - Uses AI vision to detect consent banners and find the "Accept All" button
- **`consent-extraction.ts`** - Extracts detailed consent information (partners, categories, purposes)
- **`consent-click.ts`** - Multiple strategies to click consent buttons, including iframe handling

### Script Analysis Service (`services/script-analysis.ts`)

Identifies and analyzes JavaScript files loaded by the page:

- **`analyzeScripts(scripts, maxLLMAnalyses, onProgress)`** - Analyzes scripts to determine their purpose

**Analysis Flow:**
1. Match scripts against 495 known tracking patterns (instant identification)
2. Match scripts against 51 known benign library patterns (skip LLM)
3. Use LLM to analyze remaining unknown scripts (limited to `maxLLMAnalyses`)

### Retry Handling (`utils/retry.ts`)

All OpenAI API calls are wrapped with automatic retry logic to handle transient failures:

- **Rate Limits (429)** - Automatically retried with exponential backoff
- **Server Errors (5xx)** - Retried up to 3 times
- **Network Issues** - Connection resets, timeouts, etc. are retried

**Configuration:**
- Default: 3 retries with 1s initial delay, doubling each retry (max 30s)
- Jitter: ±20% randomization to prevent thundering herd
- Respects `Retry-After` headers from the API

```typescript
import { withRetry } from '../utils/index.js'

const result = await withRetry(
  () => client.chat.completions.create({ ... }),
  { context: 'Main analysis', maxRetries: 3 }
)
```

### Data Modules (`data/`)

JSON databases of known trackers and partners, loaded lazily with caching:

**Script Pattern Databases (`data/trackers/`):**
- **`tracking-scripts.json`** - 495 tracking script patterns with descriptions (Google Analytics, Facebook Pixel, etc.)
- **`benign-scripts.json`** - 51 benign library patterns (jQuery, React, CDN libraries, etc.)

**Partner Risk Databases (`data/partners/`):**
- **`data-brokers.json`** - 89 data brokers (Acxiom, Oracle Data Cloud, etc.)
- **`ad-networks.json`** - 106 advertising networks (Google Ads, Criteo, etc.)
- **`analytics-trackers.json`** - 72 analytics providers (Google Analytics, Adobe Analytics, etc.)
- **`session-replay.json`** - 61 session replay tools (Hotjar, FullStory, etc.)
- **`identity-trackers.json`** - 54 identity resolution providers (LiveRamp, The Trade Desk, etc.)
- **`social-trackers.json`** - 43 social media trackers (Facebook Pixel, Twitter, etc.)
- **`mobile-sdk-trackers.json`** - 46 mobile tracking SDKs (Adjust, AppsFlyer, etc.)
- **`consent-platforms.json`** - 33 consent management platforms (OneTrust, CookieBot, etc.)

**Data Loader (`loader.ts`):**
- Lazy loading - data loaded on first access
- Caching - loaded data cached in memory
- Type safety - full TypeScript types for all data
- RegExp compilation - patterns compiled from JSON strings

## Data Types

### Tracking Data

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

interface TrackedScript {
  url: string
  domain: string
  timestamp: string
}

interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
}

interface StorageItem {
  key: string
  value: string
  timestamp: string
}
```

### Consent Types

```typescript
interface ConsentDetails {
  hasManageOptions: boolean
  manageOptionsSelector: string | null
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  rawText: string
}

interface ConsentCategory {
  name: string
  description: string
  required: boolean
}

interface ConsentPartner {
  name: string
  purpose: string
  dataCollected: string[]
}
```

### Summary Finding

```typescript
type SummaryFindingType = 'critical' | 'high' | 'moderate' | 'info' | 'positive'

interface SummaryFinding {
  type: SummaryFindingType
  text: string
}
```

### Analysis Result

```typescript
interface AnalysisResult {
  success: boolean
  analysis?: string          // Full markdown report
  summaryFindings?: SummaryFinding[]  // Structured findings for summary tab
  privacyScore?: number      // Privacy score 0-100 (higher is worse)
  privacySummary?: string    // One-sentence summary
  siteName?: string          // Extracted site name
  summary?: TrackingSummary
  error?: string
}
```

## Environment Variables

Create a `.env` file in the server directory. Configure either Azure OpenAI OR standard OpenAI:

**Option A: Azure OpenAI**
```env
# Server port (default: 3001)
PORT=3001

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# Optional: API version (default: 2024-12-01-preview)
OPENAI_API_VERSION=2024-12-01-preview
```

**Option B: Standard OpenAI**
```env
# Server port (default: 3001)
PORT=3001

# OpenAI Configuration
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-5.1-chat

# Optional: Custom base URL for OpenAI-compatible APIs
# OPENAI_BASE_URL=https://api.openai.com/v1
```

## Development

### Prerequisites

- Node.js 22+ (uses native TypeScript support)
- OpenAI API key or Azure OpenAI resource (GPT-5.1 recommended for vision)
- Xvfb (virtual display) for browser automation

### Installation

```bash
cd server
npm install
```

### Virtual Display Setup

The browser runs in headed mode to avoid ad network bot detection. It needs a virtual display (Xvfb):

**Using VS Code Devcontainer (Recommended):**
Xvfb is automatically installed and started. Just use the "Debug Server" launch configuration which sets `DISPLAY=:99`.

**Manual Setup:**
```bash
# Install Xvfb (Debian/Ubuntu)
sudo apt-get install -y xvfb

# Start Xvfb on display :99
Xvfb :99 -screen 0 1920x1080x24 -ac &

# Run server with virtual display
DISPLAY=:99 npm run dev
```

### Running

```bash
# Development with hot reload (ensure DISPLAY=:99 is set)
DISPLAY=:99 npm run dev

# Production build
npm run build
npm start
```

### Type Checking

```bash
npm run typecheck
```

## How It Works

### 1. Browser Automation Flow

```
Launch Browser (headed mode on virtual display)
     ↓
Apply device emulation (viewport, user agent, touch)
     ↓
Navigate to URL → Wait for network idle (20s)
     ↓
Wait additional time for ads and deferred scripts
     ↓
Check for access denied / bot protection
     ↓
If blocked: Return page error to client
     ↓
Capture initial state (cookies, scripts, requests)
     ↓
Take screenshot → Detect consent banner (AI vision)
     ↓
If consent found:
  → Extract consent details (partners, categories)
  → Click "Accept All" button
  → Wait for page update
  → Recapture tracking data
     ↓
Calculate deterministic privacy score
     ↓
Run AI privacy analysis (markdown report + summary findings)
     ↓
Return complete results with privacy score
```

**Why Headed Mode on Virtual Display?**

Ad networks commonly detect and block headless browsers to prevent ad fraud. By running in headed mode, the browser passes fingerprinting checks that would otherwise block ads. The virtual display (Xvfb) means no actual window is shown - it renders to a virtual screen buffer instead.

This is configured via:
- `DISPLAY=:99` environment variable points to Xvfb
- `headless: false` in Playwright launch options
- `--disable-blink-features=AutomationControlled` removes automation flags

### 2. Consent Detection

The server uses Azure OpenAI to detect consent banners by sending **both a screenshot AND filtered HTML** to the LLM. Each serves a distinct purpose:

**Screenshot (Vision Analysis):**
- Visually detects consent banners even when dynamically rendered by JavaScript
- Sees banners inside iframes that may not appear in the main page HTML
- Reads button text even if styled unusually or rendered as images
- Provides high confidence that a consent banner is actually visible to users

**Filtered HTML:**
- Provides the CSS selectors, IDs, and class names needed to actually click the button
- Enables the LLM to return actionable selectors like `#onetrust-accept-btn-handler`
- Gives structural context when multiple similar buttons exist
- Acts as fallback context if the screenshot is unclear

The HTML is filtered to only include relevant elements (divs with cookie/consent/gdpr classes, buttons, etc.) and limited to ~15KB to minimize token usage while providing necessary context.

**Detection Flow:**
1. Take screenshot of the page
2. Extract relevant HTML snippets (cookie/consent/button elements)
3. Send both to Azure OpenAI vision model
4. LLM returns: `{ found, selector, buttonText, confidence, reason }`

**Fallback Click Strategies:**

If the LLM-suggested selector fails, fallback strategies try:
- Common button text patterns ("Accept All", "I Agree", etc.)
- Button role with partial text matching
- Consent buttons inside iframes (OneTrust, CookieBot, etc.)

### 3. Tracking Analysis

The AI analyzes collected data to identify:

- **Known tracking services** (Google Analytics, Facebook Pixel, etc.)
- **Data collection types** (browsing behavior, user IDs, cross-site tracking)
- **Third-party services** and their purposes
- **Privacy risk level** (Low/Medium/High/Very High)
- **Cookie purposes** (functional vs tracking)
- **Consent vs reality** comparison (what was disclosed vs what's happening)

### 4. Request Tracking

The browser tracks all network requests in real-time:

```typescript
page.on('request', (request) => {
  // Track scripts separately
  if (resourceType === 'script') {
    trackedScripts.push({ url, domain, timestamp })
  }
  
  // Track all requests with third-party detection
  trackedNetworkRequests.push({
    url,
    domain,
    method,
    resourceType,
    isThirdParty: isThirdParty(url, currentPageUrl),
    timestamp
  })
})
```

## Troubleshooting

### "OpenAI not configured"

Ensure you have configured either Azure OpenAI or standard OpenAI:

**Azure OpenAI:**
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`

**Standard OpenAI:**
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional, defaults to `gpt-5.1-chat`)

### Consent button not clicking

The server tries multiple click strategies. Check the console logs for which strategies were attempted. Common issues:
- Button is inside an iframe
- Button text doesn't match common patterns
- Page requires scrolling to see the button

### Browser crashes

Playwright requires certain system dependencies. On Linux, run:
```bash
npx playwright install-deps chromium
```

### Ads not loading / blank ad spaces

The browser runs in headed mode on a virtual display to avoid bot detection by ad networks. Ensure:

1. **Xvfb is running** on display `:99`:
   ```bash
   pgrep Xvfb || Xvfb :99 -screen 0 1920x1080x24 -ac &
   ```

2. **DISPLAY is set** to `:99` (not `:0` or `:1` which may be a real display):
   ```bash
   export DISPLAY=:99
   ```

3. **For Docker**, this is handled automatically by the entrypoint script.

4. **For VS Code devcontainer**, ensure `.vscode/launch.json` sets `DISPLAY: ":99"` in the env section.

## License

See the root [LICENSE](../LICENSE) file.
