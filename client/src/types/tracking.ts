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
 * AI-generated explanation of what a cookie does.
 */
export interface CookieInfo {
  description: string
  setBy: string
  purpose: string
  riskLevel: 'none' | 'low' | 'medium' | 'high' | 'critical'
  privacyNote: string
}

/**
 * AI-generated explanation of what a storage key does.
 */
export interface StorageInfo {
  description: string
  setBy: string
  purpose: string
  riskLevel: 'none' | 'low' | 'medium' | 'high' | 'critical'
  privacyNote: string
}

/**
 * A matched IAB TCF v2.2 purpose with full metadata.
 */
export interface TcfPurpose {
  id: number
  name: string
  description: string
  riskLevel: string
  lawfulBases: string[]
  notes: string
  category: 'purpose' | 'special-purpose' | 'feature' | 'special-feature'
}

/**
 * Result of mapping consent purpose strings to TCF purposes.
 */
export interface TcfLookupResult {
  matched: TcfPurpose[]
  unmatched: string[]
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
  /** Domain of the frame that initiated the request */
  initiatorDomain?: string
  /** Previous URL in a redirect chain */
  redirectedFromUrl?: string
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
  /** Privacy policy page URL */
  privacyUrl?: string
}

/**
 * Detailed information extracted from a cookie consent dialog.
 */
/**
 * Decoded IAB TCF v2 TC String data.
 *
 * Contains machine-readable consent signals extracted from
 * the euconsent-v2 cookie set by TCF-compliant CMPs.
 */
export interface TcStringData {
  version: number
  created: string
  lastUpdated: string
  cmpId: number
  cmpVersion: number
  consentScreen: number
  consentLanguage: string
  vendorListVersion: number
  tcfPolicyVersion: number
  isServiceSpecific: boolean
  useNonStandardStacks: boolean
  publisherCountryCode: string
  purposeConsents: number[]
  purposeLegitimateInterests: number[]
  specialFeatureOptIns: number[]
  vendorConsents: number[]
  vendorLegitimateInterests: number[]
  vendorConsentCount: number
  vendorLiCount: number
  totalPurposesConsented: number
  rawString: string
  /** Resolved vendor names for consent IDs (from IAB GVL) */
  resolvedVendorConsents?: ResolvedVendor[]
  /** Number of consent vendor IDs not found in the IAB GVL */
  unresolvedVendorConsentCount?: number
  /** Resolved vendor names for legitimate interest IDs (from IAB GVL) */
  resolvedVendorLi?: ResolvedVendor[]
  /** Number of LI vendor IDs not found in the IAB GVL */
  unresolvedVendorLiCount?: number
}

/**
 * A vendor ID resolved to a company name via the IAB GVL
 * or Google ATP provider list, optionally enriched with
 * classification metadata from the partner databases.
 */
export interface ResolvedVendor {
  id: number
  name: string
  /** Company homepage URL from partner databases */
  url?: string
  /** Privacy policy URL from the IAB GVL */
  policy_url?: string
  /** Classification category (e.g. "Ad Network", "Data Broker") */
  category?: string
  /** Privacy concerns from partner databases */
  concerns?: string[]
  /** IAB TCF purpose IDs declared by this vendor */
  purposes?: number[]
}

/**
 * A Google ATP provider ID resolved to a name and policy URL,
 * optionally enriched with classification metadata.
 */
export interface ResolvedAcProvider {
  id: number
  name: string
  policy_url: string
  /** Company homepage URL from partner databases */
  url?: string
  /** Classification category (e.g. "Ad Network", "Analytics") */
  category?: string
  /** Privacy concerns from partner databases */
  concerns?: string[]
}

/**
 * Decoded Google Additional Consent Mode (AC) String data.
 *
 * The AC String lists non-IAB ad-tech providers that received
 * consent through a Google-certified CMP.  It supplements the
 * TC String for vendors not in the IAB Global Vendor List.
 */
export interface AcStringData {
  /** AC spec version (currently always 1) */
  version: number
  /** Google Ad Technology Provider IDs that received consent */
  vendorIds: number[]
  /** Number of consented ATP vendors */
  vendorCount: number
  /** Raw AC String for reference */
  rawString: string
  /** Resolved provider names and policy URLs (from Google ATP list) */
  resolvedProviders?: ResolvedAcProvider[]
  /** Number of provider IDs not found in the Google ATP list */
  unresolvedProviderCount?: number
}

/**
 * A purpose consent/LI signal decoded from the TC String,
 * cross-referenced against the consent dialog text.
 */
export interface TcPurposeSignal {
  id: number
  name: string
  description: string
  riskLevel: string
  consented: boolean
  legitimateInterest: boolean
  disclosedInDialog: boolean
}

/**
 * A validation finding from TC String cross-referencing.
 */
export interface TcValidationFinding {
  severity: 'critical' | 'high' | 'moderate' | 'info'
  category: string
  title: string
  detail: string
}

/**
 * TC String validation result — cross-references TC String
 * consent signals against consent dialog content.
 */
