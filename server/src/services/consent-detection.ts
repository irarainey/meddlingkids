/**
 * @fileoverview Cookie consent banner detection using LLM vision.
 * Uses Azure OpenAI to analyze screenshots and find "Accept All" buttons.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { CONSENT_DETECTION_SYSTEM_PROMPT, buildConsentDetectionUserPrompt } from '../prompts/index.js'
import { getErrorMessage, createLogger, withRetry } from '../utils/index.js'
import type { CookieConsentDetection } from '../types.js'

const log = createLogger('Consent-Detect')

/**
 * Detect blocking overlays (cookie consent, sign-in walls, etc.) using LLM vision analysis.
 * Analyzes a screenshot and HTML to find the dismiss/accept button.
 *
 * @param screenshot - PNG screenshot buffer of the page
 * @param html - Full HTML content of the page
 * @returns Detection result with selector and confidence level
 */
export async function detectCookieConsent(screenshot: Buffer, html: string): Promise<CookieConsentDetection> {
  const client = getOpenAIClient()
  if (!client) {
    log.warn('OpenAI not configured, skipping consent detection')
    return {
      found: false,
      overlayType: null,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: 'OpenAI not configured',
    }
  }

  const deployment = getDeploymentName()

  // Extract only relevant HTML for overlay detection (much smaller payload)
  const relevantHtml = extractRelevantHtml(html)
  log.debug('Extracted relevant HTML', { originalLength: html.length, extractedLength: relevantHtml.length })

  log.startTimer('vision-detection')
  log.info('Analyzing screenshot for overlays...')
  
  try {
    const response = await withRetry(
      () => client.chat.completions.create({
        model: deployment,
        messages: [
          {
            role: 'system',
            content: CONSENT_DETECTION_SYSTEM_PROMPT,
          },
          {
            role: 'user',
            content: [
              {
                type: 'image_url',
                image_url: {
                  url: `data:image/png;base64,${screenshot.toString('base64')}`,
                },
              },
              {
                type: 'text',
                text: buildConsentDetectionUserPrompt(relevantHtml),
              },
            ],
          },
        ],
        max_completion_tokens: 500,
      }),
      { context: 'Consent detection' }
    )

    log.endTimer('vision-detection', 'Vision analysis complete')

    const content = response.choices[0]?.message?.content || '{}'

    // Parse JSON from response, handling potential markdown code blocks
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }

    const result = JSON.parse(jsonStr) as CookieConsentDetection
    
    if (result.found) {
      log.success('Overlay detected', { type: result.overlayType, selector: result.selector, confidence: result.confidence })
    } else {
      log.info('No overlay detected', { reason: result.reason })
    }
    
    return result
  } catch (error) {
    const errorMsg = getErrorMessage(error)
    
    // Check if this is a content filter error from Azure OpenAI
    if (errorMsg.includes('filtered') || errorMsg.includes('content_filter') || errorMsg.includes('ResponsibleAIPolicyViolation')) {
      log.warn('Content filtered by Azure OpenAI - screenshot may contain flagged content, trying HTML-only detection')
      
      // Try HTML-only fallback detection
      return detectFromHtmlOnly(relevantHtml)
    }
    
    log.error('Overlay detection failed', { error: errorMsg })
    return {
      found: false,
      overlayType: null,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: `Detection failed: ${errorMsg}`,
    }
  }
}

/**
 * Fallback detection using HTML patterns only (no vision).
 * Used when Azure content filter rejects the screenshot.
 */
