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
    sendProgress(res, 'init', '🚀 Starting browser...', 5)

    // Clear tracked data and set URL for third-party detection
    clearTrackingData()
    setCurrentPageUrl(url)

    sendProgress(res, 'browser', '🌐 Launching headless browser...', 10)

    await launchBrowser(true)

    sendProgress(res, 'navigate', `📄 Loading ${new URL(url).hostname}...`, 20)

    await navigateTo(url, 'networkidle')

    // Wait additional time for dynamic content (ads, trackers) to load
    sendProgress(res, 'wait-content', '⏳ Waiting for dynamic content to load...', 30)
    await waitForTimeout(3000)

    sendProgress(res, 'cookies', '🍪 Capturing initial cookies...', 35)

    await captureCurrentCookies()
    let storage = await captureStorage()

    sendProgress(res, 'screenshot', '📸 Taking initial screenshot...', 40)

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

    sendProgress(res, 'consent-detect', '🔍 Analyzing page for cookie consent banner...', 45)

    const html = await getPageContent()
    const consentDetection = await detectCookieConsent(screenshot, html)

    let consentAccepted = false
    let detectedConsent: CookieConsentDetection | null = null
    let consentDetails: ConsentDetails | null = null

    const page = getPage()

    if (consentDetection.found && consentDetection.selector && page) {
      sendProgress(res, 'consent-found', `✅ Cookie consent found: "${consentDetection.buttonText || 'Accept'}"`, 50)
      detectedConsent = consentDetection

      // Extract detailed consent information BEFORE accepting
      sendProgress(res, 'consent-extract', '📋 Extracting partner and tracking details from consent dialog...', 55)
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
        sendProgress(res, 'consent-expand', '🔎 Expanding cookie preferences to find more details...', 58)
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

      try {
        sendProgress(res, 'consent-click', '👆 Clicking accept button...', 62)

        // Try multiple click strategies
        consentAccepted = await tryClickConsentButton(page, consentDetection.selector, consentDetection.buttonText)

        if (consentAccepted) {
          sendProgress(res, 'consent-wait', '⏳ Waiting for page to update...', 70)
          await waitForTimeout(1000)
          await waitForLoadState('domcontentloaded').catch(() => {})

          sendProgress(res, 'recapture', '🔄 Recapturing tracking data...', 75)
          await captureCurrentCookies()
          storage = await captureStorage()
          screenshot = await takeScreenshot(false)
          base64Screenshot = screenshot.toString('base64')

          // Send screenshot after consent (stage 2)
          sendEvent(res, 'screenshot', {
            screenshot: `data:image/png;base64,${base64Screenshot}`,
            cookies: getTrackedCookies(),
            scripts: getTrackedScripts(),
            networkRequests: getTrackedNetworkRequests(),
            localStorage: storage.localStorage,
            sessionStorage: storage.sessionStorage,
          })

          sendEvent(res, 'consent', {
            detected: true,
            clicked: true,
            details: detectedConsent,
          })
        } else {
          console.log('All consent click strategies failed')
          sendEvent(res, 'consent', {
            detected: true,
            clicked: false,
            details: detectedConsent,
            error: 'Failed to click consent button with all strategies',
          })
        }
      } catch (clickError) {
        console.error('Failed to click cookie consent:', clickError)
        sendEvent(res, 'consent', {
          detected: true,
          clicked: false,
          details: detectedConsent,
          error: 'Failed to click consent button',
        })
      }
    } else {
      sendProgress(res, 'consent-none', 'ℹ️ No cookie consent banner detected', 70)
      sendEvent(res, 'consent', {
        detected: false,
        clicked: false,
        details: null,
        reason: consentDetection.reason,
      })
    }

    sendProgress(res, 'analysis', '🤖 Running AI privacy analysis...', 80)
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
    sendProgress(res, 'complete', '✅ Analysis complete!', 100)

    // Send final complete event
    sendEvent(res, 'complete', {
      success: true,
      message: consentAccepted
        ? 'Tracking analyzed after accepting cookie consent'
        : 'Tracking analyzed',
      analysis: analysisResult.success ? analysisResult.analysis : null,
      highRisks: analysisResult.success ? analysisResult.highRisks : null,
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
