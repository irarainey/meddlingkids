/**
 * @fileoverview Consent button click strategies.
 * Provides multiple fallback strategies for clicking "Accept All" buttons
 * on cookie consent banners, including iframe handling.
 */

import type { Page } from 'playwright'

/** Common text patterns found on accept/agree buttons */
const COMMON_ACCEPT_PATTERNS = [
  'Accept All',
  'Accept all',
  'Accept Cookies',
  'Accept cookies',
  'Allow All',
  'Allow all',
  'I Accept',
  'I agree',
  'Agree',
  'OK',
  'Got it',
  'Continue',
  'Consent',
  'Yes',
  'Allow',
]

/** URL patterns that indicate a frame contains consent UI */
const CONSENT_IFRAME_PATTERNS = [
  'consent',
  'cookie',
  'privacy',
  'gdpr',
  'onetrust',
  'cookiebot',
  'trustarc',
  'quantcast',
]

/**
 * Try multiple strategies to click a consent accept button.
 * Attempts various selectors and patterns in order of likelihood,
 * including checking iframes for consent managers like OneTrust or CookieBot.
 *
 * @param page - Playwright Page instance
 * @param selector - CSS selector suggested by LLM detection (may be null)
 * @param buttonText - Text of the button suggested by LLM (may be null)
 * @returns True if any strategy succeeded in clicking, false otherwise
 */
export async function tryClickConsentButton(
  page: Page,
  selector: string | null,
  buttonText: string | null
): Promise<boolean> {
  const strategies: Array<{ name: string; fn: () => Promise<void> }> = []

  // Strategy 1: Direct selector click
  if (selector) {
    // Convert jQuery-style :contains() to Playwright text selector
    const containsMatch = selector.match(/:contains\(["'](.+?)["']\)/)
    if (containsMatch) {
      const text = containsMatch[1]
      strategies.push({
        name: `text selector "${text}"`,
        fn: () => page.getByText(text, { exact: false }).first().click({ timeout: 3000 }),
      })
    } else {
      strategies.push({
        name: `CSS selector "${selector}"`,
        fn: () => page.click(selector, { timeout: 3000 }),
      })
    }
  }

  // Strategy 2: Button role with text
  if (buttonText) {
    strategies.push({
      name: `button role "${buttonText}"`,
      fn: () => page.getByRole('button', { name: buttonText }).click({ timeout: 3000 }),
    })
    // Also try with exact: false for partial matches
    strategies.push({
      name: `button role partial "${buttonText}"`,
      fn: () =>
        page
          .getByRole('button', { name: new RegExp(buttonText, 'i') })
          .first()
          .click({ timeout: 3000 }),
    })
  }

  // Strategy 3: Common accept button patterns
  for (const pattern of COMMON_ACCEPT_PATTERNS) {
    strategies.push({
      name: `common pattern "${pattern}"`,
      fn: () => page.getByRole('button', { name: pattern }).click({ timeout: 2000 }),
    })
  }

  // Strategy 4: Check iframes for consent banners
  strategies.push({
    name: 'iframe consent',
    fn: () => tryClickInConsentIframes(page),
  })

  // Try each strategy in order
  for (const strategy of strategies) {
    try {
      console.log(`Trying consent click strategy: ${strategy.name}`)
      await strategy.fn()
      console.log(`Success with strategy: ${strategy.name}`)
      return true
    } catch (error) {
      console.log(`Strategy "${strategy.name}" failed:`, error instanceof Error ? error.message : error)
    }
  }

  return false
}

/**
 * Try clicking consent buttons within iframes.
 * Many consent management platforms (OneTrust, CookieBot, TrustArc)
 * render their UI in iframes.
 *
 * @param page - Playwright Page instance
 * @throws Error if no consent iframe found or click fails
 */
async function tryClickInConsentIframes(page: Page): Promise<void> {
  const frames = page.frames()

  for (const frame of frames) {
    if (frame === page.mainFrame()) continue

    const frameUrl = frame.url().toLowerCase()

    // Check if this frame matches consent iframe patterns
    const isConsentFrame = CONSENT_IFRAME_PATTERNS.some((pattern) => frameUrl.includes(pattern))

    if (isConsentFrame) {
      // Try clicking accept buttons in this frame
      for (const pattern of ['Accept All', 'Accept', 'Allow All', 'I Accept', 'Agree', 'OK']) {
        try {
          await frame.getByRole('button', { name: pattern }).click({ timeout: 2000 })
          return // Success
        } catch {
          // Try next pattern
        }
      }
    }
  }

  throw new Error('No consent iframe found')
}
