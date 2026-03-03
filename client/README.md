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
│   ├── logo.svg                 # Application logo
│   └── mystery_machine.png      # Animated van for progress bar
├── components/
│   ├── index.ts                 # Barrel export
│   ├── ErrorDialog.vue          # Generic error dialog
│   ├── PageErrorDialog.vue      # Access denied/error dialog
│   ├── ProgressBanner.vue       # Loading progress indicator
│   ├── ScoreDialog.vue          # Privacy score results dialog
│   ├── ScreenshotGallery.vue    # Screenshot thumbnails + modal
│   ├── ScriptViewerDialog.vue   # Fullscreen script source viewer with syntax highlighting
│   ├── TrackerCategorySection.vue # Reusable tracker category block (used ×5 in SummaryTab)
│   └── tabs/
│       ├── index.ts             # Barrel export for tabs
│       ├── SummaryTab.vue       # AI analysis results with structured report and findings
│       ├── ConsentTab.vue       # Consent details with TCF purpose breakdown
│       ├── CookiesTab.vue       # Cookies by domain
│       ├── NetworkTab.vue       # Network requests
│       ├── ScriptsTab.vue       # Scripts by domain
│       ├── StorageTab.vue       # localStorage/sessionStorage
│       └── TrackerGraphTab.vue  # Interactive tracker relationship graph (D3.js)
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
- Connection errors with contextual messages based on progress step
- Browser and timeout errors with categorized titles
- General error handling

### ScreenshotGallery

Shows captured screenshots with:
- Thumbnail row with incremental numbering (1, 2, 3, ...)
- Click-to-expand modal
- Teleported overlay for fullscreen view

### ScriptViewerDialog

Fullscreen dialog for viewing JavaScript source code:
- Fetches script content via the server proxy (`POST /api/fetch-script`) to avoid CORS restrictions
- Beautifies minified code with js-beautify (2-space indent, preserved newlines)
- Applies syntax highlighting with highlight.js (One Dark-inspired colour theme)
- Displays the AI-generated script description from the Scripts tab
- Copy-to-clipboard button for the formatted source
- Link to the original script URL
- Truncation warning when scripts exceed 512 KB
- Loading spinner and error states
- Closes on Escape key or clicking the backdrop

### Tab Components

Each tab is a self-contained component with its own template and scoped styles:

| Component | Purpose |
|-----------|---------|
| `SummaryTab` | Full AI analysis with structured report, summary findings, and clickable vendor/service links |
| `ConsentTab` | Consent dialog details with IAB TCF v2.2 purpose breakdown, consent categories, and partners grouped by risk level |
| `CookiesTab` | Cookies grouped by domain with click-to-expand info lookup (database-first, LLM fallback) showing description, who sets it, purpose, risk level, and privacy note |
| `NetworkTab` | Network requests with third-party filter and filter explanation note |
| `ScriptsTab` | JavaScript files grouped by domain with click-to-view source dialog (syntax highlighted, auto-formatted) |
| `StorageTab` | localStorage and sessionStorage items with click-to-expand info lookup (database-first, LLM fallback) showing description, who sets it, purpose, risk level, and privacy note |
| `TrackerGraphTab` | Interactive force-directed network graph of tracker domain relationships using D3.js. Colour-coded by category (analytics, advertising, social, identity, session replay, consent management, CDN, first-party). Includes view modes (all domains, third-party only, pre-consent only), clickable category legend for single-category path filtering, first-party domain alias recognition, subdomain prefix heuristics, Disconnect override corrections, subgraph highlighting, minimap navigation, resource-type breakdown, and domain keyword heuristic to reduce "other" classifications |

### useTrackingAnalysis Composable

The core of the application logic, managing:

- **Reactive State**: All UI state including loading status, error messages, and collected data
- **SSE Connection**: Establishes and manages the EventSource connection to the server
- **Event Handlers**: Processes `progress`, `screenshot`, `consentDetails`, `pageError`, `complete`, and `error` events. Progress updates are monotonic — status messages and the progress bar only advance forward; out-of-order events from concurrent pipeline stages are silently ignored
- **Error Handling**: Categorized error titles (timeout, browser, configuration), contextual connection-loss messages based on progress step, and server-error priority to prevent overwriting specific error messages
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
  networkRequests,      // Raw network requests (used by TrackerGraphTab)
  activeTab,            // Currently selected tab
  structuredReport,     // Structured per-section report
  analysisError,        // Analysis error if AI failed
  summaryFindings,      // Structured findings array
  privacyScore,         // Privacy score (0-100)
  privacySummary,       // One-sentence summary
  showScoreDialog,      // Score dialog visibility
  consentDetails,       // Extracted consent info
  decodedCookies,       // Decoded structured cookies (TC/AC strings, OneTrust, etc.)
  pageError,            // Page error info (access denied, etc.)
  showPageErrorDialog,  // Page error dialog visibility
  errorDialog,          // Generic error dialog info { title, message }
  showErrorDialog,      // Error dialog visibility
  statusMessage,        // Current progress message
  progressStep,         // Current step identifier
  progressPercent,      // Progress bar value (0-100)
  selectedScreenshot,   // Currently selected screenshot index

  // Computed
  scriptsByDomain,      // Scripts grouped by domain
  cookiesByDomain,      // Cookies grouped by domain
  filteredNetworkRequests, // Network requests (filtered)
  networkByDomain,      // Network requests grouped by domain
  graphConnectionCount, // Number of connections in the tracker graph

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
| `CookieInfo` | Cookie lookup result with description, setBy, purpose, riskLevel, and privacyNote |
| `StorageInfo` | Storage key lookup result with description, setBy, purpose, riskLevel, and privacyNote |
| `TcfPurpose` | IAB TCF v2.2 purpose with id, name, description, riskLevel, lawfulBases, notes, and category |
| `TcfLookupResult` | TCF purpose lookup result with matched purposes and unmatched strings |
| `NetworkRequest` | HTTP request with domain, type, third-party flag, initiator domain, and redirect source |
| `ConsentCategory` | Cookie category from consent dialog |
| `ConsentPartner` | Third-party vendor from consent dialog (with risk classification and URL) |
| `TcStringData` | Decoded IAB TCF v2 consent string (CMP metadata, purpose/vendor consents, LI signals) |
| `AcStringData` | Decoded Google Additional Consent string (version, provider IDs, resolved names) |
| `ResolvedVendor` | Vendor ID resolved to name from IAB GVL |
| `ResolvedAcProvider` | Provider ID resolved to name from Google ATP list |
| `TcPurposeSignal` | Individual TCF purpose consent/LI signal with purpose name and granted status |
| `TcValidationFinding` | TC String validation finding (severity level and description) |
| `TcValidationResult` | Collection of TC String validation findings |
| `DecodedCookies` | All decoded structured cookies (USP, GPP, GA, FB, Google Ads, OneTrust, Cookiebot, SOCS, GPC/DNT) |
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
| `ConsentDiscrepancy` | Discrepancy between consent claims and observed tracking |
| `ConsentAnalysisSection` | Consent analysis with discrepancies and summary |
| `RecommendationGroup` | Group of recommendations by priority |
| `RecommendationsSection` | Collection of recommendation groups |
| `SocialMediaRisk` | Per-platform social media privacy risk with severity |
| `SocialMediaImplicationsSection` | Social media tracking implications analysis (platforms, identity linking risk, risks, summary) |
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
6. **Screenshot Gallery**: Thumbnails of captured screenshots (clickable for fullscreen)
7. **Tab Navigation**: Switch between different data views
8. **Data Panels**: Display collected tracking information

