# Meddling Kids - Client

The Vue.js frontend for the Meddling Kids tracking analysis tool. Provides an interactive interface for investigating website tracking behavior, displaying real-time analysis progress, and presenting detailed findings.

## Overview

The client is a single-page application built with Vue 3 and TypeScript. It connects to the server via Server-Sent Events (SSE) to receive real-time updates during URL analysis, displaying:

- **Progress indicators** during the multi-stage analysis
- **Screenshots** captured at each stage (initial load, after overlay dismissal, final state)
- **Tracking data** including cookies, scripts, storage, and network requests
- **AI-generated analysis** with risk assessments and privacy concerns
- **Overlay and consent details** extracted from page overlays

## Architecture

```
src/
├── App.vue                      # Main app shell (URL input, device selector, tab nav)
├── main.ts                      # Application entry point
├── style.css                    # Global styles
├── assets/
│   └── logo.svg                 # Application logo
├── components/
│   ├── index.ts                 # Barrel export
│   ├── ErrorDialog.vue          # Generic error dialog
│   ├── PageErrorDialog.vue      # Access denied/error dialog
│   ├── ProgressBanner.vue       # Loading progress indicator
│   ├── ScoreDialog.vue          # Privacy score results dialog
│   ├── ScreenshotGallery.vue    # Screenshot thumbnails + modal
│   └── tabs/
│       ├── index.ts             # Barrel export for tabs
│       ├── AnalysisTab.vue      # AI analysis results
│       ├── CookiesTab.vue       # Cookies by domain
│       ├── DebugLogTab.vue      # Server debug log (debug mode only)
│       ├── NetworkTab.vue       # Network requests
│       ├── ScriptsTab.vue       # Scripts by domain
│       └── StorageTab.vue       # localStorage/sessionStorage
├── composables/
│   ├── index.ts                 # Barrel export
│   └── useTrackingAnalysis.ts   # Main state management composable
├── types/
│   ├── index.ts                 # Barrel export
│   └── tracking.ts              # TypeScript interfaces
└── utils/
    ├── index.ts                 # Barrel export
    └── formatters.ts            # Display formatting utilities
```

## Key Components

### App.vue

The main application shell containing:
- Header with logo
- URL input bar with device type dropdown
- Tab navigation
- Privacy score dialog (Scooby-Doo themed)
- Page error dialog (for access denied/bot protection)
- Component mounting for each view

### ProgressBanner

Displays during analysis with:
- Animated Mystery Machine van
- Status message
- Progress bar with percentage

### ScoreDialog

Privacy score results dialog showing:
- Animated privacy score (0-100)
- Scooby-Doo themed exclamation (Zoinks!, Jeepers!, Ruh-Roh!, Jinkies!, or Scoob-tastic!)
- One-sentence privacy summary
- Site name

### PageErrorDialog

Error dialog for blocked pages:
- Access denied / bot protection detection
- Server error handling
- Helpful tips for users

### ErrorDialog

Generic error dialog for displaying error messages:
- Configuration errors (missing OpenAI keys)
- Connection errors
- General error handling

### ScreenshotGallery

Shows captured screenshots with:
- Thumbnail row with incremental numbering (1, 2, 3, ...)
- Click-to-expand modal
- Teleported overlay for fullscreen view

### Tab Components

Each tab is a self-contained component with its own template and scoped styles:

| Component | Purpose |
|-----------|---------|
| `AnalysisTab` | Full AI analysis with structured report, summary findings, and clickable vendor/service links |
| `CookiesTab` | Cookies grouped by domain |
| `DebugLogTab` | Server debug log output (visible in debug mode only) |
| `NetworkTab` | Network requests with third-party filter and filter explanation note |
| `ScriptsTab` | JavaScript files grouped by domain |
| `StorageTab` | localStorage and sessionStorage items |

### useTrackingAnalysis Composable

The core of the application logic, managing:

- **Reactive State**: All UI state including loading status, error messages, and collected data
- **SSE Connection**: Establishes and manages the EventSource connection to the server
- **Event Handlers**: Processes `progress`, `screenshot`, `consentDetails`, `pageError`, `complete`, and `error` events
- **Computed Properties**: Derived data like grouped cookies/scripts by domain, filtered network requests

