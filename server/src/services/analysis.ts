/**
 * @fileoverview AI-powered tracking analysis service.
 * Uses Azure OpenAI to analyze collected tracking data and generate
 * comprehensive privacy reports with risk assessments.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import {
  TRACKING_ANALYSIS_SYSTEM_PROMPT,
  HIGH_RISKS_SYSTEM_PROMPT,
  PRIVACY_SCORE_SYSTEM_PROMPT,
  buildTrackingAnalysisUserPrompt,
  buildHighRisksUserPrompt,
  buildPrivacyScoreUserPrompt,
} from '../prompts/index.js'
import { getErrorMessage, buildTrackingSummary } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest, ConsentDetails, AnalysisResult } from '../types.js'

/**
 * Run comprehensive tracking analysis using Azure OpenAI.
 * Analyzes cookies, scripts, network requests, and storage to generate
 * a detailed privacy report and high-risks summary.
 * 
 * Optimized to run secondary analyses (high risks, score) in parallel.
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
    return { success: false, error: 'OpenAI not configured' }
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

    // Step 1: Run main analysis (required for subsequent analyses)
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

    // Step 2: Run high risks and privacy score in PARALLEL (both depend on main analysis)
    const [highRisksResult, scoreResult] = await Promise.all([
      // High risks summary
      client.chat.completions.create({
        model: deployment,
        messages: [
          { role: 'system', content: HIGH_RISKS_SYSTEM_PROMPT },
          { role: 'user', content: buildHighRisksUserPrompt(analysis) },
        ],
        max_completion_tokens: 500,
      }).catch(err => {
        console.error('Failed to generate high risks summary:', err)
        return null
      }),
      
      // Privacy score
      client.chat.completions.create({
        model: deployment,
        messages: [
          { role: 'system', content: PRIVACY_SCORE_SYSTEM_PROMPT },
          { role: 'user', content: buildPrivacyScoreUserPrompt(analysis, analyzedUrl) },
        ],
        max_completion_tokens: 200,
      }).catch(err => {
        console.error('Failed to generate privacy score:', err)
        return null
      })
    ])

    // Process summary content result
    const summaryContent = highRisksResult?.choices[0]?.message?.content || ''
    if (summaryContent) {
      console.log('Summary content generated')
    }

    // Process privacy score result
    let privacyScore: number | undefined
    let privacySummary: string | undefined
    
    if (scoreResult) {
      const scoreContent = scoreResult.choices[0]?.message?.content || ''
      console.log('Privacy score response:', scoreContent)
      try {
        const scoreData = JSON.parse(scoreContent)
        privacyScore = Math.min(100, Math.max(0, Number(scoreData.score) || 50))
        privacySummary = scoreData.summary || ''
        
        // Ensure the domain at the start of the summary is lowercase
        // LLM sometimes capitalizes it despite instructions
        if (privacySummary) {
          let siteName: string
          try {
            siteName = new URL(analyzedUrl).hostname.replace(/^www\./, '').toLowerCase()
          } catch {
            siteName = analyzedUrl.toLowerCase()
          }
          if (privacySummary.toLowerCase().startsWith(siteName)) {
            privacySummary = siteName + privacySummary.slice(siteName.length)
          }
        }
        
        console.log('Privacy score generated:', privacyScore)
      } catch (parseError) {
        console.error('Failed to parse privacy score JSON:', parseError)
        privacyScore = 50
        privacySummary = 'Unable to generate summary'
      }
    }

    return {
      success: true,
      analysis,
      summaryContent,
      privacyScore,
      privacySummary,
      summary: trackingSummary,
    }
  } catch (error) {
    console.error('Analysis error:', error)
    return { success: false, error: getErrorMessage(error) }
  }
}
