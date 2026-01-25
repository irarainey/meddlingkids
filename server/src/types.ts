/**
 * @fileoverview Type definitions for the tracking analysis server.
 * Contains interfaces for cookies, scripts, storage, network requests,
 * consent detection, and analysis results.
 */

// ============================================================================
// Tracking Data Types
// ============================================================================

/**
 * Represents a cookie captured from the browser context.
 * Contains all standard cookie attributes plus a timestamp for when it was captured.
 */
export interface TrackedCookie {
  /** Cookie name (e.g., '_ga', 'sessionId') */
  name: string
  /** Cookie value (may be encoded or encrypted) */
  value: string
  /** Domain the cookie is associated with */
  domain: string
  /** URL path the cookie is valid for */
  path: string
  /** Unix timestamp when cookie expires (-1 for session cookies) */
  expires: number
  /** Whether the cookie is only accessible via HTTP (not JavaScript) */
  httpOnly: boolean
  /** Whether the cookie requires HTTPS */
  secure: boolean
  /** SameSite attribute: 'Strict', 'Lax', or 'None' */
  sameSite: string
  /** ISO timestamp when the cookie was captured */
  timestamp: string
}

/**
 * Represents a JavaScript script loaded by the page.
 * Used to identify third-party tracking scripts.
 */
export interface TrackedScript {
  /** Full URL of the script */
  url: string
  /** Domain the script was loaded from */
  domain: string
  /** ISO timestamp when the script was detected */
  timestamp: string
  /** AI-generated description of the script's purpose */
  description?: string
}

/**
 * Represents an item stored in localStorage or sessionStorage.
 */
export interface StorageItem {
  /** Storage key name */
  key: string
  /** Stored value (may be JSON stringified) */
  value: string
  /** ISO timestamp when the item was captured */
  timestamp: string
}

/**
 * Represents an HTTP network request made by the page.
 * Used to identify tracking pixels, beacons, and API calls.
 */
export interface NetworkRequest {
  /** Full URL of the request */
  url: string
  /** Domain the request was sent to */
  domain: string
  /** HTTP method (GET, POST, etc.) */
  method: string
  /** Type of resource: 'script', 'image', 'xhr', 'fetch', etc. */
  resourceType: string
  /** Whether this request was to a third-party domain */
  isThirdParty: boolean
  /** ISO timestamp when the request was made */
  timestamp: string
  /** HTTP status code from the response (if captured) */
  statusCode?: number
}

// ============================================================================
// Cookie Consent Types
// ============================================================================

/**
 * Type of overlay detected on the page.
 */
export type OverlayType = 'cookie-consent' | 'sign-in' | 'newsletter' | 'paywall' | 'age-verification' | 'other'

/**
 * Result of LLM vision analysis for detecting cookie consent banners and other blocking overlays.
 * Used to find and click dismiss/accept buttons automatically.
 */
export interface CookieConsentDetection {
  /** Whether a blocking overlay was found */
  found: boolean
  /** Type of overlay detected */
  overlayType: OverlayType | null
  /** CSS selector to click the dismiss/accept button, or null if not found */
  selector: string | null
  /** Text displayed on the button */
  buttonText: string | null
  /** LLM's confidence in the detection */
  confidence: 'high' | 'medium' | 'low'
  /** Human-readable explanation of the detection result */
  reason: string
}

/**
 * Represents a cookie category disclosed in a consent dialog.
 * Examples: "Necessary", "Analytics", "Marketing", "Functional"
 */
export interface ConsentCategory {
  /** Name of the category */
  name: string
  /** Description of what this category is used for */
  description: string
  /** Whether this category is required and cannot be disabled */
  required: boolean
}

/**
 * Represents a third-party partner/vendor listed in a consent dialog.
 * These are companies that receive data when the user accepts cookies.
 */
export interface ConsentPartner {
  /** Name of the partner company */
  name: string
  /** What the partner does with the data */
  purpose: string
  /** Types of data collected by this partner */
  dataCollected: string[]
}

/**
 * Detailed information extracted from a cookie consent dialog.
 * Contains all the fine print that users typically don't read.
 */
export interface ConsentDetails {
  /** Whether there's a button to manage detailed preferences */
  hasManageOptions: boolean
  /** CSS selector for the manage options button, if present */
  manageOptionsSelector: string | null
  /** Cookie categories disclosed in the dialog */
  categories: ConsentCategory[]
  /** Third-party partners/vendors listed */
  partners: ConsentPartner[]
  /** Stated purposes for data collection */
  purposes: string[]
  /** Raw text excerpts from the consent dialog */
  rawText: string
  /** Whether the preferences panel was expanded to get more details */
  expanded?: boolean
}

// ============================================================================
// Analysis Types
// ============================================================================

/**
 * Tracking data grouped by domain.
 * Used for analyzing which domains are collecting what data.
 */
export interface DomainData {
  /** Cookies from this domain */
  cookies: TrackedCookie[]
  /** Scripts loaded from this domain */
  scripts: TrackedScript[]
  /** Network requests to this domain */
  networkRequests: NetworkRequest[]
}

/**
 * Summary statistics for a single domain's tracking activity.
 * Used in the analysis report to show per-domain breakdown.
 */
export interface DomainBreakdown {
  /** The domain name */
  domain: string
  /** Number of cookies from this domain */
  cookieCount: number
  /** Names of all cookies from this domain */
  cookieNames: string[]
  /** Number of scripts from this domain */
  scriptCount: number
  /** Number of network requests to this domain */
  requestCount: number
  /** Types of resources requested (script, image, xhr, etc.) */
  requestTypes: string[]
}

/**
 * Complete summary of tracking data collected from a page.
 * This is sent to the LLM for privacy analysis.
 */
export interface TrackingSummary {
  /** URL that was analyzed */
  analyzedUrl: string
  /** Total number of cookies captured */
  totalCookies: number
  /** Total number of scripts detected */
  totalScripts: number
  /** Total number of network requests tracked */
  totalNetworkRequests: number
  /** Number of localStorage items */
  localStorageItems: number
  /** Number of sessionStorage items */
  sessionStorageItems: number
  /** List of third-party domains detected */
  thirdPartyDomains: string[]
  /** Per-domain breakdown of tracking data */
  domainBreakdown: DomainBreakdown[]
  /** Preview of localStorage contents */
  localStorage: { key: string; valuePreview: string }[]
  /** Preview of sessionStorage contents */
  sessionStorage: { key: string; valuePreview: string }[]
}

/**
 * Result of the AI-powered tracking analysis.
 * Contains the full markdown report and a high-risks summary.
 */
export interface AnalysisResult {
  /** Whether the analysis completed successfully */
  success: boolean
  /** Full markdown analysis report */
  analysis?: string
  /** Brief summary of highest privacy risks */
  highRisks?: string
  /** Privacy risk score (0-100) */
  privacyScore?: number
  /** One-sentence summary for the results dialog */
  privacySummary?: string
  /** Tracking data summary used for the analysis */
  summary?: TrackingSummary
  /** Error message if analysis failed */
  error?: string
}
