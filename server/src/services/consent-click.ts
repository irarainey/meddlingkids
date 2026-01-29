/**
 * @fileoverview Consent button click strategies.
 * Prioritizes LLM-suggested selectors, checking main page and iframes.
 */

import type { Page, Frame } from 'playwright'
import { createLogger, withRetry } from '../utils/index.js'
import { getOpenAIClient, getDeploymentName } from './openai.js'

const log = createLogger('Consent-Click')

/**
 * Click a consent/dismiss button using LLM-provided selector and text.
 * Checks iframes FIRST since consent managers often use iframes (OneTrust, Sourcepoint, etc.).
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
  log.info('Attempting click', { selector, buttonText })
  
  // Phase 1: Try iframes FIRST (consent managers like OneTrust, Sourcepoint use iframes)
  const frames = page.frames()
  const consentFrames = frames.filter(f => {
    const url = f.url().toLowerCase()
    return f !== page.mainFrame() && (
      url.includes('consent') ||
      url.includes('onetrust') ||
      url.includes('cookiebot') ||
      url.includes('sourcepoint') ||
      url.includes('trustarc') ||
      url.includes('didomi') ||
      url.includes('quantcast') ||
      url.includes('gdpr') ||
      url.includes('privacy')
    )
  })
  
  // Try consent-related iframes first (more likely to contain the button)
  for (const frame of consentFrames) {
    const frameUrl = frame.url()
    log.debug('Checking consent iframe', { url: frameUrl.substring(0, 80) })
    
    const iframeResult = await tryClickInFrame(frame, selector, buttonText, 1500)
    if (iframeResult) {
      log.success('Click succeeded in consent iframe', { url: frameUrl.substring(0, 50) })
      return true
    }
  }
  
  // Phase 2: Try main page (quick - 1.5s timeout)
  const mainResult = await tryClickInFrame(page.mainFrame(), selector, buttonText, 1500)
  if (mainResult) {
    log.success('Click succeeded on main page')
    return true
  }

  // Phase 3: Try remaining iframes
  const otherFrames = frames.filter(f => f !== page.mainFrame() && !consentFrames.includes(f))
  if (otherFrames.length > 0) {
    log.debug('Checking remaining iframes', { count: otherFrames.length })
    
    for (const frame of otherFrames) {
      const frameUrl = frame.url()
      log.debug('Checking iframe', { url: frameUrl.substring(0, 80) })
      
      const iframeResult = await tryClickInFrame(frame, selector, buttonText, 1500)
      if (iframeResult) {
        log.success('Click succeeded in iframe', { url: frameUrl.substring(0, 50) })
        return true
      }
    }
  }

  // Phase 4: Last resort - try generic close buttons on main page
  log.debug('Trying generic close buttons...')
  const closeResult = await tryCloseButtons(page)
  if (closeResult) return true

  log.warn('All click strategies failed')
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
      log.debug('Trying close button', { selector: sel })
      await page.locator(sel).first().click({ timeout: 1000 })
      log.success('Close button clicked', { selector: sel })
      return true
    } catch {
      // Try next
    }
  }

  return false
}

/**
 * Text patterns for buttons that close/go back from expanded dialogs.
 * After gathering partner info, we need to return to the main consent dialog.
 * Ordered by preference - most specific navigation patterns first.
 */
const CLOSE_BACK_PATTERNS = [
  // Specific "return to consent" patterns (highest priority)
  /^back\s+to\s+consent$/i,
  /^return\s+to\s+consent$/i,
  /^go\s+to\s+consent$/i,
  // Back/return buttons
  /^back$/i,
  /^go\s*back$/i,
  /^←\s*back$/i,
  /^←$/i,
  /^return$/i,
  /^previous$/i,
  // Close buttons
  /^close$/i,
  /^×$/i,
  /^x$/i,
  // Save and close (these should go back to consent after saving)
  /^save\s*(?:&|and)?\s*(?:close|exit)?$/i,
  /^save\s+(?:preferences?|settings?|choices?)$/i,
  /^confirm\s+(?:preferences?|settings?|choices?)$/i,
  /^done$/i,
  /^ok$/i,
  // Cancel
  /^cancel$/i,
]

