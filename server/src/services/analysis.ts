/**
 * @fileoverview AI-powered tracking analysis service.
 * Uses Azure OpenAI to analyze collected tracking data and generate
 * comprehensive privacy reports with risk assessments.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import {
  TRACKING_ANALYSIS_SYSTEM_PROMPT,
  HIGH_RISKS_SYSTEM_PROMPT,
  buildTrackingAnalysisUserPrompt,
  buildHighRisksUserPrompt,
} from '../prompts/index.js'
import { getErrorMessage, buildTrackingSummary } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest, ConsentDetails, AnalysisResult } from '../types.js'

/**
 * Run comprehensive tracking analysis using Azure OpenAI.
 * Analyzes cookies, scripts, network requests, and storage to generate
 * a detailed privacy report and high-risks summary.
 *
 * @param cookies - Captured cookies from the browser
 * @param localStorage - localStorage items from the page
 * @param sessionStorage - sessionStorage items from the page
 * @param networkRequests - Network requests made by the page
 * @param scripts - Scripts loaded by the page
 * @param analyzedUrl - URL of the page that was analyzed
 * @param consentDetails - Optional consent dialog information for comparison
 * @returns Analysis result with full report and high-risks summary
 */
export async function runTrackingAnalysis(
  cookies: TrackedCookie[],
  localStorage: StorageItem[],
  sessionStorage: StorageItem[],
  networkRequests: NetworkRequest[],
  scripts: TrackedScript[],
  analyzedUrl: string,
  consentDetails?: ConsentDetails | null
): Promise<AnalysisResult> {
  const client = getOpenAIClient()
  if (!client) {
    return { success: false, error: 'Azure OpenAI not configured' }
  }

  try {
    const trackingSummary = buildTrackingSummary(
      cookies,
      scripts,
      networkRequests,
      localStorage,
      sessionStorage,
      analyzedUrl
    )

    const deployment = getDeploymentName()

    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: TRACKING_ANALYSIS_SYSTEM_PROMPT },
        { role: 'user', content: buildTrackingAnalysisUserPrompt(trackingSummary, consentDetails) },
      ],
      max_completion_tokens: 3000,
    })

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'
    console.log('Analysis generated, length:', analysis.length)

    // Generate a concise high risks summary
    let highRisks = ''
    try {
      const highRisksResponse = await client.chat.completions.create({
        model: deployment,
        messages: [
          { role: 'system', content: HIGH_RISKS_SYSTEM_PROMPT },
          { role: 'user', content: buildHighRisksUserPrompt(analysis) },
        ],
        max_completion_tokens: 500,
      })
      highRisks = highRisksResponse.choices[0]?.message?.content || ''
      console.log('High risks summary generated')
    } catch (highRisksError) {
      console.error('Failed to generate high risks summary:', highRisksError)
    }

    return {
      success: true,
      analysis,
      highRisks,
      summary: trackingSummary,
    }
  } catch (error) {
    console.error('Analysis error:', error)
    return { success: false, error: getErrorMessage(error) }
  }
}
