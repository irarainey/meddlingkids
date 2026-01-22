// Browser state management and capture utilities

import { chromium, type Browser, type Page, type BrowserContext } from 'playwright'
import { extractDomain, isThirdParty } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, NetworkRequest, StorageItem } from '../types.js'

// Browser state - module-level singletons
let browser: Browser | null = null
let context: BrowserContext | null = null
let page: Page | null = null
let pageUrl: string = ''

// Tracking data arrays
const trackedCookies: TrackedCookie[] = []
const trackedScripts: TrackedScript[] = []
const trackedNetworkRequests: NetworkRequest[] = []

// Getters for state
export function getBrowser(): Browser | null {
  return browser
}

export function getContext(): BrowserContext | null {
  return context
}

export function getPage(): Page | null {
  return page
}

export function getPageUrl(): string {
  return pageUrl
}

export function getTrackedCookies(): TrackedCookie[] {
  return trackedCookies
}

export function getTrackedScripts(): TrackedScript[] {
  return trackedScripts
}

export function getTrackedNetworkRequests(): NetworkRequest[] {
  return trackedNetworkRequests
}

// Clear all tracking data
export function clearTrackingData(): void {
  trackedCookies.length = 0
  trackedScripts.length = 0
  trackedNetworkRequests.length = 0
}

// Set page URL for third-party detection
export function setPageUrl(url: string): void {
  pageUrl = url
}

// Launch a new browser instance
export async function launchBrowser(headless: boolean = true): Promise<void> {
  // Close existing browser if open
  if (browser) {
    await browser.close()
  }

  browser = await chromium.launch({ headless })

  context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    storageState: undefined,
    ignoreHTTPSErrors: false,
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
      isThirdParty: isThirdParty(requestUrl, pageUrl),
      timestamp: new Date().toISOString(),
    }

    if (!trackedNetworkRequests.some((r) => r.url === requestUrl)) {
      trackedNetworkRequests.push(networkRequest)
    }
  })
}

// Navigate to a URL
export async function navigateTo(url: string, waitUntil: 'load' | 'domcontentloaded' | 'networkidle' = 'networkidle'): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.goto(url, { waitUntil })
}

// Close the browser
export async function closeBrowser(): Promise<void> {
  if (browser) {
    await browser.close()
    browser = null
    context = null
    page = null
  }
}

// Capture current cookies from browser context
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

// Capture localStorage and sessionStorage
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

// Take a screenshot
export async function takeScreenshot(fullPage: boolean = false): Promise<Buffer> {
  if (!page) {
    throw new Error('No browser session active')
  }
  return page.screenshot({ type: 'png', fullPage })
}

// Get page HTML content
export async function getPageContent(): Promise<string> {
  if (!page) {
    throw new Error('No browser session active')
  }
  return page.content()
}

// Wait for timeout
export async function waitForTimeout(ms: number): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.waitForTimeout(ms)
}

// Wait for load state
export async function waitForLoadState(state: 'load' | 'domcontentloaded' | 'networkidle'): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.waitForLoadState(state)
}

// Click at coordinates
export async function clickAt(x: number, y: number): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.mouse.click(x, y)
}

// Click on element by selector
export async function clickSelector(selector: string, timeout: number = 5000): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.click(selector, { timeout })
}

// Fill text in an element
export async function fillText(selector: string, text: string): Promise<void> {
  if (!page) {
    throw new Error('No browser session active')
  }
  await page.fill(selector, text)
}
