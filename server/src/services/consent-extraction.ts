/**
 * @fileoverview Consent details extraction using LLM vision.
 * Extracts detailed information about cookie categories, partners,
 * and data collection purposes from consent dialogs.
 */

import type { Page } from 'playwright'
import { getOpenAIClient, getDeploymentName } from './openai.js'
import { CONSENT_EXTRACTION_SYSTEM_PROMPT, buildConsentExtractionUserPrompt } from '../prompts/index.js'
import { createLogger, getErrorMessage, withRetry } from '../utils/index.js'
import type { ConsentDetails } from '../types.js'

const log = createLogger('Consent-Extract')

/**
 * Extract detailed consent information from a cookie preferences panel.
 * Uses LLM vision to analyze the screenshot and extract structured data
 * about cookie categories, third-party partners, and data purposes.
 *
 * @param page - Playwright Page instance for extracting visible text
 * @param screenshot - PNG screenshot buffer of the consent dialog
 * @returns Structured consent details or empty defaults if extraction fails
 */
export async function extractConsentDetails(page: Page, screenshot: Buffer): Promise<ConsentDetails> {
  const client = getOpenAIClient()
  if (!client) {
    log.warn('OpenAI not configured, skipping consent extraction')
    return {
      hasManageOptions: false,
      manageOptionsSelector: null,
      categories: [],
      partners: [],
      purposes: [],
      rawText: '',
    }
  }

  const deployment = getDeploymentName()
  log.info('Extracting consent details from page...')

  // Get all visible text from the page related to cookies/consent
  log.startTimer('text-extraction')
  
  // First extract from main page
  const mainPageText = await page.evaluate(() => {
    const selectors = [
      '[class*="cookie"]',
      '[class*="consent"]',
      '[class*="privacy"]',
      '[class*="gdpr"]',
      '[id*="cookie"]',
      '[id*="consent"]',
      '[role="dialog"]',
      '[class*="modal"]',
      '[class*="banner"]',
      '[class*="overlay"]',
      '[class*="cmp"]',
      '[class*="tcf"]',
      '[class*="vendor"]',
      '[class*="partner"]',
    ]

    const elements: string[] = []
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach((el) => {
        const text = (el as HTMLElement).innerText?.trim()
        if (text && text.length > 10 && text.length < 15000) {
          elements.push(text)
        }
      })
    }

    // Also get any tables that might list partners
    document.querySelectorAll('table').forEach((table) => {
      const text = table.innerText?.trim()
      if (
        text &&
        (text.toLowerCase().includes('partner') ||
          text.toLowerCase().includes('vendor') ||
          text.toLowerCase().includes('cookie') ||
          text.toLowerCase().includes('purpose'))
      ) {
        elements.push(text)
      }
    })
    
    // Look for lists that might contain vendors/partners
    document.querySelectorAll('ul, ol').forEach((list) => {
      const text = (list as HTMLElement).innerText?.trim()
      const parent = list.parentElement
      const parentText = (parent as HTMLElement)?.innerText?.toLowerCase() || ''
      if (
        text && 
        text.length > 50 &&
        (parentText.includes('partner') ||
         parentText.includes('vendor') ||
         parentText.includes('third part'))
      ) {
        elements.push(`PARTNER LIST:\n${text}`)
      }
    })

    return [...new Set(elements)].join('\n\n---\n\n')
  })
  
  // Also extract from consent iframes (OneTrust, Sourcepoint, etc.)
  const iframeTexts: string[] = []
  const frames = page.frames()
  for (const frame of frames) {
    if (frame === page.mainFrame()) continue
    
    const frameUrl = frame.url().toLowerCase()
    if (frameUrl.includes('consent') || frameUrl.includes('onetrust') || 
        frameUrl.includes('cookiebot') || frameUrl.includes('sourcepoint') ||
        frameUrl.includes('trustarc') || frameUrl.includes('didomi') ||
        frameUrl.includes('quantcast') || frameUrl.includes('cmp') ||
        frameUrl.includes('gdpr') || frameUrl.includes('privacy')) {
      try {
        const iframeText = await frame.evaluate(() => {
          const text = document.body?.innerText?.trim()
          return text && text.length > 50 ? text : ''
        })
        if (iframeText) {
          iframeTexts.push(`[CONSENT IFRAME]:\n${iframeText}`)
        }
      } catch {
        // Frame may be inaccessible
      }
    }
  }
  
  // Combine all text, prioritizing iframe content
  const consentText = [...iframeTexts, mainPageText]
    .filter(t => t.length > 0)
    .join('\n\n---\n\n')
    .substring(0, 50000) // Increased limit to capture more partner data
  
  log.endTimer('text-extraction', 'Text extraction complete')
  log.debug('Extracted consent text', { length: consentText.length })

  log.startTimer('vision-extraction')
  log.info('Analyzing consent dialog with vision...')
  
  try {
    const response = await withRetry(
      () => client.chat.completions.create({
        model: deployment,
        messages: [
          {
            role: 'system',
            content: CONSENT_EXTRACTION_SYSTEM_PROMPT,
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
                text: buildConsentExtractionUserPrompt(consentText),
              },
            ],
          },
        ],
        max_completion_tokens: 4000, // Increased to handle long partner lists
      }),
      { context: 'Consent extraction' }
    )

    log.endTimer('vision-extraction', 'Vision extraction complete')

    const content = response.choices[0]?.message?.content || '{}'

    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }

    const result = JSON.parse(jsonStr) as ConsentDetails
    result.rawText = consentText.substring(0, 5000) // Keep raw text for analysis
    
    log.success('Consent details extracted', { categories: result.categories.length, partners: result.partners.length, purposes: result.purposes.length })
    
    return result
  } catch (error) {
    log.error('Consent extraction failed', { error: getErrorMessage(error) })
    return {
      hasManageOptions: false,
      manageOptionsSelector: null,
      categories: [],
      partners: [],
      purposes: [],
      rawText: consentText.substring(0, 5000),
    }
  }
}
