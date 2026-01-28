/**
 * @fileoverview Access denial and bot blocking detection utilities.
 * Checks page content for patterns that indicate bot blocking or access denial.
 */

import type { Page } from 'playwright'

// ============================================================================
// Types
// ============================================================================

/**
 * Result of an access denial check.
 */
export interface AccessDenialResult {
  denied: boolean
  reason: string | null
}

// ============================================================================
// Detection Patterns
// ============================================================================

/** Page title patterns that indicate blocking */
const BLOCKED_TITLE_PATTERNS = [
  'access denied',
  'forbidden',
  '403',
  '401',
  'blocked',
  'not allowed',
  'cloudflare',
  'security check',
  'captcha',
  'robot',
  'bot detection',
  'please verify',
  'are you human',
  'just a moment',
  'checking your browser',
  'ddos protection',
  'attention required',
]

/** Page body text patterns that indicate blocking */
const BLOCKED_BODY_PATTERNS = [
  'access denied',
  'access to this page has been denied',
  'you have been blocked',
  'this request was blocked',
  'automated access',
  'bot traffic',
  'enable javascript and cookies',
  'please complete the security check',
  'checking if the site connection is secure',
  'verify you are human',
  'we have detected unusual activity',
  'your ip has been blocked',
  'rate limit exceeded',
]

// ============================================================================
// Detection Functions
// ============================================================================

/**
 * Check if the current page content indicates access denial or bot blocking.
 *
 * @param page - The Playwright page to check
 * @returns Object indicating if access was denied and the reason
 */
export async function checkForAccessDenied(page: Page): Promise<AccessDenialResult> {
  try {
    const title = await page.title()
    const titleLower = title.toLowerCase()
    
    // Check title for common access denied patterns
    for (const pattern of BLOCKED_TITLE_PATTERNS) {
      if (titleLower.includes(pattern)) {
        return { denied: true, reason: `Page title indicates blocking: "${title}"` }
      }
    }

    // Check visible body text for common access denied messages
    const bodyText = await page.evaluate(() => {
      const body = document.body
      return body ? body.innerText.substring(0, 2000).toLowerCase() : ''
    })

    for (const pattern of BLOCKED_BODY_PATTERNS) {
      if (bodyText.includes(pattern)) {
        return { denied: true, reason: `Page content indicates blocking: "${pattern}"` }
      }
    }

    return { denied: false, reason: null }
  } catch {
    return { denied: false, reason: null }
  }
}