/**
 * Close expanded consent dialogs and return to main consent screen.
 * After gathering partner info, we need to get back to where we can accept.
 * Uses pattern matching first, then falls back to LLM assistance if stuck.
 * 
 * @param page - Playwright Page instance
 * @param stepsToClose - Number of expansion steps to potentially close
 * @returns True if successfully closed/navigated back
 */
export async function closeExpandedDialogs(page: Page, stepsToClose: number): Promise<boolean> {
  log.info('Attempting to close expanded dialogs...', { stepsToClose })
  
  let closedAny = false
  let failedAttempts = 0
  const maxFailedAttempts = 2  // Fail fast - only 2 failed attempts before trying LLM
  const maxTotalAttempts = stepsToClose + 2
  
  for (let attempt = 1; attempt <= maxTotalAttempts; attempt++) {
    log.debug(`Close attempt ${attempt}/${maxTotalAttempts} (failed: ${failedAttempts})...`)
    
    // Strategy 1: Quick pattern-based back/close buttons (fast)
    const backClicked = await tryClickBackButton(page, 500)  // Short timeout
    if (backClicked) {
      closedAny = true
      failedAttempts = 0  // Reset on success
      await page.waitForTimeout(400)
      continue
    }
    
    // Strategy 2: Aria-label buttons (fast)
    const closeClicked = await tryAriaCloseButtons(page, 500)
    if (closeClicked) {
      closedAny = true
      failedAttempts = 0
      await page.waitForTimeout(400)
      continue
    }
    
    // Strategy 3: Escape key
    log.debug('Trying Escape key...')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
    
    failedAttempts++
    
    // If pattern matching keeps failing, ask LLM for help
    if (failedAttempts >= maxFailedAttempts) {
      log.info('Pattern matching failed, asking LLM for navigation help...')
      const llmResult = await askLLMForNavigationHelp(page)
      if (llmResult.clicked) {
        closedAny = true
        failedAttempts = 0
        await page.waitForTimeout(500)
        continue
      } else {
        // LLM couldn't help either, break out
        log.warn('LLM navigation help failed', { reason: llmResult.reason })
        break
      }
    }
  }
  
  if (closedAny) {
    log.success('Closed expanded dialogs')
  } else {
    log.debug('Could not close expanded dialogs')
  }
  
  return closedAny
}

/**
 * Result of LLM navigation assistance.
 */
interface LLMNavigationResult {
  clicked: boolean
  reason?: string
  buttonText?: string
}

/**
 * Ask LLM to analyze screenshot and help navigate back to main consent.
 * Used when pattern matching fails to find the right button.
 */
