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
│   └── analyze-stream.ts     # Main SSE streaming endpoint
├── services/
│   ├── browser.ts            # Playwright browser management
│   ├── openai.ts             # Azure OpenAI client
│   ├── analysis.ts           # AI tracking analysis
│   ├── consent-detection.ts  # AI consent banner detection
│   ├── consent-extraction.ts # AI consent details extraction
│   └── consent-click.ts      # Consent button click strategies
├── prompts/
│   ├── index.ts              # Prompt exports
│   ├── consent-detection.ts  # Detection system prompt
│   ├── consent-extraction.ts # Extraction system prompt
│   └── tracking-analysis.ts  # Analysis system prompts
└── utils/
    ├── index.ts              # Utility exports
    ├── url.ts                # Domain/URL utilities
    ├── errors.ts             # Error handling
    └── tracking-summary.ts   # Data aggregation for LLM
```

## API Endpoint

### `GET /api/open-browser-stream?url={url}`

Analyzes tracking on the specified URL with real-time progress updates.

**Query Parameters:**
- `url` (required): The URL to analyze

**Response:** Server-Sent Events stream

**Events Emitted:**

| Event | Data | Description |
|-------|------|-------------|
| `progress` | `{ step, message, progress }` | Progress updates (0-100%) |
| `screenshot` | `{ screenshot, cookies, scripts, networkRequests, localStorage, sessionStorage }` | Page capture with tracking data |
| `consentDetails` | `{ categories, partners, purposes, hasManageOptions }` | Extracted consent dialog info |
| `consent` | `{ detected, clicked, details }` | Consent handling result |
| `complete` | `{ success, analysis, highRisks, analysisSummary, consentDetails }` | Final analysis results |
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

- **`launchBrowser(headless)`** - Launch browser instance with request tracking
- **`navigateTo(url, waitUntil)`** - Navigate to URL
- **`captureCurrentCookies()`** - Capture all cookies from browser context
- **`captureStorage()`** - Capture localStorage and sessionStorage
- **`takeScreenshot(fullPage)`** - Take PNG screenshot
- **`getPageContent()`** - Get full HTML content
- **`getTrackedCookies/Scripts/NetworkRequests()`** - Get tracked data arrays

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
  analysis?: string      // Full markdown report
  highRisks?: string     // Brief risk summary
  summary?: TrackingSummary
  error?: string
}
```

## Environment Variables

Create a `.env` file in the server directory:

```env
# Server port (default: 3001)
PORT=3001

# Azure OpenAI Configuration (required for AI analysis)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# Optional: API version (default: 2024-12-01-preview)
OPENAI_API_VERSION=2024-12-01-preview
```

## Development

### Prerequisites

- Node.js 18+
- Azure OpenAI resource with a deployed model (GPT-4o recommended for vision)

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
Launch Browser → Navigate to URL → Wait for content
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
Run AI privacy analysis
     ↓
Return complete results
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

### "Azure OpenAI not configured"

Ensure all required environment variables are set:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`

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
