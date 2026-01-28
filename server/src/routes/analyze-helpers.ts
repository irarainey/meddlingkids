/**
 * @fileoverview Helper functions for the streaming analysis handler.
 * Extracts reusable logic for overlay handling, screenshot capture, etc.
 * Updated to use BrowserSession for concurrent request support.
 */

import type { Response } from 'express'
import type { Page } from 'playwright'
import type { BrowserSession } from '../services/browser-session.js'
import { detectCookieConsent } from '../services/consent-detection.js'
import { extractConsentDetails } from '../services/consent-extraction.js'
import { tryClickConsentButton } from '../services/consent-click.js'
import type { ConsentDetails, CookieConsentDetection, StorageItem } from '../types.js'

// ============================================================================
// SSE Helper Functions
// ============================================================================

/**
 * Send a named event to the SSE stream.
 *
 * @param res - Express response object (SSE stream)
 * @param type - Event type name
 * @param data - Data object to serialize as JSON
 */
export function sendEvent(res: Response, type: string, data: object): void {
  res.write(`event: ${type}\n`)
  res.write(`data: ${JSON.stringify(data)}\n\n`)
}

/**
 * Send a progress event to the SSE stream.
 *
 * @param res - Express response object (SSE stream)
 * @param step - Current step identifier (e.g., 'init', 'navigate', 'consent')
 * @param message - Human-readable progress message
 * @param progress - Progress percentage (0-100)
 */
export function sendProgress(res: Response, step: string, message: string, progress: number): void {
  sendEvent(res, 'progress', { step, message, progress })
}

// ============================================================================
// Overlay Handling
// ============================================================================

/** Maximum overlays to handle in sequence */
const MAX_OVERLAYS = 5

/**
 * Get appropriate message based on overlay type.
 */
function getOverlayMessage(type: string | null): string {
  switch (type) {
    case 'cookie-consent': return 'Cookie consent detected'
    case 'sign-in': return 'Sign-in prompt detected'
    case 'newsletter': return 'Newsletter popup detected'
    case 'paywall': return 'Paywall detected'
    case 'age-verification': return 'Age verification detected'
    default: return 'Overlay detected'
  }
}

/** Result of handling overlays */
export interface OverlayHandlingResult {
  overlayCount: number
  dismissedOverlays: CookieConsentDetection[]
  consentDetails: ConsentDetails | null
  finalScreenshot: Buffer
  finalStorage: { localStorage: StorageItem[]; sessionStorage: StorageItem[] }
}

/**
 * Handle multiple overlays (cookie consent, sign-in walls, etc.) in sequence.
 * Captures consent details from the first cookie consent dialog.
 *
 * @param session - Browser session instance
 * @param page - Playwright page instance
 * @param res - Express response for SSE
 * @param initialScreenshot - Screenshot taken before overlay detection
 * @returns Result with overlay count and consent details
 */
export async function handleOverlays(
  session: BrowserSession,
  page: Page,
  res: Response,
  initialScreenshot: Buffer
): Promise<OverlayHandlingResult> {
  let consentDetails: ConsentDetails | null = null
  const dismissedOverlays: CookieConsentDetection[] = []
  let overlayCount = 0
  let screenshot = initialScreenshot
  let storage = await session.captureStorage()

  while (overlayCount < MAX_OVERLAYS) {
    // Get fresh HTML for detection
    const html = await session.getPageContent()
    const consentDetection = await detectCookieConsent(screenshot, html)

    if (!consentDetection.found || !consentDetection.selector) {
      if (overlayCount === 0) {
        sendProgress(res, 'consent-none', 'No overlay detected', 70)
        sendEvent(res, 'consent', {
          detected: false,
          clicked: false,
          details: null,
          reason: consentDetection.reason,
        })
      } else {
        sendProgress(res, 'overlays-done', `Dismissed ${overlayCount} overlay(s)`, 70)
      }
      break
    }

    overlayCount++
    const progressBase = 45 + (overlayCount * 5)
    
    sendProgress(res, `overlay-${overlayCount}-found`, getOverlayMessage(consentDetection.overlayType), progressBase)
    dismissedOverlays.push(consentDetection)

    // Extract detailed consent information BEFORE accepting (only for first cookie consent)
    if (consentDetection.overlayType === 'cookie-consent' && !consentDetails) {
      sendProgress(res, 'consent-extract', 'Extracting consent details...', progressBase + 1)
      consentDetails = await extractConsentDetails(page, screenshot)

      sendEvent(res, 'consentDetails', {
        categories: consentDetails.categories,
        partners: consentDetails.partners,
        purposes: consentDetails.purposes,
        hasManageOptions: consentDetails.hasManageOptions,
      })
    }

    // Try to click the dismiss/accept button
    try {
      sendProgress(res, `overlay-${overlayCount}-click`, 'Dismissing overlay...', progressBase + 3)

      const clicked = await tryClickConsentButton(page, consentDetection.selector, consentDetection.buttonText)

      if (clicked) {
        sendProgress(res, `overlay-${overlayCount}-wait`, 'Waiting for page to update...', progressBase + 4)
        
        // Wait for DOM to settle
        await Promise.race([
          session.waitForTimeout(800),
          session.waitForLoadState('domcontentloaded').catch(() => {})
        ])

        // Recapture data and take screenshot after this overlay
        sendProgress(res, `overlay-${overlayCount}-capture`, 'Capturing page state...', progressBase + 5)
        await session.captureCurrentCookies()
        storage = await session.captureStorage()
        screenshot = await session.takeScreenshot(false)
        const base64Screenshot = screenshot.toString('base64')

        // Send screenshot after this overlay
        sendEvent(res, 'screenshot', {
          screenshot: `data:image/png;base64,${base64Screenshot}`,
          cookies: session.getTrackedCookies(),
          scripts: session.getTrackedScripts(),
          networkRequests: session.getTrackedNetworkRequests(),
          localStorage: storage.localStorage,
          sessionStorage: storage.sessionStorage,
          overlayDismissed: consentDetection.overlayType,
        })

        sendEvent(res, 'consent', {
          detected: true,
          clicked: true,
          details: consentDetection,
          overlayNumber: overlayCount,
        })
        
        console.log(`Overlay ${overlayCount} (${consentDetection.overlayType}) dismissed successfully`)
      } else {
        console.log(`Failed to click overlay ${overlayCount}, stopping overlay detection`)
        sendEvent(res, 'consent', {
          detected: true,
          clicked: false,
          details: consentDetection,
          error: 'Failed to click dismiss button',
          overlayNumber: overlayCount,
        })
        break
      }
    } catch (clickError) {
      console.error(`Failed to click overlay ${overlayCount}:`, clickError)
      sendEvent(res, 'consent', {
        detected: true,
        clicked: false,
        details: consentDetection,
        error: 'Failed to click dismiss button',
        overlayNumber: overlayCount,
      })
      break
    }
  }

  if (overlayCount >= MAX_OVERLAYS) {
    console.log('Reached maximum overlay limit, stopping detection')
    sendProgress(res, 'overlays-limit', 'Maximum overlay limit reached', 70)
  }

  return {
    overlayCount,
    dismissedOverlays,
    consentDetails,
    finalScreenshot: screenshot,
    finalStorage: storage,
  }
}