export interface TcValidationResult {
  purposeSignals: TcPurposeSignal[]
  vendorConsentCount: number
  vendorLiCount: number
  claimedPartnerCount: number | null
  vendorCountMismatch: boolean
  /** Non-IAB vendor count from Google AC String (null if not present) */
  acVendorCount: number | null
  specialFeatures: string[]
  findings: TcValidationFinding[]
}

export interface ConsentDetails {
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  hasManageOptions?: boolean
  /** Number of partners claimed by the consent dialog text (e.g. "We and our 1467 partners") */
  claimedPartnerCount?: number | null
  /** Detected consent management platform name (e.g. "Sourcepoint", "OneTrust") */
  consentPlatform?: string | null
  /** Decoded TC String data from the euconsent-v2 cookie (populated after consent acceptance) */
  tcStringData?: TcStringData | null
  /** TC String validation results — cross-referenced against dialog purposes */
  tcValidation?: TcValidationResult | null
  /** Decoded AC String data from the addtl_consent cookie (Google Additional Consent Mode) */
  acStringData?: AcStringData | null
}

// ============================================================================
// Decoded Privacy Cookie Types
// ============================================================================

/** USP String (CCPA) decoded from the usprivacy cookie */
export interface UspStringData {
  version: number
  noticeGiven: boolean
  optedOut: boolean
  lspaCovered: boolean
  noticeLabel: string
  optOutLabel: string
  lspaLabel: string
  rawString: string
}

/** GPP section info */
export interface GppSection {
  id: number
  name: string
}

/** GPP String (Global Privacy Platform) decoded from __gpp / __gpp_sid */
export interface GppStringData {
  version?: number
  segmentCount: number
  sectionIds: number[]
  sections: GppSection[]
  rawString: string
}

/** Google Analytics _ga cookie decoded data */
export interface GoogleAnalyticsData {
  clientId: string
  firstVisitTimestamp: number | null
  firstVisit: string | null
  rawValue: string
}

/** Facebook _fbp browser ID decoded data */
export interface FbpData {
  browserId: string
  createdTimestamp: number
  created: string | null
  rawValue: string
}

/** Facebook _fbc click ID decoded data */
export interface FbcData {
  fbclid: string
  clickTimestamp: number
  clicked: string | null
  rawValue: string
}

/** Facebook pixel cookies combined */
export interface FacebookPixelData {
  fbp?: FbpData | null
  fbc?: FbcData | null
}

/** Google Ads _gcl_au conversion linker */
export interface GclAuData {
  version: string
  createdTimestamp: number
  created: string | null
  rawValue: string
}

/** Google Ads _gcl_aw click cookie */
export interface GclAwData {
  gclid: string
  clickTimestamp: number
  clicked: string | null
  rawValue: string
}

/** Google Ads cookies combined */
export interface GoogleAdsData {
  gclAu?: GclAuData | null
  gclAw?: GclAwData | null
}

/** OneTrust consent category */
export interface OneTrustCategory {
  id: string
  name: string
  consented: boolean
}

/** OneTrust OptanonConsent decoded data */
export interface OneTrustData {
  categories: OneTrustCategory[]
  datestamp: string | null
  isGpcApplied: boolean
  consentId: string | null
  rawValue: string
}

/** Cookiebot consent category */
export interface CookiebotCategory {
  name: string
  consented: boolean
}

/** Cookiebot CookieConsent decoded data */
export interface CookiebotData {
  categories: CookiebotCategory[]
  stamp: string | null
  utc: string | null
  rawValue: string
}

/** Google SOCS consent cookie decoded data */
export interface GoogleSocsData {
  consentMode: string
  modeChar: string
  rawValue: string
}

/** GPC / DNT detection result */
export interface GpcDntData {
  gpcEnabled: boolean
  dntEnabled: boolean
}

/** Container for all decoded privacy cookies */
export interface DecodedCookies {
  uspString?: UspStringData | null
  gppString?: GppStringData | null
  googleAnalytics?: GoogleAnalyticsData | null
  facebookPixel?: FacebookPixelData | null
  googleAds?: GoogleAdsData | null
  oneTrust?: OneTrustData | null
  cookiebot?: CookiebotData | null
  googleSocs?: GoogleSocsData | null
  gpcDnt?: GpcDntData | null
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
  /** Plain-language "what you agreed to" digest for non-technical users */
  plainLanguageSummary?: string
  /** Deterministic note about the user's privacy rights under the detected framework */
  userRightsNote?: string
  /** Detected consent management platform name (e.g. "Sourcepoint", "OneTrust") */
  consentPlatform?: string | null
  /** Base URL of the consent management platform vendor */
  consentPlatformUrl?: string | null
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

/** A specific social media privacy risk. */
export interface SocialMediaRisk {
  platform: string
  risk: string
  severity: 'low' | 'medium' | 'high' | 'critical'
}

/** Analysis of social media tracking implications. */
export interface SocialMediaImplicationsSection {
  platformsDetected: string[]
  identityLinkingRisk: 'none' | 'low' | 'medium' | 'high'
  risks: SocialMediaRisk[]
  summary: string
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
  socialMediaImplications: SocialMediaImplicationsSection
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
export type TabId = 'cookies' | 'storage' | 'network' | 'tracker-graph' | 'scripts' | 'summary' | 'consent'
