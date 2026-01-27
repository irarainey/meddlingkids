/**
 * @fileoverview Streaming URL analysis endpoint with progress updates.
 * Provides Server-Sent Events (SSE) endpoint for real-time progress during
 * page loading, consent handling, and tracking analysis.
 */

import type { Request, Response } from 'express'
import {
  launchBrowser,
  closeBrowser,
  navigateTo,
  setCurrentPageUrl,
  clearTrackingData,
  captureCurrentCookies,
  captureStorage,
  takeScreenshot,
  waitForTimeout,
  waitForNetworkIdle,
  checkForAccessDenied,
  getPage,
  getTrackedCookies,
  getTrackedScripts,
  getTrackedNetworkRequests,
} from '../services/browser.js'
import { runTrackingAnalysis } from '../services/analysis.js'
import { analyzeScripts } from '../services/script-analysis.js'
import { validateOpenAIConfig } from '../services/openai.js'
import { getErrorMessage } from '../utils/index.js'
import { sendEvent, sendProgress, handleOverlays } from './analyze-helpers.js'

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
 * - device: Device type to emulate (optional, default: 'ipad')
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

  // Set up SSE headers first so we can send error events
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.setHeader('Access-Control-Allow-Origin', '*')

  // Validate OpenAI configuration before starting analysis
  const configError = validateOpenAIConfig()
  if (configError) {
    sendEvent(res, 'error', { error: configError })
    res.end()
    return
  }

  // Validate device type
  const validDevices = ['iphone', 'ipad', 'android-phone', 'android-tablet', 'windows-chrome', 'macos-safari']
  const deviceType = validDevices.includes(device) ? device : 'ipad'

  if (!url) {
    sendEvent(res, 'error', { error: 'URL is required' })
    res.end()
    return
  }

  try {
    // ========================================================================
    // Phase 1: Browser Setup and Navigation
    // ========================================================================
    
    sendProgress(res, 'init', 'Starting investigation...', 5)

    clearTrackingData()
    setCurrentPageUrl(url)

    sendProgress(res, 'browser', 'Launching headless browser...', 8)
    await launchBrowser(deviceType as import('../services/browser.js').DeviceType)

    const hostname = new URL(url).hostname
    sendProgress(res, 'navigate', `Connecting to ${hostname}...`, 12)

    // Navigate and wait for DOM to be ready
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
    
    // ========================================================================
    // Phase 2: Wait for Page Load and Check Access
    // ========================================================================
    
    sendProgress(res, 'wait-network', `Loading ${hostname}...`, 18)
    
    // Wait for network to settle (shorter timeout for ad-heavy sites)
    const networkIdleResult = await waitForNetworkIdle(15000)
    
    if (!networkIdleResult) {
      console.log('Network still active (normal for ad-heavy sites), continuing...')
      sendProgress(res, 'wait-continue', 'Page loaded, capturing trackers...', 28)
    } else {
      sendProgress(res, 'wait-done', 'Page fully loaded', 28)
    }

    await waitForTimeout(1000)
    
    // Check for access denied in page content (bot detection, Cloudflare, etc.)
    const accessCheck = await checkForAccessDenied()
    if (accessCheck.denied) {
      console.log('Access denied detected:', accessCheck.reason)
      
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

    // ========================================================================
    // Phase 3: Initial Data Capture
    // ========================================================================
    
    sendProgress(res, 'cookies', 'Capturing cookies...', 32)
    await captureCurrentCookies()
    
    sendProgress(res, 'storage', 'Capturing storage data...', 35)
    let storage = await captureStorage()

    // Wait for consent dialogs to appear
    sendProgress(res, 'consent-wait', 'Waiting for consent dialogs...', 37)
    await waitForTimeout(2000)

    sendProgress(res, 'screenshot', 'Taking screenshot...', 38)
    const screenshot = await takeScreenshot(false)
    const base64Screenshot = screenshot.toString('base64')

    const cookieCount = getTrackedCookies().length
    const scriptCount = getTrackedScripts().length
    const requestCount = getTrackedNetworkRequests().length
    
    sendProgress(res, 'captured', `Found ${cookieCount} cookies, ${scriptCount} scripts, ${requestCount} requests`, 42)

    // Send initial screenshot
    sendEvent(res, 'screenshot', {
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })

    // ========================================================================
    // Phase 4: Overlay Detection and Handling
    // ========================================================================
    
    sendProgress(res, 'consent-detect', 'Checking for consent dialogs...', 45)

    const page = getPage()
    let consentDetails = null
    let overlayCount = 0

    if (page) {
      const overlayResult = await handleOverlays(page, res, screenshot)
      consentDetails = overlayResult.consentDetails
      overlayCount = overlayResult.overlayCount
      storage = overlayResult.finalStorage
    }

    // ========================================================================
    // Phase 5: AI Analysis
    // ========================================================================
    
    sendProgress(res, 'analysis-prep', 'Preparing tracking data for analysis...', 75)
    console.log('Starting tracking analysis...')

    const finalCookieCount = getTrackedCookies().length
    const finalScriptCount = getTrackedScripts().length
    
    sendProgress(res, 'analysis-start', `Analyzing ${finalCookieCount} cookies and ${finalScriptCount} scripts...`, 78)

    // Run script analysis and main analysis in parallel
    const [analyzedScripts, analysisResult] = await Promise.all([
      // Script analysis
      (async () => {
        const scripts = await analyzeScripts(
          getTrackedScripts(), 
          20,
          (current, total) => {
            sendProgress(res, 'script-analysis', `Analyzing script ${current} of ${total}...`, 80 + Math.floor((current / total) * 10))
          }
        )
        console.log(`Script analysis complete: ${scripts.length} scripts analyzed`)
        return scripts
      })(),
      
      // Main tracking analysis
      runTrackingAnalysis(
        getTrackedCookies(),
        storage.localStorage,
        storage.sessionStorage,
        getTrackedNetworkRequests(),
        getTrackedScripts(),
        url,
        consentDetails
      )
    ])

    if (analysisResult.success) {
      sendProgress(res, 'analysis-score', 'Calculating privacy score...', 95)
    }

    // ========================================================================
    // Phase 6: Complete
    // ========================================================================
    
    console.log('Analysis result:', analysisResult.success ? 'Success' : analysisResult.error)
    sendProgress(res, 'complete', 'Investigation complete!', 100)

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
      scripts: analyzedScripts,
    })

    res.end()
  } catch (error) {
    sendEvent(res, 'error', { error: getErrorMessage(error) })
    res.end()
  } finally {
    // Always clean up browser resources to prevent memory leaks
    await closeBrowser().catch((err) => {
      console.warn('Error during browser cleanup:', err)
    })
  }
}