function detectFromHtmlOnly(html: string): CookieConsentDetection {
  const log2 = createLogger('Consent-Detect')
  log2.info('Attempting HTML-only overlay detection...')
  
  // Common cookie consent button patterns
  const consentPatterns = [
    { pattern: /id=["']?onetrust-accept-btn-handler["']?/i, selector: '#onetrust-accept-btn-handler', type: 'cookie-consent' as const },
    { pattern: /id=["']?accept-cookies["']?/i, selector: '#accept-cookies', type: 'cookie-consent' as const },
    { pattern: /id=["']?CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll["']?/i, selector: '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll', type: 'cookie-consent' as const },
    { pattern: /id=["']?didomi-notice-agree-button["']?/i, selector: '#didomi-notice-agree-button', type: 'cookie-consent' as const },
    { pattern: /class=["'][^"']*sp_choice_type_11[^"']*["']?/i, selector: 'button.sp_choice_type_11', type: 'cookie-consent' as const },
    { pattern: /data-action=["']?accept["']?/i, selector: '[data-action="accept"]', type: 'cookie-consent' as const },
    { pattern: /data-testid=["']?accept-button["']?/i, selector: '[data-testid="accept-button"]', type: 'cookie-consent' as const },
    { pattern: /aria-label=["'][^"']*[Aa]ccept[^"']*["']/i, selector: '[aria-label*="ccept"]', type: 'cookie-consent' as const },
    { pattern: />Accept All</i, selector: 'button:has-text("Accept All")', type: 'cookie-consent' as const },
    { pattern: />Accept Cookies</i, selector: 'button:has-text("Accept Cookies")', type: 'cookie-consent' as const },
    { pattern: />I Agree</i, selector: 'button:has-text("I Agree")', type: 'cookie-consent' as const },
    { pattern: />Agree</i, selector: 'button:has-text("Agree")', type: 'cookie-consent' as const },
  ]
  
  for (const { pattern, selector, type } of consentPatterns) {
    if (pattern.test(html)) {
      log2.success('Found overlay via HTML pattern matching', { selector, type })
      return {
        found: true,
        overlayType: type,
        selector,
        buttonText: 'Accept',
        confidence: 'medium',
        reason: 'Detected via HTML pattern matching (vision unavailable due to content filter)',
      }
    }
  }
  
  log2.info('No overlay detected via HTML patterns')
  return {
    found: false,
    overlayType: null,
    selector: null,
    buttonText: null,
    confidence: 'low',
    reason: 'No overlay detected (HTML-only detection, vision unavailable due to content filter)',
  }
}

/**
 * Extract only relevant HTML snippets for overlay analysis.
 * Reduces payload size by filtering to elements likely to contain overlay UI.
 *
 * @param fullHtml - Complete HTML content of the page
 * @returns Filtered HTML containing likely overlay-related elements
 */
function extractRelevantHtml(fullHtml: string): string {
  const patterns = [
    // Cookie consent related
    /<div[^>]*(?:cookie|consent|gdpr|privacy|banner|modal|popup|overlay)[^>]*>[\s\S]*?<\/div>/gi,
    // Sign-in / account walls (including BBC-style prompts)
    /<div[^>]*(?:sign-?in|login|auth|account|register|subscribe|newsletter|prompt|upsell|gate)[^>]*>[\s\S]*?<\/div>/gi,
    // Modal and dialog elements
    /<(?:dialog|aside)[^>]*>[\s\S]*?<\/(?:dialog|aside)>/gi,
    /<div[^>]*(?:role=["']dialog["']|aria-modal)[^>]*>[\s\S]*?<\/div>/gi,
    // Fixed/sticky positioned elements (often overlays)
    /<div[^>]*(?:position:\s*fixed|position:\s*sticky)[^>]*>[\s\S]*?<\/div>/gi,
    // All buttons
    /<button[^>]*>[\s\S]*?<\/button>/gi,
    // All links (to catch "Maybe Later" style dismiss links)
    /<a[^>]*>[\s\S]*?<\/a>/gi,
    // Close buttons and icons
    /<[^>]*(?:class|id)=["'][^"']*(?:close|dismiss|skip|later)[^"']*["'][^>]*>[\s\S]*?<\/[^>]+>/gi,
    // Sections that might contain sign-in prompts
    /<section[^>]*>[\s\S]*?<\/section>/gi,
  ]

  const matches: string[] = []
  for (const pattern of patterns) {
    const found = fullHtml.match(pattern) || []
    matches.push(...found.slice(0, 15)) // Limit matches per pattern
  }

  const relevant = matches.join('\n').substring(0, 20000)
  return relevant || fullHtml.substring(0, 15000)
}
