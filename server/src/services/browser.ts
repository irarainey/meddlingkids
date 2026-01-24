/**
 * @fileoverview Browser state management and capture utilities.
 * Manages a headless Chromium browser instance via Playwright,
 * tracks cookies, scripts, and network requests during page visits.
 */

import { chromium, type Browser, type Page, type BrowserContext } from 'playwright'
import { extractDomain, isThirdParty } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, NetworkRequest, StorageItem } from '../types.js'

// ============================================================================
// Browser State - Module-level Singletons
// ============================================================================

/** Active browser instance */
let browser: Browser | null = null
/** Browser context (incognito-like session) */
let context: BrowserContext | null = null
/** Current page being controlled */
let page: Page | null = null
/** URL of the page being analyzed (for third-party detection) */
let currentPageUrl: string = ''

// ============================================================================
// Tracking Data Arrays
// ============================================================================

/** Cookies captured from the browser context */
const trackedCookies: TrackedCookie[] = []
/** Scripts loaded by the page */
const trackedScripts: TrackedScript[] = []
/** Network requests made by the page */
const trackedNetworkRequests: NetworkRequest[] = []

// ============================================================================
// State Getters
// ============================================================================

/**
 * Get the current page being controlled.
 * @returns The Page instance or null if no session is active
 */
export function getPage(): Page | null {
  return page
}

/**
 * Get all cookies captured during the session.
 * @returns Array of tracked cookies (may include duplicates from multiple captures)
 */
export function getTrackedCookies(): TrackedCookie[] {
  return trackedCookies
}

/**
 * Get all scripts detected during the session.
 * @returns Array of script URLs and their domains
 */
export function getTrackedScripts(): TrackedScript[] {
  return trackedScripts
}

/**
 * Get all network requests tracked during the session.
 * @returns Array of network requests with metadata
 */
export function getTrackedNetworkRequests(): NetworkRequest[] {
  return trackedNetworkRequests
}

// ============================================================================
// State Management
// ============================================================================

/**
 * Clear all tracked data (cookies, scripts, network requests).
 * Call this before navigating to a new URL for fresh tracking.
 */
export function clearTrackingData(): void {
  trackedCookies.length = 0
  trackedScripts.length = 0
  trackedNetworkRequests.length = 0
}

/**
 * Set the URL being analyzed for third-party detection.
 * Must be called before navigating to properly classify requests.
 * @param url - The URL about to be visited
 */
export function setCurrentPageUrl(url: string): void {
  currentPageUrl = url
}

// ============================================================================
// Browser Lifecycle
// ============================================================================

/** Device type identifiers */
export type DeviceType = 'iphone' | 'ipad' | 'android-phone' | 'android-tablet' | 'windows-chrome' | 'macos-safari'