### Available Tabs

| Tab | Content |
|-----|---------|
| **Summary** | Structured privacy report with summary findings and AI analysis |
| **Consent** | TCF purpose breakdown with risk levels, TC String/AC String decoding, decoded cookie breakdowns, consent categories, and partners grouped by risk classification (visible when consent dialog detected) |
| **Cookies** | All cookies grouped by domain — click any cookie for instant identification (description, who sets it, purpose, risk level, privacy note) |
| **Storage** | localStorage and sessionStorage items — click any key for instant identification (description, who sets it, purpose, risk level, privacy note) |
| **Network** | HTTP requests with third-party filter |
| **Graph** | Interactive tracker relationship graph showing domain connections, colour-coded by category with first-party and CDN classification, view modes for all domains, third-party only, and pre-consent only |
| **Scripts** | JavaScript files grouped by domain — click any URL to view syntax-highlighted source in a fullscreen dialog |

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
  `${apiBase}/api/open-browser-stream?url=${encodeURIComponent(url)}&device=${deviceType}&clear-cache=${clearCache}`
)

eventSource.addEventListener('progress', (event) => { /* Update status */ })
eventSource.addEventListener('screenshot', (event) => { /* Add screenshot + data */ })
eventSource.addEventListener('screenshotUpdate', (event) => { /* Replace latest screenshot */ })
eventSource.addEventListener('pageError', (event) => { /* Show page error dialog */ })
eventSource.addEventListener('consentDetails', (event) => { /* Store consent info */ })
eventSource.addEventListener('decodedCookies', (event) => { /* Store decoded cookie breakdowns */ })
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
| `screenshotUpdate` | `{ screenshot }` | Replace most recent screenshot (targeted refresh at key pipeline points) |
| `consentDetails` | `ConsentDetails` | Store consent dialog information |
| `decodedCookies` | `DecodedCookies` | Store decoded structured cookie breakdowns |
| `pageError` | `{ type, message, statusCode }` | Display page error dialog |
| `completeTracking` | `{ cookies, networkRequests, localStorage, sessionStorage }` | Final tracking data snapshot (uncapped) |
| `completeScripts` | `{ scripts, scriptGroups }` | Analysed scripts and groups |
| `complete` | `{ message, structuredReport, summaryFindings, privacyScore, privacySummary, analysisError, consentDetails, decodedCookies }` | Final results with AI analysis and privacy score |
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
```

### Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start Vite dev server with HMR |
| `npm run build` | Type check and build for production |

## Technology Stack

- **Vue 3**: Composition API with `<script setup>` syntax
- **TypeScript**: Full type safety throughout
- **D3.js**: Force-directed graph visualization for the tracker graph tab
- **Vite**: Fast build tool and dev server
- **CSS**: Global shared styles + scoped component styles

## Styling Architecture

### Global Styles (`style.css`)

Contains design tokens (CSS custom properties on `:root`) and shared CSS classes used across multiple components. All tab components reference these tokens for consistent typography, colours, and spacing.

#### Design Tokens

| Token Group | Examples | Purpose |
|-------------|----------|--------|
| Typography | `--section-title-size`, `--body-size`, `--summary-size` | Consistent font sizing across all tabs |
| Colours | `--section-title-color`, `--body-color`, `--link-color`, `--muted-color` | Unified colour palette |
| Surfaces | `--surface-section`, `--surface-card`, `--surface-card-inner`, `--surface-panel` | Nested background layers |
| Borders | `--border-card`, `--border-separator`, `--border-accent` | Consistent border styling |
| Badges | `--badge-radius`, `--badge-padding`, `--badge-size` | Uniform badge appearance |
| Stats | `--stat-value-size`, `--stat-label-size` | Dashboard-style stat blocks |

#### Shared Classes

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
