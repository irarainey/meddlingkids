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

    sendProgress(res, 'browser', 'Launching browser...', 10)

    await launchBrowser(true)

    sendProgress(res, 'navigate', `Loading ${new URL(url).hostname}...`, 15)

    // First, navigate and wait for DOM to be ready (fast)
    await navigateTo(url, 'domcontentloaded', 30000)
    
    sendProgress(res, 'wait-network', 'Waiting for page to finish loading...', 20)
    
    // Now wait for network to become idle (captures all trackers/ads)
    // This may take a while on ad-heavy sites
    const networkIdleResult = await waitForNetworkIdle(90000)
    
    if (!networkIdleResult) {
      console.log('Network did not reach idle state within timeout, continuing with captured data')
      sendProgress(res, 'wait-partial', 'Page still loading, continuing...', 28)
    }

    // Wait additional time for any final dynamic content
    sendProgress(res, 'wait-content', 'Capturing page content...', 30)
    await waitForTimeout(3000)

    sendProgress(res, 'cookies', 'Collecting tracking data...', 35)

    await captureCurrentCookies()
    let storage = await captureStorage()

    sendProgress(res, 'screenshot', 'Taking screenshot...', 40)

    let screenshot = await takeScreenshot(false)
    let base64Screenshot = screenshot.toString('base64')

    // Send initial screenshot (stage 1)
    sendEvent(res, 'screenshot', {
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })

    sendProgress(res, 'consent-detect', 'Analyzing page...', 45)

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
      const html = await getPageContent()
      screenshot = await takeScreenshot(false)
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

      // Extract detailed consent information BEFORE accepting (only for cookie consent)
      if (consentDetection.overlayType === 'cookie-consent') {
        sendProgress(res, 'consent-extract', 'Extracting consent details...', progressBase + 1)
        consentDetails = await extractConsentDetails(page, screenshot)

        // Send consent details event
        sendEvent(res, 'consentDetails', {
          categories: consentDetails.categories,
          partners: consentDetails.partners,
          purposes: consentDetails.purposes,
          hasManageOptions: consentDetails.hasManageOptions,
        })

        // If there's a manage options button, try clicking it to get more details
        if (consentDetails.hasManageOptions && consentDetails.manageOptionsSelector) {
          sendProgress(res, 'consent-expand', 'Expanding preferences...', progressBase + 2)
          try {
            // Convert jQuery-style :contains() selectors to Playwright text selectors
            let selector = consentDetails.manageOptionsSelector
            const containsMatch = selector.match(/:contains\(["'](.+?)["']\)/)

            if (containsMatch) {
              // Extract the text and use Playwright's text locator instead
              const buttonText = containsMatch[1]
              await page.getByRole('button', { name: buttonText }).first().click({ timeout: 3000 })
            } else {
              await page.click(selector, { timeout: 3000 })
            }
            await waitForTimeout(500)

            // Take new screenshot and extract more details
            const expandedScreenshot = await takeScreenshot(true)
            const expandedDetails = await extractConsentDetails(page, expandedScreenshot)

            // Merge the details
            consentDetails = {
              ...consentDetails,
              categories: [...consentDetails.categories, ...expandedDetails.categories].filter(
                (c, i, arr) => arr.findIndex((x) => x.name === c.name) === i
              ),
              partners: [...consentDetails.partners, ...expandedDetails.partners].filter(
                (p, i, arr) => arr.findIndex((x) => x.name === p.name) === i
              ),
              purposes: [...new Set([...consentDetails.purposes, ...expandedDetails.purposes])],
              rawText: consentDetails.rawText + '\n\n' + expandedDetails.rawText,
            }

            // Send updated consent details
            sendEvent(res, 'consentDetails', {
              categories: consentDetails.categories,
              partners: consentDetails.partners,
              purposes: consentDetails.purposes,
              expanded: true,
            })

            console.log('Expanded consent details:', {
              categories: consentDetails.categories.length,
              partners: consentDetails.partners.length,
            })
          } catch (expandError) {
            console.log('Could not expand cookie preferences:', expandError)
          }
        }
      }

      // Try to click the dismiss/accept button
      try {
        sendProgress(res, `overlay-${overlayCount}-click`, 'Dismissing overlay...', progressBase + 3)

        const clicked = await tryClickConsentButton(page, consentDetection.selector, consentDetection.buttonText)

        if (clicked) {
          sendProgress(res, `overlay-${overlayCount}-wait`, 'Waiting for page to update...', progressBase + 4)
          await waitForTimeout(1500)
          await waitForLoadState('domcontentloaded').catch(() => {})

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

    sendProgress(res, 'analysis', 'Running privacy analysis...', 80)
    console.log('Starting tracking analysis...')

    const analysisResult = await runTrackingAnalysis(
      getTrackedCookies(),
      storage.localStorage,
      storage.sessionStorage,
      getTrackedNetworkRequests(),
      getTrackedScripts(),
      url,
      consentDetails
    )

    console.log('Analysis result:', analysisResult.success ? 'Success' : analysisResult.error)
    sendProgress(res, 'complete', 'Analysis complete!', 100)

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
