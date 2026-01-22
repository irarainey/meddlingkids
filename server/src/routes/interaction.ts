// Interaction endpoints (click, type, state)

import type { Request, Response } from 'express'
import {
  getPage,
  getContext,
  captureCurrentCookies,
  captureStorage,
  takeScreenshot,
  waitForTimeout,
  clickAt,
  clickSelector,
  fillText,
  getTrackedCookies,
  getTrackedScripts,
  getTrackedNetworkRequests,
} from '../services/browser.js'

// Click at specific coordinates
export async function clickHandler(req: Request, res: Response): Promise<void> {
  const { x, y } = req.body

  const page = getPage()
  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await clickAt(x, y)
    await waitForTimeout(1000) // Wait for any animations/requests

    // Capture cookies after interaction
    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await takeScreenshot(true)
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
}

// Click on element by selector
export async function clickSelectorHandler(req: Request, res: Response): Promise<void> {
  const { selector } = req.body

  const page = getPage()
  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await clickSelector(selector, 5000)
    await waitForTimeout(1000)

    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await takeScreenshot(true)
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
}

// Type text into an element
export async function typeHandler(req: Request, res: Response): Promise<void> {
  const { selector, text } = req.body

  const page = getPage()
  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await fillText(selector, text)

    const storage = await captureStorage()
    const screenshot = await takeScreenshot(true)
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
}

// Get current state (screenshot, cookies, scripts)
export async function stateHandler(_req: Request, res: Response): Promise<void> {
  const page = getPage()
  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await takeScreenshot(true)
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: getTrackedCookies(),
      scripts: getTrackedScripts(),
      networkRequests: getTrackedNetworkRequests(),
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
}

// Get only cookies
export async function cookiesHandler(_req: Request, res: Response): Promise<void> {
  const context = getContext()
  if (!context) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await captureCurrentCookies()
    res.json({ cookies: getTrackedCookies() })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
}

// Get only scripts
export function scriptsHandler(_req: Request, res: Response): void {
  res.json({ scripts: getTrackedScripts() })
}
