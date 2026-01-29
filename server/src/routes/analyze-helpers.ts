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
import { getPartnerRiskSummary, classifyPartnerByPatternSync } from '../services/partner-classification.js'
import { createLogger } from '../utils/index.js'
import type { ConsentDetails, CookieConsentDetection, StorageItem } from '../types.js'

const log = createLogger('Overlays')

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
    case 'cookie-consent': return 'Cookie consent overlay detected'
    case 'sign-in': return 'Sign-in overlay detected'
    case 'newsletter': return 'Newsletter overlay detected'
    case 'paywall': return 'Paywall overlay detected'
    case 'age-verification': return 'Age verification overlay detected'
    default: return 'Page overlay detected'
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

  log.info('Starting overlay detection loop', { maxOverlays: MAX_OVERLAYS })

  while (overlayCount < MAX_OVERLAYS) {
    // Get fresh HTML for detection
    log.startTimer(`overlay-detect-${overlayCount + 1}`)
    const html = await session.getPageContent()
    const consentDetection = await detectCookieConsent(screenshot, html)
    log.endTimer(`overlay-detect-${overlayCount + 1}`, 'Overlay detection complete')

    if (!consentDetection.found || !consentDetection.selector) {
      if (overlayCount === 0) {
        log.info('No overlay detected')
        sendProgress(res, 'overlay-none', 'No page overlays detected', 70)
        sendEvent(res, 'consent', {
          detected: false,
          clicked: false,
          details: null,
          reason: consentDetection.reason,
        })
      } else {
        log.success(`Dismissed ${overlayCount} overlay(s), no more found`)
        sendProgress(res, 'overlays-done', `Dismissed ${overlayCount} overlay(s)`, 70)
      }
      break
    }

    overlayCount++
    const progressBase = 45 + (overlayCount * 5)
    
    log.info(`Overlay ${overlayCount} found`, { type: consentDetection.overlayType, selector: consentDetection.selector, buttonText: consentDetection.buttonText, confidence: consentDetection.confidence })
    sendProgress(res, `overlay-${overlayCount}-found`, getOverlayMessage(consentDetection.overlayType), progressBase)
    dismissedOverlays.push(consentDetection)

    // Extract detailed consent information BEFORE accepting (only for first cookie consent)
    if (consentDetection.overlayType === 'cookie-consent' && !consentDetails) {
      log.startTimer('consent-extraction')
      sendProgress(res, 'overlay-extract', 'Extracting overlay details...', progressBase + 1)
      consentDetails = await extractConsentDetails(page, screenshot)
      log.endTimer('consent-extraction', 'Consent details extracted')
      log.info('Consent details', { categories: consentDetails.categories.length, partners: consentDetails.partners.length, purposes: consentDetails.purposes.length })

      // Enrich partners with risk classification
      if (consentDetails.partners.length > 0) {
        log.startTimer('partner-classification')
        sendProgress(res, 'partner-classify', 'Analyzing partner risk levels...', progressBase + 2)
        
        const riskSummary = getPartnerRiskSummary(consentDetails.partners)
        log.info('Partner risk summary', { 
          critical: riskSummary.criticalCount, 
          high: riskSummary.highCount,
          totalRisk: riskSummary.totalRiskScore 
        })
        
        // Enrich each partner with classification
        for (const partner of consentDetails.partners) {
          const classification = classifyPartnerByPatternSync(partner)
          if (classification) {
            partner.riskLevel = classification.riskLevel
            partner.riskCategory = classification.category
            partner.riskScore = classification.riskScore
            partner.concerns = classification.concerns
          } else {
            partner.riskLevel = 'unknown'
            partner.riskScore = 3 // Default moderate risk for unknowns
          }
        }
        log.endTimer('partner-classification', 'Partner classification complete')
      }

      sendEvent(res, 'consentDetails', {
        categories: consentDetails.categories,
        partners: consentDetails.partners,
        purposes: consentDetails.purposes,
        hasManageOptions: consentDetails.hasManageOptions,
      })
    }

    // Try to click the dismiss/accept button
    try {
      log.startTimer(`overlay-click-${overlayCount}`)
      sendProgress(res, `overlay-${overlayCount}-click`, 'Dismissing overlay...', progressBase + 3)

      const clicked = await tryClickConsentButton(page, consentDetection.selector, consentDetection.buttonText)
      log.endTimer(`overlay-click-${overlayCount}`, clicked ? 'Click succeeded' : 'Click failed')

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

        log.success(`Overlay ${overlayCount} (${consentDetection.overlayType}) dismissed successfully`)

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
      } else {
        log.warn(`Failed to click overlay ${overlayCount}, stopping overlay detection`)
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
      log.error(`Failed to click overlay ${overlayCount}`, { error: clickError instanceof Error ? clickError.message : String(clickError) })
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
    log.warn('Reached maximum overlay limit, stopping detection')
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
