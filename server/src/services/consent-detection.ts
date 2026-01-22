// Cookie consent banner detection using LLM vision

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { CONSENT_DETECTION_SYSTEM_PROMPT, buildConsentDetectionUserPrompt } from '../prompts/index.js'
import type { CookieConsentDetection } from '../types.js'

// Detect cookie consent banner using LLM vision
export async function detectCookieConsent(screenshot: Buffer, html: string): Promise<CookieConsentDetection> {
  const client = getOpenAIClient()
  if (!client) {
    return {
      found: false,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: 'Azure OpenAI not configured',
    }
  }

  const deployment = getDeploymentName()

  // Extract only relevant HTML for cookie consent (much smaller payload)
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
    console.log('Cookie consent detection result:', result)
    return result
  } catch (error) {
    console.error('Cookie consent detection error:', error)
    return {
      found: false,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: `Detection failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
    }
  }
}

// Extract only relevant HTML for cookie consent analysis
function extractRelevantHtml(fullHtml: string): string {
  const patterns = [
    /<div[^>]*(?:cookie|consent|gdpr|privacy|banner|modal|popup|overlay)[^>]*>[\s\S]*?<\/div>/gi,
    /<button[^>]*>[\s\S]*?<\/button>/gi,
    /<a[^>]*(?:accept|agree|consent|allow)[^>]*>[\s\S]*?<\/a>/gi,
  ]

  const matches: string[] = []
  for (const pattern of patterns) {
    const found = fullHtml.match(pattern) || []
    matches.push(...found.slice(0, 10)) // Limit matches per pattern
  }

  const relevant = matches.join('\n').substring(0, 15000)
  return relevant || fullHtml.substring(0, 10000)
}