```typescript
const {
  // State
  inputValue,           // URL input field
  deviceType,           // Selected device/browser type
  isLoading,            // Analysis in progress
  isComplete,           // Analysis finished
  screenshots,          // Array of base64 screenshots
  cookies,              // Tracked cookies
  scripts,              // Loaded scripts
  scriptGroups,         // Grouped similar scripts
  localStorage,         // localStorage items
  sessionStorage,       // sessionStorage items
  activeTab,            // Currently selected tab
  analysisResult,       // Full AI analysis (markdown)
  structuredReport,     // Structured per-section report
  analysisError,        // Analysis error if AI failed
  summaryFindings,      // Structured findings array
  privacyScore,         // Privacy score (0-100)
  privacySummary,       // One-sentence summary
  showScoreDialog,      // Score dialog visibility
  consentDetails,       // Extracted consent info
  pageError,            // Page error info (access denied, etc.)
  showPageErrorDialog,  // Page error dialog visibility
  errorDialog,          // Generic error dialog info { title, message }
  showErrorDialog,      // Error dialog visibility
  statusMessage,        // Current progress message
  progressStep,         // Current step identifier
  progressPercent,      // Progress bar value (0-100)
  selectedScreenshot,   // Currently selected screenshot index
  debugLog,             // Server debug log lines

  // Computed
  scriptsByDomain,      // Scripts grouped by domain
  cookiesByDomain,      // Cookies grouped by domain
  filteredNetworkRequests, // Network requests (filtered)
  networkByDomain,      // Network requests grouped by domain

  // Methods
  analyzeUrl,           // Start analysis
  openScreenshotModal,  // View screenshot fullscreen
  closeScreenshotModal, // Close modal
  closeScoreDialog,     // Close score dialog
  closePageErrorDialog, // Close page error dialog
  closeErrorDialog,     // Close generic error dialog
} = useTrackingAnalysis()
```

### Type Definitions

Located in `types/tracking.ts`:

| Interface | Description |
|-----------|-------------|
| `TrackedCookie` | Cookie with name, value, domain, expiry, security flags |
| `TrackedScript` | JavaScript file loaded by the page |
| `ScriptGroup` | Group of similar scripts (chunks, vendor bundles) |
| `StorageItem` | localStorage/sessionStorage entry |
| `NetworkRequest` | HTTP request with domain, type, third-party flag |
| `ConsentCategory` | Cookie category from consent dialog |
| `ConsentPartner` | Third-party vendor from consent dialog (with risk classification and URL) |
| `ConsentDetails` | Full consent dialog information |
| `SummaryFindingType` | Finding severity: critical, high, moderate, info, positive |
| `SummaryFinding` | Structured finding with type and text |
| `TrackerEntry` | Identified tracking technology with name, domains, cookies, purpose, and URL |
| `TrackingTechnologiesSection` | Categorised trackers (analytics, advertising, identity, social, other) |
| `NamedEntity` | Company or service name with optional URL for clickable links |
| `DataCollectionItem` | Data collection category with risk level and shared-with entities |
| `DataCollectionSection` | Collection of data collection items |
| `ThirdPartyGroup` | Third-party service group with services as named entities |
| `ThirdPartySection` | Collection of third-party groups |
| `RiskFactor` | Individual privacy risk factor with severity |
| `PrivacyRiskSection` | Overall privacy risk assessment with risk factors |
| `CookieGroup` | Cookie analysis group |
| `CookieAnalysisSection` | Cookie analysis details |
| `StorageAnalysisSection` | Storage analysis details |
| `StructuredReport` | Per-section structured privacy report |
| `ScreenshotModal` | Modal display state |
| `TabId` | Union type for tab identifiers |
| `PageError` | Access denied or server error information |
| `ErrorDialogState` | Generic error dialog state (title + message) |

### Utility Functions

Located in `utils/formatters.ts`:

| Function | Purpose |
|----------|---------|
| `getExclamation(score)` | Get themed exclamation based on privacy score |
| `getRiskLevel(score)` | Get risk level label based on privacy score |
| `getScoreClass(score)` | Get CSS class for score styling |
| `formatExpiry(expires)` | Format cookie expiry timestamp for display |
| `truncateValue(value, maxLength)` | Truncate long strings with ellipsis |
| `getResourceTypeIcon(type)` | Get emoji icon for resource type |
| `stripMarkdown(text)` | Strip markdown formatting (bold, italic, code, links, headers) from text |
| `formatMarkdown(text)` | Convert markdown to HTML for rendering |

## User Interface

### Main Sections

1. **URL Input Bar**: Enter a URL, select device type, and click "Unmask" to start analysis
2. **Device Selector**: Choose from iPhone, iPad, Android Phone, Android Tablet, Windows Chrome, or macOS Safari
3. **Progress Banner**: Shows current analysis step with animated Mystery Machine van
4. **Privacy Score Dialog**: Displays final privacy score with Scooby-Doo themed rating
5. **Page Error Dialog**: Displays access denied or server error information
3. **Screenshot Gallery**: Thumbnails of captured screenshots (clickable for fullscreen)
4. **Tab Navigation**: Switch between different data views
5. **Data Panels**: Display collected tracking information

### Available Tabs

| Tab | Content |
|-----|---------|
| **Analysis** | Structured privacy report with summary findings and AI analysis |
| **Cookies** | All cookies grouped by domain |
| **Storage** | localStorage and sessionStorage items |
| **Network** | HTTP requests with third-party filter |
| **Scripts** | JavaScript files grouped by domain |
| **Debug Log** | Server debug log output (debug mode only, enabled via `?debug=true`) |

### Visual Indicators

- **Mystery Machine van**: Animated van on progress bar during analysis
- **Progress bar**: Visual progress through analysis stages
- **Status messages**: Real-time updates ("Loading page...", "Detecting page overlays...", etc.)
- **Privacy score animation**: Animated counter revealing final score
- **Third-party badges**: Highlight external domains in network requests
- **Resource type icons**: Emoji indicators for request types (📜 script, 🔄 XHR, 🖼️ image)

