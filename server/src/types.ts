// Types for tracking data

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

export interface TrackedScript {
  url: string
  domain: string
  timestamp: string
}

export interface StorageItem {
  key: string
  value: string
  timestamp: string
}

export interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
}

// Cookie consent types

export interface CookieConsentDetection {
  found: boolean
  selector: string | null
  buttonText: string | null
  confidence: 'high' | 'medium' | 'low'
  reason: string
}

export interface ConsentCategory {
  name: string
  description: string
  required: boolean
}

export interface ConsentPartner {
  name: string
  purpose: string
  dataCollected: string[]
}

export interface ConsentDetails {
  hasManageOptions: boolean
  manageOptionsSelector: string | null
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  rawText: string
  expanded?: boolean
}

// Analysis types

export interface AnalysisResult {
  success: boolean
  analysis?: string
  highRisks?: string
  summary?: TrackingSummary
  error?: string
}

export interface DomainData {
  cookies: TrackedCookie[]
  scripts: TrackedScript[]
  networkRequests: NetworkRequest[]
}

export interface DomainBreakdown {
  domain: string
  cookieCount: number
  cookieNames: string[]
  scriptCount: number
  requestCount: number
  requestTypes: string[]
}

export interface TrackingSummary {
  analyzedUrl: string
  totalCookies: number
  totalScripts: number
  totalNetworkRequests: number
  localStorageItems: number
  sessionStorageItems: number
  thirdPartyDomains: string[]
  domainBreakdown: DomainBreakdown[]
  localStorage: { key: string; valuePreview: string }[]
  sessionStorage: { key: string; valuePreview: string }[]
}