async function askLLMForNavigationHelp(page: Page): Promise<LLMNavigationResult> {
  const client = getOpenAIClient()
  if (!client) {
    return { clicked: false, reason: 'OpenAI not configured' }
  }
  
  try {
    // Take screenshot
    const screenshot = await page.screenshot({ type: 'png' })
    const base64Screenshot = screenshot.toString('base64')
    
    // Get visible button text for context
    const buttonTexts = await page.evaluate(() => {
      const buttons = document.querySelectorAll('button, a, [role="button"]')
      return Array.from(buttons)
        .map(b => (b as HTMLElement).innerText?.trim())
        .filter(t => t && t.length > 0 && t.length < 50)
        .slice(0, 20)
    })
    
    log.debug('Asking LLM for navigation help', { visibleButtons: buttonTexts.length })
    
    const deployment = getDeploymentName()
    const response = await withRetry(
      () => client.chat.completions.create({
        model: deployment,
        messages: [
          {
            role: 'system',
            content: `You are helping navigate a cookie consent dialog. The user has expanded partner/vendor information and needs to get back to the main consent dialog where they can click "Accept All" or "I Accept".

Analyze the screenshot and identify the button to click to navigate BACK to the main consent dialog.

Look for buttons like:
- "Back" or "← Back"
- "Back to Consent" or "Return to Consent"
- "Close" or "×"
- "Save & Exit" or "Done"
- Any navigation that would return to the main consent screen

Respond with JSON only:
{
  "buttonText": "exact text of button to click",
  "selector": "CSS selector if visible",
  "confidence": "high" | "medium" | "low",
  "reason": "brief explanation"
}

If there's no clear navigation button (e.g., already on main consent), respond:
{
  "buttonText": null,
  "reason": "Already on main consent" or "No navigation button found"
}`
          },
          {
            role: 'user',
            content: [
              {
                type: 'image_url',
                image_url: { url: `data:image/png;base64,${base64Screenshot}` }
              },
              {
                type: 'text',
                text: `Visible buttons on page: ${buttonTexts.join(', ')}\n\nWhat button should I click to get back to the main consent dialog?`
              }
            ]
          }
        ],
        max_completion_tokens: 300,
      }),
      { context: 'LLM navigation help', maxRetries: 1 }
    )
    
    const content = response.choices[0]?.message?.content || '{}'
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }
    
    const result = JSON.parse(jsonStr)
    log.info('LLM navigation suggestion', { buttonText: result.buttonText, confidence: result.confidence, reason: result.reason })
    
    if (!result.buttonText) {
      return { clicked: false, reason: result.reason || 'No button suggested' }
    }
    
    // Try to click the suggested button
    const clicked = await tryClickByText(page, result.buttonText, result.selector)
    if (clicked) {
      log.success('LLM-guided click successful', { buttonText: result.buttonText })
      return { clicked: true, buttonText: result.buttonText }
    }
    
    return { clicked: false, reason: 'Could not click suggested button' }
    
  } catch (error) {
    log.warn('LLM navigation help error', { error: String(error) })
    return { clicked: false, reason: String(error) }
  }
}

/**
 * Try to click an element by text or selector.
 */
async function tryClickByText(page: Page, buttonText: string, selector?: string): Promise<boolean> {
  // Try selector first if provided
  if (selector) {
    try {
      await page.locator(selector).first().click({ timeout: 1000 })
      return true
    } catch {
      // Fall through to text matching
    }
  }
  
  // Try by exact text
  try {
    await page.getByText(buttonText, { exact: true }).first().click({ timeout: 1000 })
    return true
  } catch {
    // Try partial
  }
  
  // Try partial text
  try {
    await page.getByText(buttonText, { exact: false }).first().click({ timeout: 1000 })
    return true
  } catch {
    // Try button role
  }
  
  // Try as button
  try {
    await page.getByRole('button', { name: buttonText }).first().click({ timeout: 1000 })
    return true
  } catch {
    return false
  }
}

/**
 * Try to click a back/close button using pattern matching.
 */
async function tryClickBackButton(page: Page, timeout: number = 1000): Promise<boolean> {
  try {
    const clickables = await page.locator(
      'button, a, [role="button"], span[onclick], div[onclick]'
    ).all()
    
    for (const element of clickables) {
      try {
        if (!await element.isVisible({ timeout: 100 })) continue
        
        const text = await element.textContent({ timeout: 200 })
        if (!text) continue
        
        const trimmedText = text.trim()
        if (trimmedText.length > 50) continue
        
        for (const pattern of CLOSE_BACK_PATTERNS) {
          if (pattern.test(trimmedText)) {
            log.debug('Found back/close button', { text: trimmedText })
            await element.click({ timeout })
            log.success('Clicked back/close button', { text: trimmedText })
            return true
          }
        }
      } catch {
        // Continue
      }
    }
  } catch {
    // Ignore
  }
  return false
}

/**
 * Try to click aria-label close buttons.
 */
async function tryAriaCloseButtons(page: Page, timeout: number = 1000): Promise<boolean> {
  const closeSelectors = [
    '[aria-label*="close" i]',
    '[aria-label*="back" i]',
    '[aria-label*="dismiss" i]',
    '[aria-label*="return" i]',
    'button[class*="back"]',
    'button[class*="close"]',
    '[class*="back-button"]',
    '[class*="close-button"]',
  ]
  
  for (const selector of closeSelectors) {
    try {
      const element = page.locator(selector).first()
      if (await element.isVisible({ timeout: 150 })) {
        await element.click({ timeout })
        log.debug('Clicked aria close button', { selector })
        return true
      }
    } catch {
      // Continue
    }
  }
  return false
}

