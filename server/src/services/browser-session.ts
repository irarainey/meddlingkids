/**
 * @fileoverview Browser session management for concurrent analysis support.
 * Each BrowserSession instance manages its own isolated browser state,
 * allowing multiple concurrent URL analyses without interference.
 */

import { chromium, type Browser, type Page, type BrowserContext } from 'playwright'
import { extractDomain, isThirdParty } from '../utils/index.js'
import { DEVICE_CONFIGS, type DeviceType } from './device-configs.js'
import { checkForAccessDenied, type AccessDenialResult } from './access-detection.js'
import type { TrackedCookie, TrackedScript, NetworkRequest, StorageItem } from '../types.js'

// Re-export DeviceType for external use
export type { DeviceType } from './device-configs.js'

// ============================================================================
// Constants
// ============================================================================

/** Maximum number of network requests to track (prevents memory issues on ad-heavy sites) */
const MAX_TRACKED_REQUESTS = 5000

/** Maximum number of scripts to track */
const MAX_TRACKED_SCRIPTS = 1000

// ============================================================================
// Types
// ============================================================================

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

// ============================================================================
// BrowserSession Class
// ============================================================================

/**
 * Manages an isolated browser session for a single URL analysis.
 * Each instance has its own browser, context, page, and tracking data,
 * enabling concurrent analyses without interference.
 */
export class BrowserSession {
  /** Active browser instance */
  private browser: Browser | null = null
  /** Browser context (incognito-like session) */
  private context: BrowserContext | null = null
  /** Current page being controlled */
  private page: Page | null = null
  /** URL of the page being analyzed (for third-party detection) */
  private currentPageUrl: string = ''

  /** Cookies captured from the browser context */
  private trackedCookies: TrackedCookie[] = []
  /** Scripts loaded by the page */
  private trackedScripts: TrackedScript[] = []
  /** Network requests made by the page */
  private trackedNetworkRequests: NetworkRequest[] = []

  // ==========================================================================
  // State Getters
  // ==========================================================================

  /**
   * Get the current page being controlled.
   * @returns The Page instance or null if no session is active
   */
  getPage(): Page | null {
    return this.page
  }

  /**
   * Get all cookies captured during the session.
   * @returns Array of tracked cookies (may include duplicates from multiple captures)
   */
  getTrackedCookies(): TrackedCookie[] {
    return this.trackedCookies
  }

  /**
   * Get all scripts detected during the session.
   * @returns Array of script URLs and their domains
   */
  getTrackedScripts(): TrackedScript[] {
    return this.trackedScripts
  }

  /**
   * Get all network requests tracked during the session.
   * @returns Array of network requests with metadata
   */
  getTrackedNetworkRequests(): NetworkRequest[] {
    return this.trackedNetworkRequests
  }

  // ==========================================================================
  // State Management
  // ==========================================================================

  /**
   * Clear all tracked data (cookies, scripts, network requests).
   * Call this before navigating to a new URL for fresh tracking.
   */
  clearTrackingData(): void {
    this.trackedCookies.length = 0
    this.trackedScripts.length = 0
    this.trackedNetworkRequests.length = 0
  }

  /**
   * Set the URL being analyzed for third-party detection.
   * Must be called before navigating to properly classify requests.
   * @param url - The URL about to be visited
   */
  setCurrentPageUrl(url: string): void {
    this.currentPageUrl = url
  }

  // ==========================================================================
  // Browser Lifecycle
  // ==========================================================================

  /**
   * Launch a new headless Chromium browser instance.
   * Creates a completely fresh browser instance with no stored state.
   * Always runs in headless mode for Docker compatibility.
   *
   * @param deviceType - The device/browser to emulate (default: 'ipad')
   */
  async launchBrowser(deviceType: DeviceType = 'ipad'): Promise<void> {
    const deviceConfig = DEVICE_CONFIGS[deviceType]
    
    // Close existing context and browser completely to ensure clean state
    if (this.context) {
      await this.context.close().catch(() => {})
      this.context = null
    }
    if (this.browser) {
      await this.browser.close().catch(() => {})
      this.browser = null
    }
    if (this.page) {
      this.page = null
    }

    // Launch fresh browser with minimal args (always headless for Docker)
    this.browser = await chromium.launch({ 
      headless: true,
      args: [
        '--no-first-run',
        '--no-default-browser-check',
      ]
    })

    // Create fresh context with device emulation
    this.context = await this.browser.newContext({
      ...deviceConfig,
      locale: 'en-GB',
      timezoneId: 'Europe/London',
      javaScriptEnabled: true,
    })

    this.page = await this.context.newPage()

    // Set up request tracking - capture ALL requests (not just unique URLs)
    this.page.on('request', (request) => {
      const resourceType = request.resourceType()
      const requestUrl = request.url()
      const domain = extractDomain(requestUrl)

      // Track scripts separately (deduplicate by URL since we just need to know which scripts loaded)
      if (resourceType === 'script') {
        if (this.trackedScripts.length < MAX_TRACKED_SCRIPTS && !this.trackedScripts.some((s) => s.url === requestUrl)) {
          this.trackedScripts.push({
            url: requestUrl,
            domain,
            timestamp: new Date().toISOString(),
          })
        }
      }

      // Track ALL network requests (with limit to prevent memory issues on ad-heavy sites)
      if (this.trackedNetworkRequests.length < MAX_TRACKED_REQUESTS) {
        const networkRequest: NetworkRequest = {
          url: requestUrl,
          domain,
          method: request.method(),
          resourceType,
          isThirdParty: isThirdParty(requestUrl, this.currentPageUrl),
          timestamp: new Date().toISOString(),
        }

        this.trackedNetworkRequests.push(networkRequest)
      }
    })
    
    // Also track responses to capture status codes
    this.page.on('response', (response) => {
      const requestUrl = response.url()
      // Find the corresponding request and update with response info
      const existingRequest = this.trackedNetworkRequests.find(
        (r) => r.url === requestUrl && !r.statusCode
      )
      if (existingRequest) {
        existingRequest.statusCode = response.status()
      }
    })
  }

