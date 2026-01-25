/**
 * @fileoverview Cookie consent banner detection using LLM vision.
 * Uses Azure OpenAI to analyze screenshots and find "Accept All" buttons.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { CONSENT_DETECTION_SYSTEM_PROMPT, buildConsentDetectionUserPrompt } from '../prompts/index.js'
import { getErrorMessage } from '../utils/index.js'
import type { CookieConsentDetection } from '../types.js'

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

  try {
    const response = await client.chat.completions.create({
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
    })

    const content = response.choices[0]?.message?.content || '{}'

    // Parse JSON from response, handling potential markdown code blocks
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }

    const result = JSON.parse(jsonStr) as CookieConsentDetection
    console.log('Overlay detection result:', result)
    return result
  } catch (error) {
    console.error('Overlay detection error:', error)
    return {
      found: false,
      overlayType: null,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: `Detection failed: ${getErrorMessage(error)}`,
    }
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
