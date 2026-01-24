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

/** iPad Pro 12.9" with Chrome - realistic tablet user agent and settings */
const MOBILE_DEVICE_CONFIG = {
  userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/122.0.6261.89 Mobile/15E148 Safari/604.1',
  viewport: { width: 1024, height: 1366 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
}

/**
 * Launch a new headless Chromium browser instance.
 * Configured to appear as Chrome on an iPhone for realistic behavior.
 * Sets up request interception to track scripts and network activity.
 * Closes any existing browser instance first.
 *
 * @param headless - Whether to run in headless mode (default: true)
 */
export async function launchBrowser(headless: boolean = true): Promise<void> {
  // Close existing browser if open
  if (browser) {
    await browser.close()
  }

  browser = await chromium.launch({ headless })

  context = await browser.newContext({
    ...MOBILE_DEVICE_CONFIG,
    storageState: undefined,
    ignoreHTTPSErrors: false,
    locale: 'en-GB',
    timezoneId: 'Europe/London',
  })

  page = await context.newPage()

  // Set up request tracking
  page.on('request', (request) => {
    const resourceType = request.resourceType()
    const requestUrl = request.url()
    const domain = extractDomain(requestUrl)

    // Track scripts separately
    if (resourceType === 'script') {
      if (!trackedScripts.some((s) => s.url === requestUrl)) {
        trackedScripts.push({
          url: requestUrl,
          domain,
          timestamp: new Date().toISOString(),
        })
      }
    }

    // Track all network requests
    const networkRequest: NetworkRequest = {
      url: requestUrl,
      domain,
      method: request.method(),
      resourceType,
      isThirdParty: isThirdParty(requestUrl, currentPageUrl),
      timestamp: new Date().toISOString(),
    }

    if (!trackedNetworkRequests.some((r) => r.url === requestUrl)) {
      trackedNetworkRequests.push(networkRequest)
    }
  })
}

/**
 * Navigate the current page to a URL and wait for it to load.
 * Uses an extended timeout for ad-heavy sites that take longer to reach network idle.
 *
 * @param url - The URL to navigate to
 * @param waitUntil - When to consider navigation complete:
 *   - 'load': Wait for load event (default browser behavior)
 *   - 'domcontentloaded': Wait for DOMContentLoaded event
 *   - 'networkidle': Wait until network is idle (default, best for tracking)
 * @param timeout - Maximum time to wait in milliseconds (default: 90000 for ad-heavy sites)
 * @throws Error if no browser session is active
 */
export async function navigateTo(
  url: string, 
  waitUntil: 'load' | 'domcontentloaded' | 'networkidle' = 'networkidle',
  timeout: number = 90000
): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  
  await page.goto(url, { waitUntil, timeout })
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