## Server Communication

The client communicates with the server using Server-Sent Events:

```typescript
// Relative URL — Vite proxies /api to the Python server in development;
// production serves both client and API on the same origin.
const apiBase = import.meta.env.VITE_API_URL || ''
const eventSource = new EventSource(
  `${apiBase}/api/open-browser-stream?url=${encodeURIComponent(url)}&device=${deviceType}`
)

eventSource.addEventListener('progress', (event) => { /* Update status */ })
eventSource.addEventListener('screenshot', (event) => { /* Add screenshot + data */ })
eventSource.addEventListener('screenshotUpdate', (event) => { /* Replace latest screenshot */ })
eventSource.addEventListener('pageError', (event) => { /* Show page error dialog */ })
eventSource.addEventListener('consentDetails', (event) => { /* Store consent info */ })
eventSource.addEventListener('complete', (event) => { /* Finalize results */ })
eventSource.addEventListener('error', (event) => { /* Handle errors */ })
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `''` (empty) | Optional API base URL override. Not needed in normal use — the Vite dev proxy and same-origin production serving handle routing automatically. |

The environment is configured via:
- `vite.config.ts` - Dev proxy forwards `/api` requests to `http://localhost:3001`
- Production builds use relative URLs (same-origin server)

### Event Types Received

| Event | Payload | Purpose |
|-------|---------|---------|
| `progress` | `{ step, message, progress }` | Update progress bar and status |
| `screenshot` | `{ screenshot, cookies, scripts, ... }` | Add screenshot, update tracking data |
| `screenshotUpdate` | `{ screenshot }` | Replace most recent screenshot (background refresh) |
| `consentDetails` | `ConsentDetails` | Store consent dialog information |
| `pageError` | `{ type, message, statusCode }` | Display page error dialog |
| `analysis-chunk` | `{ text }` | Streamed token from tracking analysis (not currently consumed by client) |
| `complete` | `{ analysis, structuredReport, summaryFindings, privacyScore, privacySummary, scoreBreakdown, analysisSummary, analysisError, consentDetails, scripts, scriptGroups, debugLog }` | Final results with AI analysis and privacy score |
| `error` | `{ error }` | Display error message |

## Development

### Prerequisites

- Node.js 22+ (for building the Vue client and running the dev server)
- npm

### Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The development server runs on `http://localhost:5173` by default.

### Build

```bash
# Type check and build for production
npm run build

# Preview production build
npm run preview
```

### Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server with HMR |
| `npm run build` | Type check and build for production |
| `npm run preview` | Preview production build locally |

## Technology Stack

- **Vue 3**: Composition API with `<script setup>` syntax
- **TypeScript**: Full type safety throughout
- **Vite**: Fast build tool and dev server
- **CSS**: Global shared styles + scoped component styles

## Styling Architecture

### Global Styles (`style.css`)

Contains base styles and shared CSS classes used across multiple components:

| Class | Purpose |
|-------|---------|
| `.tab-content` | Base styling for all tab panels (border, scroll, background) |
| `.empty-state` | "No data" message styling |
| `.hint` | Secondary/helper text styling |
| `.domain-groups` | Container for grouped data (cookies, scripts, network) |
| `.domain-group` | Individual domain section |
| `.domain-header` | Sticky header for each domain group |
| `.badge` | Small label/tag styling |

### Component Scoped Styles

Each component contains only its unique styles using `<style scoped>`:

- **App.vue**: Header, URL bar, tab navigation buttons
- **ProgressBanner.vue**: Progress bar, spinner animation
- **ScreenshotGallery.vue**: Thumbnails, modal overlay
- **Tab components**: Item-specific styles (cookie-item, network-item, etc.)

This approach:
- Reduces CSS duplication across components
- Keeps the bundle size smaller
- Makes shared styles easy to update globally
- Preserves component encapsulation for unique styles

## Configuration

### Vite Configuration

The Vite config (`vite.config.ts`) includes:

- Vue plugin for SFC support
- Output directory set to `../dist` (shared with server)
- Development server proxy (if needed)

### TypeScript Configuration

- `tsconfig.app.json`: Client-specific TypeScript settings
- Strict mode enabled
- Vue type support via `vue-tsc`

## Design Patterns

### Composables

Following Vue 3 best practices, all logic is extracted into composables:

- Single responsibility: One composable for tracking analysis
- Reusable: Could be used in multiple components if needed
- Testable: Logic separated from presentation

### Barrel Exports

Each module directory includes an `index.ts` for clean imports:

```typescript
// Instead of:
import { useTrackingAnalysis } from './composables/useTrackingAnalysis'

// Use:
import { useTrackingAnalysis } from './composables'
```

### Type Safety

All data structures are fully typed:

- Server responses typed with interfaces
- Computed properties return typed objects
- Event handlers use proper typing

## Browser Support

The application uses modern JavaScript features:

- ES2022+ syntax
- Native EventSource API
- CSS custom properties
- Flexbox and Grid layouts

Recommended browsers: Chrome, Firefox, Safari, Edge (latest versions).
