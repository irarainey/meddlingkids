/**
 * @fileoverview Consent button click strategies.
 * Prioritizes LLM-suggested selectors, checking main page and iframes.
 */

import type { Page, Frame } from 'playwright'

/**
 * Click a consent/dismiss button using LLM-provided selector and text.
 * Checks both main page and iframes since consent managers often use iframes.
 *
 * @param page - Playwright Page instance
 * @param selector - CSS selector suggested by LLM detection
 * @param buttonText - Text of the button suggested by LLM
 * @returns True if click succeeded, false otherwise
 */
export async function tryClickConsentButton(
  page: Page,
  selector: string | null,
  buttonText: string | null
): Promise<boolean> {
  // Phase 1: Try LLM suggestions on main page (quick - 1.5s timeout)
  console.log(`Attempting to click: selector="${selector}", buttonText="${buttonText}"`)
  
  const mainResult = await tryClickInFrame(page.mainFrame(), selector, buttonText, 1500)
  if (mainResult) {
    console.log('Success on main page')
    return true
  }

  // Phase 2: Try LLM suggestions in ALL iframes (consent managers often use iframes)
  const frames = page.frames()
  for (const frame of frames) {
    if (frame === page.mainFrame()) continue
    
    const frameUrl = frame.url()
    console.log(`Checking iframe: ${frameUrl.substring(0, 80)}...`)
    
    const iframeResult = await tryClickInFrame(frame, selector, buttonText, 1500)
    if (iframeResult) {
      console.log(`Success in iframe: ${frameUrl.substring(0, 50)}`)
      return true
    }
  }

  // Phase 3: Last resort - try generic close buttons on main page
  const closeResult = await tryCloseButtons(page)
  if (closeResult) return true

  console.log('All click strategies failed')
  return false
}

/**
 * Try clicking in a specific frame using LLM-provided selector and text.
 * Tries selector first, then button role, then link role, then text.
 */
async function tryClickInFrame(
  frame: Frame,
  selector: string | null,
  buttonText: string | null,
  timeout: number
): Promise<boolean> {
  // Strategy 1: Direct CSS selector
  if (selector) {
    // Handle jQuery-style :contains() selectors
    const containsMatch = selector.match(/:contains\(["'](.+?)["']\)/)
    const actualSelector = containsMatch ? null : selector
    const textFromSelector = containsMatch ? containsMatch[1] : null
    
    if (actualSelector) {
      try {
        await frame.locator(actualSelector).first().click({ timeout })
        return true
      } catch {
        // Continue to next strategy
      }
    }
    
    if (textFromSelector) {
      try {
        await frame.getByText(textFromSelector, { exact: false }).first().click({ timeout })
        return true
      } catch {
        // Continue to next strategy
      }
    }
  }

  // Strategy 2: Button/link/text with buttonText
  if (buttonText) {
    // Try as button
    try {
      await frame.getByRole('button', { name: buttonText }).first().click({ timeout })
      return true
    } catch {
      // Continue
    }

    // Try as link
    try {
      await frame.getByRole('link', { name: buttonText }).first().click({ timeout })
      return true
    } catch {
      // Continue
    }

    // Try as any text element
    try {
      await frame.getByText(buttonText, { exact: true }).first().click({ timeout })
      return true
    } catch {
      // Continue
    }
    
    // Try partial text match
    try {
      await frame.getByText(buttonText, { exact: false }).first().click({ timeout })
      return true
    } catch {
      // Continue
    }
  }

  return false
}

/**
 * Try common close button patterns as a last resort.
 */
async function tryCloseButtons(page: Page): Promise<boolean> {
  const closeSelectors = [
    '[aria-label*="close" i]',
    '[aria-label*="dismiss" i]',
    'button[class*="close"]',
    '[class*="modal-close"]',
  ]

  for (const sel of closeSelectors) {
    try {
      console.log(`Trying close button: "${sel}"`)
      await page.locator(sel).first().click({ timeout: 1000 })
      console.log(`Success with close button`)
      return true
    } catch {
      // Try next
    }
  }

  return false
}