/** Device configurations for different browser/device combinations */
const DEVICE_CONFIGS: Record<DeviceType, {
  userAgent: string
  viewport: { width: number; height: number }
  deviceScaleFactor: number
  isMobile: boolean
  hasTouch: boolean
}> = {
  'iphone': {
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    viewport: { width: 430, height: 932 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  },
  'ipad': {
    userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    viewport: { width: 1024, height: 1366 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  },
  'android-phone': {
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Mobile Safari/537.36',
    viewport: { width: 412, height: 915 },
    deviceScaleFactor: 2.625,
    isMobile: true,
    hasTouch: true,
  },
  'android-tablet': {
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.90 Safari/537.36',
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  },
  'windows-chrome': {
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    isMobile: false,
    hasTouch: false,
  },
  'macos-safari': {
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    isMobile: false,
    hasTouch: false,
  },
}

/** Currently selected device type */
let currentDeviceType: DeviceType = 'ipad'

/**
 * Launch a new headless Chromium browser instance.
 * Creates a completely fresh browser instance with no stored state.
 *
 * @param headless - Whether to run in headless mode (default: true)
 * @param deviceType - The device/browser to emulate (default: 'ipad')
 */
export async function launchBrowser(headless: boolean = true, deviceType: DeviceType = 'ipad'): Promise<void> {
  currentDeviceType = deviceType
  const deviceConfig = DEVICE_CONFIGS[deviceType]
  
  // Close existing context and browser completely to ensure clean state
  if (context) {
    await context.close().catch(() => {})
    context = null
  }
  if (browser) {
    await browser.close().catch(() => {})
    browser = null
  }
  if (page) {
    page = null
  }

  // Launch fresh browser with minimal args
  browser = await chromium.launch({ 
    headless,
    args: [
      '--no-first-run',
      '--no-default-browser-check',
    ]
  })

  // Create fresh context with device emulation
  context = await browser.newContext({
    ...deviceConfig,
    locale: 'en-GB',
    timezoneId: 'Europe/London',
    javaScriptEnabled: true,
  })

  page = await context.newPage()

  // Set up request tracking - capture ALL requests (not just unique URLs)
  page.on('request', (request) => {
    const resourceType = request.resourceType()
    const requestUrl = request.url()
    const domain = extractDomain(requestUrl)

    // Track scripts separately (deduplicate by URL since we just need to know which scripts loaded)
    if (resourceType === 'script') {
      if (!trackedScripts.some((s) => s.url === requestUrl)) {
        trackedScripts.push({
          url: requestUrl,
          domain,
          timestamp: new Date().toISOString(),
        })
      }
    }

    // Track ALL network requests (don't deduplicate - we want to see every request)
    const networkRequest: NetworkRequest = {
      url: requestUrl,
      domain,
      method: request.method(),
      resourceType,
      isThirdParty: isThirdParty(requestUrl, currentPageUrl),
      timestamp: new Date().toISOString(),
    }

    trackedNetworkRequests.push(networkRequest)
  })
  
  // Also track responses to capture status codes
  page.on('response', (response) => {
    const requestUrl = response.url()
    // Find the corresponding request and update with response info
    const existingRequest = trackedNetworkRequests.find(
      (r) => r.url === requestUrl && !r.statusCode
    )
    if (existingRequest) {
      existingRequest.statusCode = response.status()
    }
  })
}

/**
 * Result of a navigation attempt.
 */
export interface NavigationResult {
  success: boolean
  statusCode: number | null
  statusText: string | null
  isAccessDenied: boolean
  errorMessage: string | null
}

/**
 * Navigate the current page to a URL and wait for it to load.
 * Returns information about the navigation result including status codes.
 *
 * @param url - The URL to navigate to
 * @param waitUntil - When to consider navigation complete:
 *   - 'load': Wait for load event (default browser behavior)
 *   - 'domcontentloaded': Wait for DOMContentLoaded event
 *   - 'networkidle': Wait until network is idle (default, best for tracking)
 * @param timeout - Maximum time to wait in milliseconds (default: 90000 for ad-heavy sites)
 * @returns NavigationResult with status information
 * @throws Error if no browser session is active
 */
export async function navigateTo(
  url: string, 
  waitUntil: 'load' | 'domcontentloaded' | 'networkidle' = 'networkidle',
  timeout: number = 90000
): Promise<NavigationResult> {
  if (!page) {
    throw new Error('No browser session active')
  }
  
  try {
    const response = await page.goto(url, { waitUntil, timeout })
    
    const statusCode = response?.status() ?? null
    const statusText = response?.statusText() ?? null
    
    // Check for HTTP errors
    if (statusCode && statusCode >= 400) {
      const isAccessDenied = statusCode === 403 || statusCode === 401
      return {
        success: false,
        statusCode,
        statusText,
        isAccessDenied,
        errorMessage: isAccessDenied 
          ? `Access denied (${statusCode})` 
          : `Server error (${statusCode}: ${statusText})`,
      }
    }
    
    return {
      success: true,
      statusCode,
      statusText,
      isAccessDenied: false,
      errorMessage: null,
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Navigation failed'
    return {
      success: false,
      statusCode: null,
      statusText: null,
      isAccessDenied: false,
      errorMessage: message,
    }
  }
}

/**
 * Wait for the network to become idle (no requests for 500ms).
 * Useful after initial navigation to ensure all dynamic content has loaded.
 *
 * @param timeout - Maximum time to wait in milliseconds (default: 60000)
 * @returns True if network became idle, false if timed out
 */
export async function waitForNetworkIdle(timeout: number = 60000): Promise<boolean> {
  if (!page) {
    return false
  }
  
  try {
    await page.waitForLoadState('networkidle', { timeout })
    return true
  } catch {
    return false
  }
}

/**
 * Check if the current page content indicates access denial or bot blocking.
 * Looks for common patterns in the page title and body text.
 *
 * @returns Object indicating if access was denied and the reason
 */
export async function checkForAccessDenied(): Promise<{ denied: boolean; reason: string | null }> {
  if (!page) {
    return { denied: false, reason: null }
  }

  try {
    const title = await page.title()
    const titleLower = title.toLowerCase()
    
    // Check title for common access denied patterns
    const blockedTitlePatterns = [
      'access denied',
      'forbidden',
      '403',
      '401',
      'blocked',
      'not allowed',
      'cloudflare',
      'security check',
      'captcha',
      'robot',
      'bot detection',
      'please verify',
      'are you human',
      'just a moment',
      'checking your browser',
      'ddos protection',
      'attention required',
    ]
    
    for (const pattern of blockedTitlePatterns) {
      if (titleLower.includes(pattern)) {
        return { denied: true, reason: `Page title indicates blocking: "${title}"` }
      }
    }

    // Check visible body text for common access denied messages
    const bodyText = await page.evaluate(() => {
      const body = document.body
      return body ? body.innerText.substring(0, 2000).toLowerCase() : ''
    })

    const blockedBodyPatterns = [
      'access denied',
      'access to this page has been denied',
      'you have been blocked',
      'this request was blocked',
      'automated access',
      'bot traffic',
      'enable javascript and cookies',
      'please complete the security check',
      'checking if the site connection is secure',
      'verify you are human',
      'we have detected unusual activity',
      'your ip has been blocked',
      'rate limit exceeded',
    ]

    for (const pattern of blockedBodyPatterns) {
      if (bodyText.includes(pattern)) {
        return { denied: true, reason: `Page content indicates blocking: "${pattern}"` }
      }
    }

    return { denied: false, reason: null }
  } catch {
    return { denied: false, reason: null }
  }
}

// ============================================================================
// Data Capture Functions
// ============================================================================

/**
 * Capture all cookies from the current browser context.
 * Updates or adds cookies to the trackedCookies array.
 * Call this after page interactions to get the latest cookies.
 */
export async function captureCurrentCookies(): Promise<void> {
  if (!context) return

  const cookies = await context.cookies()

  for (const cookie of cookies) {
    // Check if we already have this cookie (by name and domain)
    const existingIndex = trackedCookies.findIndex(
      (c) => c.name === cookie.name && c.domain === cookie.domain
    )

    const trackedCookie: TrackedCookie = {
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      expires: cookie.expires,
      httpOnly: cookie.httpOnly,
      secure: cookie.secure,
      sameSite: cookie.sameSite,
      timestamp: new Date().toISOString(),
    }

    if (existingIndex >= 0) {
      // Update existing cookie
      trackedCookies[existingIndex] = trackedCookie
    } else {
      // Add new cookie
      trackedCookies.push(trackedCookie)
    }
  }
}

/**
 * Capture localStorage and sessionStorage contents from the current page.
 * Executes JavaScript in the page context to read storage.
 *
 * @returns Object with localStorage and sessionStorage arrays
 */
export async function captureStorage(): Promise<{ localStorage: StorageItem[]; sessionStorage: StorageItem[] }> {
  if (!page) return { localStorage: [], sessionStorage: [] }

  try {
    const storageData = await page.evaluate(() => {
      const getStorageItems = (storage: Storage) => {
        const items: { key: string; value: string }[] = []
        for (let i = 0; i < storage.length; i++) {
          const key = storage.key(i)
          if (key) {
            items.push({ key, value: storage.getItem(key) || '' })
          }
        }
        return items
      }

      return {
        localStorage: getStorageItems(window.localStorage),
        sessionStorage: getStorageItems(window.sessionStorage),
      }
    })

    const timestamp = new Date().toISOString()

    return {
      localStorage: storageData.localStorage.map((item) => ({ ...item, timestamp })),
      sessionStorage: storageData.sessionStorage.map((item) => ({ ...item, timestamp })),
    }
  } catch {
    return { localStorage: [], sessionStorage: [] }
  }
}

/**
 * Take a PNG screenshot of the current page.
 *
 * @param fullPage - Whether to capture the entire scrollable page (default: false)
 * @returns Buffer containing the PNG image data
 * @throws Error if no browser session is active
 */
export async function takeScreenshot(fullPage: boolean = false): Promise<Buffer> {
  if (!page) {
    throw new Error('No browser session active')
  }
  return page.screenshot({ type: 'png', fullPage })
}

/**
 * Get the full HTML content of the current page.
 *
 * @returns The page's HTML as a string
 * @throws Error if no browser session is active
 */
export async function getPageContent(): Promise<string> {
  if (!page) {
    throw new Error('No browser session active')
  }
  return page.content()
}

// ============================================================================
// Page Interaction Helpers
// ============================================================================

/**
 * Wait for a specified amount of time.
 * Useful for waiting for animations or async operations.
 *
 * @param ms - Milliseconds to wait
 * @throws Error if no browser session is active
 */
export async function waitForTimeout(ms: number): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.waitForTimeout(ms)
}

/**
 * Wait for a specific page load state.
 *
 * @param state - The load state to wait for:
 *   - 'load': Wait for load event
 *   - 'domcontentloaded': Wait for DOMContentLoaded
 *   - 'networkidle': Wait until no network activity for 500ms
 * @throws Error if no browser session is active
 */
export async function waitForLoadState(state: 'load' | 'domcontentloaded' | 'networkidle'): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.waitForLoadState(state)
}