  /**
   * Navigate the current page to a URL and wait for it to load.
   * Returns information about the navigation result including status codes.
   *
   * @param url - The URL to navigate to
   * @param waitUntil - When to consider navigation complete
   * @param timeout - Maximum time to wait in milliseconds (default: 90000 for ad-heavy sites)
   * @returns NavigationResult with status information
   * @throws Error if no browser session is active
   */
  async navigateTo(
    url: string, 
    waitUntil: 'load' | 'domcontentloaded' | 'networkidle' = 'networkidle',
    timeout: number = 90000
  ): Promise<NavigationResult> {
    if (!this.page) {
      throw new Error('No browser session active')
    }
    
    try {
      const response = await this.page.goto(url, { waitUntil, timeout })
      
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
   *
   * @param timeout - Maximum time to wait in milliseconds (default: 60000)
   * @returns True if network became idle, false if timed out
   */
  async waitForNetworkIdle(timeout: number = 60000): Promise<boolean> {
    if (!this.page) {
      return false
    }
    
    try {
      await this.page.waitForLoadState('networkidle', { timeout })
      return true
    } catch {
      return false
    }
  }

  /**
   * Check if the current page content indicates access denial or bot blocking.
   *
   * @returns Object indicating if access was denied and the reason
   */
  async checkForAccessDenied(): Promise<AccessDenialResult> {
    if (!this.page) {
      return { denied: false, reason: null }
    }
    return checkForAccessDenied(this.page)
  }

  // ==========================================================================
  // Data Capture Functions
  // ==========================================================================

  /**
   * Capture all cookies from the current browser context.
   */
  async captureCurrentCookies(): Promise<void> {
    if (!this.context) return

    const cookies = await this.context.cookies()

    for (const cookie of cookies) {
      // Check if we already have this cookie (by name and domain)
      const existingIndex = this.trackedCookies.findIndex(
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
        this.trackedCookies[existingIndex] = trackedCookie
      } else {
        // Add new cookie
        this.trackedCookies.push(trackedCookie)
      }
    }
  }

  /**
   * Capture localStorage and sessionStorage contents from the current page.
   *
   * @returns Object with localStorage and sessionStorage arrays
   */
  async captureStorage(): Promise<{ localStorage: StorageItem[]; sessionStorage: StorageItem[] }> {
    if (!this.page) return { localStorage: [], sessionStorage: [] }

    try {
      const storageData = await this.page.evaluate(() => {
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
  async takeScreenshot(fullPage: boolean = false): Promise<Buffer> {
    if (!this.page) {
      throw new Error('No browser session active')
    }
    return this.page.screenshot({ type: 'png', fullPage })
  }

  /**
   * Get the full HTML content of the current page.
   *
   * @returns The page's HTML as a string
   * @throws Error if no browser session is active
   */
  async getPageContent(): Promise<string> {
    if (!this.page) {
      throw new Error('No browser session active')
    }
    return this.page.content()
  }

  // ==========================================================================
  // Page Interaction Helpers
  // ==========================================================================

  /**
   * Wait for a specified amount of time.
   *
   * @param ms - Milliseconds to wait
   * @throws Error if no browser session is active
   */
  async waitForTimeout(ms: number): Promise<void> {
    if (!this.page) {
      throw new Error('No browser session active')
    }
    await this.page.waitForTimeout(ms)
  }

  /**
   * Wait for a specific page load state.
   *
   * @param state - The load state to wait for
   * @throws Error if no browser session is active
   */
  async waitForLoadState(state: 'load' | 'domcontentloaded' | 'networkidle'): Promise<void> {
    if (!this.page) {
      throw new Error('No browser session active')
    }
    await this.page.waitForLoadState(state)
  }

  // ==========================================================================
  // Cleanup Functions
  // ==========================================================================

  /**
   * Close the browser and clean up all resources.
   * Should be called after each analysis to prevent resource leaks.
   * Safe to call multiple times or when no browser is active.
   */
  async close(): Promise<void> {
    // Remove event listeners from page before closing
    if (this.page) {
      this.page.removeAllListeners()
      this.page = null
    }

    // Close context (closes all pages)
    if (this.context) {
      await this.context.close().catch((err) => {
        console.warn('Error closing browser context:', err)
      })
      this.context = null
    }

    // Close browser process
    if (this.browser) {
      await this.browser.close().catch((err) => {
        console.warn('Error closing browser:', err)
      })
      this.browser = null
    }

    // Clear tracking data
    this.clearTrackingData()
  }

  /**
   * Check if a browser session is currently active.
   * @returns True if browser and page are initialized
   */
  isActive(): boolean {
    return this.browser !== null && this.page !== null
  }
}
