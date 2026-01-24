/**
 * @fileoverview Streaming URL analysis endpoint with progress updates.
 * Provides Server-Sent Events (SSE) endpoint for real-time progress during
 * page loading, consent handling, and tracking analysis.
 */

import type { Request, Response } from 'express'
import {
  launchBrowser,
  navigateTo,
  setCurrentPageUrl,
  clearTrackingData,
  captureCurrentCookies,
  captureStorage,
  takeScreenshot,
  getPageContent,
  waitForTimeout,
  waitForLoadState,
  waitForNetworkIdle,
  checkForAccessDenied,
  getPage,
  getTrackedCookies,
  getTrackedScripts,
  getTrackedNetworkRequests,
} from '../services/browser.js'
import { detectCookieConsent } from '../services/consent-detection.js'
import { extractConsentDetails } from '../services/consent-extraction.js'
import { tryClickConsentButton } from '../services/consent-click.js'
import { runTrackingAnalysis } from '../services/analysis.js'
import { getErrorMessage } from '../utils/index.js'
import type { ConsentDetails, CookieConsentDetection } from '../types.js'

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
function sendEvent(res: Response, type: string, data: object): void {
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
function sendProgress(res: Response, step: string, message: string, progress: number): void {
  sendEvent(res, 'progress', { step, message, progress })
}

// ============================================================================
// Main Streaming Handler
// ============================================================================

/**
 * GET /api/open-browser-stream - Analyze tracking on a URL with streaming progress.
 *
 * Opens a headless browser, navigates to the URL, detects and handles cookie
 * consent banners, captures tracking data, and runs AI analysis. Progress
 * is streamed via Server-Sent Events (SSE).
 *
 * Query parameters:
 * - url: The URL to analyze (required)
 *
 * SSE Events emitted:
 * - progress: { step, message, progress } - Progress updates
 * - screenshot: { screenshot, cookies, scripts, networkRequests, storage } - Page captures
 * - consent: { detected, clicked, details } - Consent banner handling result
 * - consentDetails: { categories, partners, purposes } - Extracted consent info
 * - complete: { success, analysis, highRisks, ... } - Final results
 * - error: { error } - If something fails
 */
export async function analyzeUrlStreamHandler(req: Request, res: Response): Promise<void> {
  const url = req.query.url as string
  const device = (req.query.device as string) || 'ipad'

  // Validate device type
  const validDevices = ['iphone', 'ipad', 'android-phone', 'android-tablet', 'windows-chrome', 'macos-safari']
  const deviceType = validDevices.includes(device) ? device : 'ipad'

  if (!url) {
    res.status(400).json({ error: 'URL is required' })
    return
  }

  // Set up SSE headers
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.setHeader('Access-Control-Allow-Origin', '*')

  try {
    sendProgress(res, 'init', 'Starting investigation...', 5)

    // Clear tracked data and set URL for third-party detection
    clearTrackingData()
    setCurrentPageUrl(url)

    sendProgress(res, 'browser', 'Launching headless browser...', 8)

    await launchBrowser(true, deviceType as import('../services/browser.js').DeviceType)

    const hostname = new URL(url).hostname
    sendProgress(res, 'navigate', `Connecting to ${hostname}...`, 12)

    // Navigate and wait for DOM to be ready (fast initial load)
    const navResult = await navigateTo(url, 'domcontentloaded', 30000)
    
    // Check for HTTP-level errors
    if (!navResult.success) {
      const errorType = navResult.isAccessDenied ? 'access-denied' : 'server-error'
      sendEvent(res, 'pageError', {
        type: errorType,
        statusCode: navResult.statusCode,
        message: navResult.errorMessage,
        isAccessDenied: navResult.isAccessDenied,
      })
      sendProgress(res, 'error', navResult.errorMessage || 'Failed to load page', 100)
      res.end()
      return
    }
    
    sendProgress(res, 'wait-network', `Loading ${hostname}...`, 18)
    
    // Wait for network to settle - use a shorter timeout since ad-heavy sites
    // like Daily Mail never truly reach "idle" due to continuous ad refreshes.
    // 15 seconds is enough to capture most trackers without waiting forever.
    const networkIdleResult = await waitForNetworkIdle(15000)
    
    if (!networkIdleResult) {
      // Network didn't idle - this is NORMAL for ad-heavy sites
      // We've still captured the trackers that loaded in the first 15 seconds
      console.log('Network still active (normal for ad-heavy sites), continuing...')
      sendProgress(res, 'wait-continue', 'Page loaded, capturing trackers...', 28)
    } else {
      sendProgress(res, 'wait-done', 'Page fully loaded', 28)
    }

    // Brief pause to let any final scripts execute
    await waitForTimeout(1000)
    
    // Check for access denied in page content (bot detection, Cloudflare, etc.)
    const accessCheck = await checkForAccessDenied()
    if (accessCheck.denied) {
      console.log('Access denied detected:', accessCheck.reason)
      
      // Still take a screenshot to show the user what happened
      const screenshot = await takeScreenshot(false)
      const base64Screenshot = screenshot.toString('base64')
      
      sendEvent(res, 'screenshot', {
        screenshot: `data:image/png;base64,${base64Screenshot}`,
        cookies: getTrackedCookies(),
        scripts: getTrackedScripts(),
        networkRequests: getTrackedNetworkRequests(),
        localStorage: [],
        sessionStorage: [],
      })
      
      sendEvent(res, 'pageError', {
        type: 'access-denied',
        statusCode: navResult.statusCode,
        message: 'Access denied - this site has bot protection that blocked our request',
        isAccessDenied: true,
        reason: accessCheck.reason,
      })
      sendProgress(res, 'blocked', 'Site blocked access', 100)
      res.end()
      return
    }

    sendProgress(res, 'cookies', 'Capturing cookies...', 32)
    await captureCurrentCookies()
    
    sendProgress(res, 'storage', 'Capturing storage data...', 35)
    let storage = await captureStorage()

    // Wait for consent dialogs to appear - they often load asynchronously
    sendProgress(res, 'consent-wait', 'Waiting for consent dialogs...', 37)
    await waitForTimeout(2000)

    sendProgress(res, 'screenshot', 'Taking screenshot...', 38)
    let screenshot = await takeScreenshot(false)
    let base64Screenshot = screenshot.toString('base64')

    // Count what we've found so far
    const cookieCount = getTrackedCookies().length
    const scriptCount = getTrackedScripts().length
    const requestCount = getTrackedNetworkRequests().length
    
    sendProgress(res, 'captured', `Found ${cookieCount} cookies, ${scriptCount} scripts, ${requestCount} requests`, 42)

    // Send initial screenshot (stage 1)
    sendEvent(res, 'screenshot', {
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })

    sendProgress(res, 'consent-detect', 'Checking for consent dialogs...', 45)

    let consentDetails: ConsentDetails | null = null
    const page = getPage()
    
    // Track all overlays dismissed for the final event
    const dismissedOverlays: CookieConsentDetection[] = []
    let overlayCount = 0
    const MAX_OVERLAYS = 5 // Safety limit to prevent infinite loops

    // Get appropriate message based on overlay type
    const getOverlayMessage = (type: string | null, buttonText: string | null): string => {
      const btn = buttonText || 'Dismiss'
      switch (type) {
        case 'cookie-consent': return `Cookie consent detected`
        case 'sign-in': return `Sign-in prompt detected`
        case 'newsletter': return `Newsletter popup detected`
        case 'paywall': return `Paywall detected`
        case 'age-verification': return `Age verification detected`
        default: return `Overlay detected`
      }
    }

    // Loop to handle multiple overlays (cookie consent, then sign-in wall, then newsletter, etc.)
    while (page && overlayCount < MAX_OVERLAYS) {
      // Only fetch new screenshot/HTML on first iteration or after a successful click
      // (screenshot variable is reused from previous capture)
      const html = await getPageContent()
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
      const progressBase = 45 + (overlayCount * 5) // Progress increases with each overlay
      
      sendProgress(res, `overlay-${overlayCount}-found`, getOverlayMessage(consentDetection.overlayType, consentDetection.buttonText), progressBase)
      dismissedOverlays.push(consentDetection)

      // Extract detailed consent information BEFORE accepting (only for first cookie consent)
      if (consentDetection.overlayType === 'cookie-consent' && !consentDetails) {
        sendProgress(res, 'consent-extract', 'Extracting consent details...', progressBase + 1)
        consentDetails = await extractConsentDetails(page, screenshot)

        // Send consent details event
        sendEvent(res, 'consentDetails', {
          categories: consentDetails.categories,
          partners: consentDetails.partners,
          purposes: consentDetails.purposes,
          hasManageOptions: consentDetails.hasManageOptions,
        })

        // Skip the "expand preferences" step - it's slow and often doesn't add value
        // The initial extraction usually captures the key information
      }

      // Try to click the dismiss/accept button
      try {
        sendProgress(res, `overlay-${overlayCount}-click`, 'Dismissing overlay...', progressBase + 3)

        const clicked = await tryClickConsentButton(page, consentDetection.selector, consentDetection.buttonText)

        if (clicked) {
          sendProgress(res, `overlay-${overlayCount}-wait`, 'Waiting for page to update...', progressBase + 4)
          
          // Wait for DOM to settle - use shorter wait with domcontentloaded as backup
          await Promise.race([
            waitForTimeout(800),
            waitForLoadState('domcontentloaded').catch(() => {})
          ])

          // Recapture data and take screenshot after this overlay
          sendProgress(res, `overlay-${overlayCount}-capture`, 'Capturing page state...', progressBase + 5)
          await captureCurrentCookies()
          storage = await captureStorage()
          screenshot = await takeScreenshot(false)
          base64Screenshot = screenshot.toString('base64')

          // Send screenshot after this overlay (captures each state change)
          sendEvent(res, 'screenshot', {
            screenshot: `data:image/png;base64,${base64Screenshot}`,
            cookies: getTrackedCookies(),
            scripts: getTrackedScripts(),
            networkRequests: getTrackedNetworkRequests(),
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
          break // Stop trying if we can't click
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
        break // Stop trying on error
      }
    }

    if (overlayCount >= MAX_OVERLAYS) {
      console.log('Reached maximum overlay limit, stopping detection')
      sendProgress(res, 'overlays-limit', 'Maximum overlay limit reached', 70)
    }

    sendProgress(res, 'analysis-prep', 'Preparing tracking data for analysis...', 75)
    console.log('Starting tracking analysis...')

    // Update counts after any overlay dismissals
    const finalCookieCount = getTrackedCookies().length
    const finalRequestCount = getTrackedNetworkRequests().length
    
    sendProgress(res, 'analysis-start', `Analyzing ${finalCookieCount} cookies and ${finalRequestCount} requests...`, 80)

    const analysisResult = await runTrackingAnalysis(
      getTrackedCookies(),
      storage.localStorage,
      storage.sessionStorage,
      getTrackedNetworkRequests(),
      getTrackedScripts(),
      url,
      consentDetails
    )

    if (analysisResult.success) {
      sendProgress(res, 'analysis-score', 'Calculating privacy score...', 95)
    }

    console.log('Analysis result:', analysisResult.success ? 'Success' : analysisResult.error)
    sendProgress(res, 'complete', 'Investigation complete!', 100)

    // Send final complete event
    sendEvent(res, 'complete', {
      success: true,
      message: overlayCount > 0
        ? 'Tracking analyzed after dismissing overlays'
        : 'Tracking analyzed',
      analysis: analysisResult.success ? analysisResult.analysis : null,
      highRisks: analysisResult.success ? analysisResult.highRisks : null,
      privacyScore: analysisResult.success ? analysisResult.privacyScore : null,
      privacySummary: analysisResult.success ? analysisResult.privacySummary : null,
      analysisSummary: analysisResult.success ? analysisResult.summary : null,
      analysisError: analysisResult.success ? null : analysisResult.error,
      consentDetails: consentDetails,
    })

    res.end()
  } catch (error) {
    sendEvent(res, 'error', { error: getErrorMessage(error) })
    res.end()
  }
}