/**
 * Text patterns for buttons that open settings/preferences (first level).
 * These open the main settings panel from the initial banner.
 */
const MANAGE_OPTIONS_PATTERNS = [
  /^manage\s+(?:cookie\s+)?(?:preferences?|options?|settings?)$/i,
  /^cookie\s+settings?$/i,
  /^privacy\s+settings?$/i,
  /^customise?\s+(?:cookies?)?$/i,
  /^more\s+options?$/i,  // Bristol Post / InMobi uses this
  /^advanced\s+settings?$/i,
  /^options?$/i,
]

/**
 * Text patterns for buttons that reveal partner/vendor lists (second level).
 * These are typically found inside the settings panel.
 */
const PARTNER_LIST_BUTTON_PATTERNS = [
  // Direct partner/vendor mentions - exact matches first
  /^partners?$/i,  // Bristol Post / InMobi uses just "Partners"
  /^view\s+(?:all\s+)?(?:our\s+)?partners?$/i,
  /^show\s+(?:all\s+)?partners?$/i,
  /^(?:see\s+)?(?:our\s+)?(?:\d+\s+)?partners?$/i,
  /partners?\s*\([\d,]+\)/i,
  /^vendor\s*list$/i,
  /^vendors?$/i,
  /^view\s+(?:all\s+)?vendors?$/i,
  /^(?:our\s+)?vendors?\s*\([\d,]+\)/i,
  /^iab\s+vendors?/i,
  /^(?:tcf\s+)?vendor\s+list$/i,
  // Third party mentions
  /^(?:view\s+)?third[- ]part(?:y|ies)/i,
  // Expandable list patterns
  /^see\s+all$/i,
  /^view\s+all$/i,
  /^show\s+all$/i,
  /^more\s+info(?:rmation)?$/i,
  /^learn\s+more$/i,
]

/**
 * Text patterns for legitimate interest section (third level).
 * Bristol Post and other TCF-compliant sites have this.
 */
const LEGITIMATE_INTEREST_PATTERNS = [
  /^legitimate\s+interest$/i,
  /^legitimate\s+interests?$/i,
  /^view\s+legitimate\s+interest/i,
  /^legit(?:imate)?\s+int(?:erest)?/i,
]

/**
 * Result of expanding the consent dialog.
 */
export interface ExpansionResult {
  /** Whether any expansion occurred */
  expanded: boolean
  /** Steps that were clicked (for logging/screenshots) */
  steps: Array<{
    type: 'manage-options' | 'partners' | 'legitimate-interest' | 'load-more'
    buttonText: string
  }>
}

/**
 * Callback function called after each expansion step.
 * Allows caller to take screenshots after each DOM change.
 */
export type ExpansionStepCallback = (step: ExpansionResult['steps'][0]) => Promise<void>

/**
 * Expand consent dialog to reveal partner/vendor information.
 * 
 * PURPOSE: This is INFORMATIONAL ONLY - to gather data about partners, purposes,
 * and consent categories BEFORE accepting. The primary goal remains accepting
 * consent and analyzing the final page state.
 * 
 * Many consent managers hide the partner list behind multiple clicks:
 * 1. "More Options" / "Manage Options" → opens settings panel
 * 2. "Partners" / "View Partners" → shows partner list
 * 3. "Legitimate Interest" → shows legitimate interest vendors
 *
 * This function is best-effort and should not block the main analysis flow.
 * After expansion (or timeout), the caller should proceed to accept consent.
 *
 * @param page - Playwright Page instance
 * @param onStep - Optional callback called after each expansion step (for screenshots)
 * @returns Expansion result with steps taken
 */
