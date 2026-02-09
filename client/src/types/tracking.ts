/**
 * @fileoverview Type definitions for tracking data.
 * Shared interfaces for cookies, scripts, storage, network requests, and consent.
 * 
 * NOTE: These types are duplicated in server-python/src/types/tracking.py.
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
}

/**
 * Detailed information extracted from a cookie consent dialog.
 */
export interface ConsentDetails {
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  hasManageOptions?: boolean
  expanded?: boolean
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
 * Tab identifiers for the main content area.
 */
export type TabId = 'cookies' | 'storage' | 'network' | 'scripts' | 'analysis' | 'consent' | 'summary'
