/**
 * @fileoverview Type definitions for tracking data.
 * Shared interfaces for cookies, scripts, storage, network requests, and consent.
 * 
 * NOTE: These types are duplicated in server/src/types/tracking.py.
 * When modifying, ensure both files are updated to maintain consistency.
 */

// ============================================================================
// Core Tracking Data Types
// ============================================================================

/**
 * A cookie captured from the browser context.
 */
export interface TrackedCookie {
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

/**
 * A JavaScript script loaded by the page.
 */
export interface TrackedScript {
  url: string
  domain: string
  timestamp: string
  /** AI-generated description of the script's purpose */
  description?: string
  /** Group ID if this script is part of a grouped category */
  groupId?: string
  /** Whether this script was grouped with similar scripts */
  isGrouped?: boolean
}

/**
 * A group of similar scripts (e.g., application chunks).
 */
export interface ScriptGroup {
  /** Unique identifier for the group */
  id: string
  /** Human-readable name for the group */
  name: string
  /** Description of what this group represents */
  description: string
  /** Number of scripts in this group */
  count: number
  /** Example URLs from the group */
  exampleUrls: string[]
  /** Common domain for the grouped scripts */
  domain: string
}

/**
 * An item stored in localStorage or sessionStorage.
 */
export interface StorageItem {
  key: string
  value: string
  timestamp: string
}

/**
 * An HTTP network request made by the page.
 */
export interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
  statusCode?: number
  postData?: string
  /** Whether this request was made before consent was granted */
  preConsent?: boolean
  /** Number of duplicate GET requests collapsed into this entry */
  duplicateCount?: number
}

// ============================================================================
// Cookie Consent Types
// ============================================================================

/**
 * A cookie category disclosed in a consent dialog.
 */
export interface ConsentCategory {
  name: string
  description: string
  required: boolean
}

/**
 * A third-party partner/vendor listed in a consent dialog.
 */
export interface ConsentPartner {
  name: string
  purpose: string
  dataCollected: string[]
  /** Risk classification (added during analysis) */
  riskLevel?: 'critical' | 'high' | 'medium' | 'low' | 'unknown'
  /** Category of partner business */
  riskCategory?: string
  /** Risk score contribution (0-10) */
  riskScore?: number
  /** Specific privacy concerns */
  concerns?: string[]
  /** Partner privacy policy or homepage URL */
  url?: string
}

/**
 * Detailed information extracted from a cookie consent dialog.
 */
export interface ConsentDetails {
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  hasManageOptions?: boolean
  /** Number of partners claimed by the consent dialog text (e.g. "We and our 1467 partners") */
  claimedPartnerCount?: number | null
}

// ============================================================================
// Summary Findings Types
// ============================================================================

/**
 * Severity/type of a summary finding.
 */
export type SummaryFindingType = 'critical' | 'high' | 'moderate' | 'info' | 'positive'

/**
 * A structured finding from the privacy analysis summary.
 */
export interface SummaryFinding {
  type: SummaryFindingType
  text: string
}

// ============================================================================
// Structured Report Types
// ============================================================================

/** A single identified tracking technology. */
export interface TrackerEntry {
  name: string
  domains: string[]
  cookies: string[]
  storageKeys: string[]
  purpose: string
  url: string
}

/** Categorised tracking technologies found on the page. */
export interface TrackingTechnologiesSection {
  analytics: TrackerEntry[]
  advertising: TrackerEntry[]
  identityResolution: TrackerEntry[]
  socialMedia: TrackerEntry[]
  other: TrackerEntry[]
}

/** A company or service name with an optional URL. */
export interface NamedEntity {
  name: string
  url: string
}

/** A type of data being collected. */
export interface DataCollectionItem {
  category: string
  details: string[]
  risk: 'low' | 'medium' | 'high' | 'critical'
  sensitive: boolean
  sharedWith: NamedEntity[]
}

/** What data the page collects from users. */
export interface DataCollectionSection {
  items: DataCollectionItem[]
}

/** A categorised group of third-party services. */
export interface ThirdPartyGroup {
  category: string
  services: NamedEntity[]
  privacyImpact: string
}

/** Third-party services contacted by the page. */
export interface ThirdPartySection {
  totalDomains: number
  groups: ThirdPartyGroup[]
  summary: string
}

/** A specific factor contributing to risk level. */
export interface RiskFactor {
  description: string
  severity: 'low' | 'medium' | 'high' | 'critical'
}

/** Overall privacy risk assessment. */
export interface PrivacyRiskSection {
  overallRisk: 'low' | 'medium' | 'high' | 'very-high'
  factors: RiskFactor[]
  summary: string
}

/** A group of cookies by purpose. */
export interface CookieGroup {
  category: string
  cookies: string[]
  lifespan: string
  concernLevel: 'none' | 'low' | 'medium' | 'high'
}

/** Analysis of cookies by purpose and risk. */
export interface CookieAnalysisSection {
  total: number
  groups: CookieGroup[]
  concerningCookies: string[]
}

/** Analysis of localStorage and sessionStorage usage. */
export interface StorageAnalysisSection {
  localStorageCount: number
  sessionStorageCount: number
  localStorageConcerns: string[]
  sessionStorageConcerns: string[]
  summary: string
}

/** A discrepancy between consent claims and reality. */
export interface ConsentDiscrepancy {
  claimed: string
  actual: string
  severity: 'low' | 'medium' | 'high' | 'critical'
}

/** Analysis of the consent dialog vs actual tracking. */
export interface ConsentAnalysisSection {
  hasConsentDialog: boolean
  categoriesDisclosed: number
  partnersDisclosed: number
  discrepancies: ConsentDiscrepancy[]
  summary: string
}

/** A key vendor/partner with privacy implications. */
export interface VendorEntry {
  name: string
  role: string
  privacyImpact: string
  url: string
}

/** Key vendors and their privacy implications. */
export interface VendorSection {
  vendors: VendorEntry[]
}

/** A group of recommendations. */
export interface RecommendationGroup {
  category: string
  items: string[]
}

/** Actionable recommendations for users. */
export interface RecommendationsSection {
  groups: RecommendationGroup[]
}

/** Complete structured privacy analysis report. */
export interface StructuredReport {
  trackingTechnologies: TrackingTechnologiesSection
  dataCollection: DataCollectionSection
  thirdPartyServices: ThirdPartySection
  privacyRisk: PrivacyRiskSection
  cookieAnalysis: CookieAnalysisSection
  storageAnalysis: StorageAnalysisSection
  consentAnalysis: ConsentAnalysisSection
  keyVendors: VendorSection
  recommendations: RecommendationsSection
}

// ============================================================================
// Client-Only UI Types
// ============================================================================

/**
 * Screenshot modal display state.
 */
export interface ScreenshotModal {
  src: string
  label: string
}

/**
 * Page-level error information (access denied, server error, etc.)
 */
export interface PageError {
  type: 'access-denied' | 'overlay-blocked' | 'server-error' | null
  message: string
  statusCode: number | null
}

/**
 * Generic error dialog state.
 */
export interface ErrorDialogState {
  title: string
  message: string
}

/**
 * Tab identifiers for the main content area.
 */
export type TabId = 'cookies' | 'storage' | 'network' | 'scripts' | 'analysis' | 'debug-log'