export async function expandPartnerList(
  page: Page,
  onStep?: ExpansionStepCallback
): Promise<ExpansionResult> {
  log.info('Starting partner info expansion (informational only)...')
  const result: ExpansionResult = { expanded: false, steps: [] }

  // Keep expansion quick - this is informational, not critical path
  // Primary goal is accepting consent and analyzing final page
  const expansionTimeout = 10000  // 10 seconds max
  const startTime = Date.now()
  
  const isTimedOut = () => Date.now() - startTime > expansionTimeout
  const elapsed = () => Date.now() - startTime

  // Get all frames to check, prioritizing consent iframes
  const getFramesToCheck = () => {
    const frames = page.frames()
    const consentFrames = frames.filter(f => {
      const url = f.url().toLowerCase()
      return f !== page.mainFrame() && (
        url.includes('consent') ||
        url.includes('onetrust') ||
        url.includes('cookiebot') ||
        url.includes('sourcepoint') ||
        url.includes('trustarc') ||
        url.includes('didomi') ||
        url.includes('quantcast') ||
        url.includes('gdpr') ||
        url.includes('privacy') ||
        url.includes('cmp') ||
        url.includes('inmobi')  // Bristol Post uses InMobi
      )
    })
    log.debug('Frames to check', { main: 1, consentIframes: consentFrames.length, totalFrames: frames.length })
    return [page.mainFrame(), ...consentFrames]
  }

  try {
    // Step 1: Try to click "More Options" / "Manage Options" buttons
    log.info('Step 1: Looking for manage options button...', { elapsed: elapsed() })
    if (!isTimedOut()) {
      const framesToCheck = getFramesToCheck()
      for (let i = 0; i < framesToCheck.length; i++) {
        const frame = framesToCheck[i]
        log.debug(`Checking frame ${i + 1}/${framesToCheck.length} for manage options...`)
        const clicked = await tryClickExpansionButton(frame, MANAGE_OPTIONS_PATTERNS, 2000)
        if (clicked.success) {
          log.success('Clicked manage options button', { text: clicked.buttonText, elapsed: elapsed() })
          result.expanded = true
          const step = { type: 'manage-options' as const, buttonText: clicked.buttonText }
          result.steps.push(step)
          
          // Wait for DOM to update after click
          log.debug('Waiting for DOM update after manage options click...')
          await waitForDomUpdate(page, 1500)
          
          // Call callback so caller can take screenshot
          if (onStep) {
            log.debug('Calling onStep callback for screenshot...')
            await onStep(step)
          }
          break
        }
      }
      if (!result.steps.find(s => s.type === 'manage-options')) {
        log.debug('No manage options button found', { elapsed: elapsed() })
      }
    } else {
      log.warn('Skipping step 1 - already timed out', { elapsed: elapsed() })
    }

    // Step 2: Try to click "Partners" button (may appear after step 1)
    log.info('Step 2: Looking for partners button...', { elapsed: elapsed() })
    if (!isTimedOut()) {
      const framesToCheck = getFramesToCheck()
      for (let i = 0; i < framesToCheck.length; i++) {
        const frame = framesToCheck[i]
        log.debug(`Checking frame ${i + 1}/${framesToCheck.length} for partners button...`)
        const clicked = await tryClickExpansionButton(frame, PARTNER_LIST_BUTTON_PATTERNS, 2000)
        if (clicked.success) {
          log.success('Clicked partner list button', { text: clicked.buttonText, elapsed: elapsed() })
          result.expanded = true
          const step = { type: 'partners' as const, buttonText: clicked.buttonText }
          result.steps.push(step)
          
          // Wait for DOM to update after click
          log.debug('Waiting for DOM update after partners click...')
          await waitForDomUpdate(page, 1500)
          
          // Call callback so caller can take screenshot
          if (onStep) {
            log.debug('Calling onStep callback for screenshot...')
            await onStep(step)
          }
          break
        }
      }
      if (!result.steps.find(s => s.type === 'partners')) {
        log.debug('No partners button found', { elapsed: elapsed() })
      }
    } else {
      log.warn('Skipping step 2 - already timed out', { elapsed: elapsed() })
    }

    // Step 3: Try to click "Legitimate Interest" (may be separate tab/section)
    log.info('Step 3: Looking for legitimate interest button...', { elapsed: elapsed() })
    if (!isTimedOut()) {
      const framesToCheck = getFramesToCheck()
      for (let i = 0; i < framesToCheck.length; i++) {
        const frame = framesToCheck[i]
        log.debug(`Checking frame ${i + 1}/${framesToCheck.length} for legitimate interest...`)
        const clicked = await tryClickExpansionButton(frame, LEGITIMATE_INTEREST_PATTERNS, 2000)
        if (clicked.success) {
          log.success('Clicked legitimate interest button', { text: clicked.buttonText, elapsed: elapsed() })
          result.expanded = true
          const step = { type: 'legitimate-interest' as const, buttonText: clicked.buttonText }
          result.steps.push(step)
          
          // Wait for DOM to update after click
          log.debug('Waiting for DOM update after legitimate interest click...')
          await waitForDomUpdate(page, 1000)
          
          // Call callback so caller can take screenshot
          if (onStep) {
            log.debug('Calling onStep callback for screenshot...')
            await onStep(step)
          }
          break
        }
      }
      if (!result.steps.find(s => s.type === 'legitimate-interest')) {
        log.debug('No legitimate interest button found', { elapsed: elapsed() })
      }
    } else {
      log.warn('Skipping step 3 - already timed out', { elapsed: elapsed() })
    }

    // Step 4: Try to expand scrollable lists (load more)
    log.info('Step 4: Looking for load more buttons...', { elapsed: elapsed() })
    if (!isTimedOut()) {
      const loadMoreClicked = await tryExpandScrollableLists(page)
      if (loadMoreClicked) {
        log.success('Clicked load more button', { elapsed: elapsed() })
        const step = { type: 'load-more' as const, buttonText: 'Load more' }
        result.steps.push(step)
        if (onStep) {
          await onStep(step)
        }
      } else {
        log.debug('No load more buttons found', { elapsed: elapsed() })
      }
    } else {
      log.warn('Skipping step 4 - already timed out', { elapsed: elapsed() })
    }
  } catch (error) {
    log.warn('Expansion process error', { error: String(error), elapsed: elapsed() })
  }

  if (isTimedOut()) {
    log.warn('Partner expansion timed out', { elapsed: elapsed(), timeout: expansionTimeout })
  }

  if (result.expanded) {
    log.success('Partner info expansion complete', { 
      steps: result.steps.length, 
      types: result.steps.map(s => s.type).join(', '),
      elapsed: elapsed()
    })
  } else {
    log.info('No partner expansion buttons found (may already be expanded or not available)', { elapsed: elapsed() })
  }

  return result
}

