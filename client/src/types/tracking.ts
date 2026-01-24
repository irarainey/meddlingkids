/**
 * @fileoverview Type definitions for tracking data.
 * Shared interfaces for cookies, scripts, storage, network requests, and consent.
 */

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
export type TabId = 'cookies' | 'storage' | 'network' | 'scripts' | 'analysis' | 'consent' | 'risks'
