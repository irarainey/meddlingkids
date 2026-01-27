# Tracking Analysis Server

A Node.js server that analyzes website tracking and privacy practices using headless browser automation and AI-powered analysis.

## Overview

This server provides a streaming API endpoint that:

1. **Launches a headless browser** using Playwright
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
│   ├── browser.ts            # Playwright browser management
│   ├── openai.ts             # Azure OpenAI / OpenAI client
│   ├── analysis.ts           # AI tracking analysis
│   ├── script-analysis.ts    # Script identification & LLM analysis
│   ├── consent-detection.ts  # AI consent banner detection
│   ├── consent-extraction.ts # AI consent details extraction
│   └── consent-click.ts      # Consent button click strategies
├── data/
│   ├── index.ts              # Data exports
│   ├── tracking-scripts.ts   # 300+ known tracking script patterns
│   └── benign-scripts.ts     # Known benign library patterns
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
| `complete` | `{ success, message, analysis, highRisks, privacyScore, privacySummary, analysisSummary, analysisError?, consentDetails, scripts }` | Final analysis results with privacy score and analyzed scripts |
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
  const { analysis, highRisks } = JSON.parse(event.data)
  console.log('Analysis:', analysis)
  eventSource.close()
})
```

## Services

### Browser Service (`services/browser.ts`)

Manages headless Chromium browser via Playwright:

- **`launchBrowser(headless, deviceType)`** - Launch browser instance with device emulation
- **`closeBrowser()`** - Close browser and clean up all resources
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
- **`isBrowserActive()`** - Check if browser session is active

**Tracking Limits:** The browser service enforces limits to prevent memory issues:
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
  - Full markdown privacy report
  - High-risks bullet-point summary
  - Tracking data summary

### Consent Services

- **`consent-detection.ts`** - Uses AI vision to detect consent banners and find the "Accept All" button
- **`consent-extraction.ts`** - Extracts detailed consent information (partners, categories, purposes)
- **`consent-click.ts`** - Multiple strategies to click consent buttons, including iframe handling

### Script Analysis Service (`services/script-analysis.ts`)

Identifies and analyzes JavaScript files loaded by the page:

- **`analyzeScripts(scripts, maxLLMAnalyses, onProgress)`** - Analyzes scripts to determine their purpose

**Analysis Flow:**
1. Match scripts against 300+ known tracking patterns (instant identification)
2. Match scripts against ~55 known benign library patterns (skip LLM)
3. Use LLM to analyze remaining unknown scripts (limited to `maxLLMAnalyses`)

### Data Modules (`data/`)

Pre-compiled databases of known script patterns:

- **`tracking-scripts.ts`** - 300+ tracking script patterns with descriptions (Google Analytics, Facebook Pixel, etc.)
- **`benign-scripts.ts`** - ~55 benign library patterns (jQuery, React, CDN libraries, etc.)

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

### Analysis Result

```typescript
interface AnalysisResult {
  success: boolean
  analysis?: string        // Full markdown report
  highRisks?: string       // Brief risk summary
  privacyScore?: number    // Privacy score 0-100 (lower is worse)
  privacySummary?: string  // One-sentence summary
  siteName?: string        // Extracted site name
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
OPENAI_MODEL=gpt-4o

# Optional: Custom base URL for OpenAI-compatible APIs
# OPENAI_BASE_URL=https://api.openai.com/v1
```

## Development

### Prerequisites

- Node.js 22+ (uses native TypeScript support)
- OpenAI API key or Azure OpenAI resource (GPT-4o recommended for vision)

### Installation

```bash
cd server
npm install
```

### Running

```bash
# Development with hot reload
npm run dev

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
Launch Browser (with device emulation) → Navigate to URL → Wait for content
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
Run AI privacy analysis (parallel: analysis + score)
     ↓
Return complete results with privacy score
```

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
- `OPENAI_MODEL` (optional, defaults to `gpt-4o`)

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

## License

See the root [LICENSE](../LICENSE) file.