/**
 * Wait for DOM to update after a click action.
 * Uses multiple strategies to detect when the new content has loaded.
 */
async function waitForDomUpdate(page: Page, maxWait: number): Promise<void> {
  const startTime = Date.now()
  log.debug('Waiting for DOM update...', { maxWait })
  
  try {
    // Strategy 1: Wait for network to be idle (new dialog may load content)
    await Promise.race([
      page.waitForLoadState('domcontentloaded', { timeout: maxWait }),
      page.waitForTimeout(maxWait)
    ])
  } catch {
    // Ignore timeout errors
  }
  
  // Ensure we've waited at least 500ms for animations
  const elapsed = Date.now() - startTime
  if (elapsed < 500) {
    await page.waitForTimeout(500 - elapsed)
  }
  
  log.debug('DOM update wait complete', { actualWait: Date.now() - startTime })
}

/**
 * Result of trying to click an expansion button.
 */
interface ClickResult {
  success: boolean
  buttonText: string
}

/**
 * Try clicking a button matching one of the patterns.
 * For <a> tags with hrefs, clicks and verifies URL didn't change (dialog opened via JS).
 * If URL changes, navigates back and tries next element.
 */
async function tryClickExpansionButton(
  frame: Frame,
  patterns: RegExp[],
  timeout: number
): Promise<ClickResult> {
  const page = frame.page()
  
  try {
    // Get all buttons and clickable elements - include divs with click handlers
    const clickables = await frame.locator(
      'button, a, [role="button"], [onclick], [class*="link"], span[tabindex], div[tabindex], [class*="tab"], [class*="accordion"]'
    ).all()
    
    log.debug('Found clickable elements', { count: clickables.length })
    let visibleCount = 0
    let matchedCount = 0
    
    for (const element of clickables) {
      try {
        // Check if element is visible
        if (!await element.isVisible({ timeout: 200 })) continue
        visibleCount++
        
        const text = await element.textContent({ timeout: 500 })
        if (!text) continue
        
        const trimmedText = text.trim()
        // Skip if text is too long (likely a container, not a button)
        if (trimmedText.length > 100) continue
        
        for (const pattern of patterns) {
          if (pattern.test(trimmedText)) {
            matchedCount++
            const tagName = await element.evaluate(el => el.tagName.toLowerCase())
            log.info('Found matching expansion element', { 
              text: trimmedText.substring(0, 50), 
              tag: tagName,
              pattern: pattern.toString().substring(0, 30)
            })
            
            // For <a> tags with real hrefs, we need to check if clicking causes navigation
            const href = tagName === 'a' ? await element.getAttribute('href') : null
            const mightNavigate = href && !href.startsWith('#') && !href.startsWith('javascript:')
            
            if (mightNavigate) {
              log.debug('Element is a link with href, checking for navigation...', { href: href?.substring(0, 50) })
              // Record current URL before clicking
              const urlBefore = page.url()
              
              // Click and wait briefly
              log.debug('Clicking link element...')
              await element.click({ timeout })
              await page.waitForTimeout(500)
              
              // Check if URL changed
              const urlAfter = page.url()
              if (urlAfter !== urlBefore) {
                // Navigation occurred - go back and skip this element
                log.warn('Link caused page navigation, going back', { 
                  from: urlBefore.substring(0, 50), 
                  to: urlAfter.substring(0, 50) 
                })
                await page.goBack({ timeout: 3000 }).catch(() => {})
                await page.waitForTimeout(500)
                continue  // Try next element
              }
              
              // URL didn't change - dialog likely opened via JS
              log.success('Link opened dialog without navigation', { text: trimmedText.substring(0, 50) })
              return { success: true, buttonText: trimmedText.substring(0, 50) }
            } else {
              // Regular button or safe link - just click
              log.debug('Clicking non-navigation element...', { tag: tagName })
              await element.click({ timeout })
              log.success('Click successful', { text: trimmedText.substring(0, 50) })
              return { success: true, buttonText: trimmedText.substring(0, 50) }
            }
          }
        }
      } catch (elementError) {
        // Element may have been removed, continue
        log.debug('Element error, continuing...', { error: String(elementError).substring(0, 50) })
      }
    }
    
    log.debug('No matching elements found', { visible: visibleCount, matched: matchedCount })
  } catch (frameError) {
    // Frame may be detached
    log.debug('Frame error', { error: String(frameError).substring(0, 50) })
  }
  
  return { success: false, buttonText: '' }
}

/**
 * Try expanding scrollable lists that may contain more partners.
 * @returns True if any load more button was clicked
 */
async function tryExpandScrollableLists(page: Page): Promise<boolean> {
  let clicked = false
  try {
    // Look for "load more" or similar buttons within lists
    const loadMorePatterns = [
      'button:has-text("Load more")',
      'button:has-text("Show more")',
      'button:has-text("View all")',
      '[class*="load-more"]',
      '[class*="show-more"]',
      '[class*="expand"]',
    ]
    
    for (const selector of loadMorePatterns) {
      try {
        const button = page.locator(selector).first()
        if (await button.isVisible({ timeout: 500 })) {
          await button.click({ timeout: 1000 })
          log.debug('Clicked load more button', { selector })
          await page.waitForTimeout(500)
          clicked = true
        }
      } catch {
        // Continue
      }
    }
  } catch {
    // Ignore errors
  }
  return clicked
}
