/**
 * @fileoverview AI-powered tracking analysis service.
 * Uses Azure OpenAI to analyze collected tracking data and generate
 * comprehensive privacy reports with risk assessments.
 * Privacy score is calculated deterministically for consistency.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { calculatePrivacyScore, type PrivacyScoreBreakdown } from './privacy-score.js'
import {
  TRACKING_ANALYSIS_SYSTEM_PROMPT,
  SUMMARY_FINDINGS_SYSTEM_PROMPT,
  buildTrackingAnalysisUserPrompt,
  buildSummaryFindingsUserPrompt,
} from '../prompts/index.js'
import { getErrorMessage, buildTrackingSummary, createLogger, withRetry } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest, ConsentDetails, AnalysisResult, SummaryFinding } from '../types.js'

const log = createLogger('AI-Analysis')

/**
 * Run comprehensive tracking analysis using Azure OpenAI.
 * Analyzes cookies, scripts, network requests, and storage to generate
 * a detailed privacy report and structured summary findings.
 * 
 * Privacy score is calculated deterministically for consistent results.
 *
 * @param cookies - Captured cookies from the browser
 * @param localStorage - localStorage items from the page
 * @param sessionStorage - sessionStorage items from the page
 * @param networkRequests - Network requests made by the page
 * @param scripts - Scripts loaded by the page
 * @param analyzedUrl - URL of the page that was analyzed
 * @param consentDetails - Optional consent dialog information for comparison
 * @returns Analysis result with full report and structured summary findings
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
    log.error('OpenAI client not configured')
    return { success: false, error: 'OpenAI not configured' }
  }

  log.info('Starting tracking analysis', { url: analyzedUrl, cookies: cookies.length, scripts: scripts.length, networkRequests: networkRequests.length })

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
    log.debug('Using deployment', { deployment })

    // Step 1: Run main analysis (required for subsequent analyses)
    log.startTimer('main-analysis')
    log.info('Running main tracking analysis...')
    const response = await withRetry(
      () => client.chat.completions.create({
        model: deployment,
        messages: [
          { role: 'system', content: TRACKING_ANALYSIS_SYSTEM_PROMPT },
          { role: 'user', content: buildTrackingAnalysisUserPrompt(trackingSummary, consentDetails) },
        ],
        max_completion_tokens: 3000,
      }),
      { context: 'Main tracking analysis' }
    )

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'
    log.endTimer('main-analysis', 'Main analysis complete')
    log.info('Analysis generated', { length: analysis.length })

    // Step 2: Calculate deterministic privacy score (consistent, no LLM variance)
    log.startTimer('score-calculation')
    const scoreBreakdown = calculatePrivacyScore(
      cookies,
      scripts,
      networkRequests,
      localStorage,
      sessionStorage,
      analyzedUrl,
      consentDetails
    )
    log.endTimer('score-calculation', 'Privacy score calculated')
    log.info('Privacy score breakdown', { 
      total: scoreBreakdown.totalScore,
      factors: scoreBreakdown.factors.length 
    })

    // Step 3: Generate summary findings from the analysis (LLM-based)
    log.startTimer('summary-generation')
    log.info('Generating summary findings...')
    
    let summaryResult = null
    try {
      summaryResult = await withRetry(
        () => client.chat.completions.create({
          model: deployment,
          messages: [
            { role: 'system', content: SUMMARY_FINDINGS_SYSTEM_PROMPT },
            { role: 'user', content: buildSummaryFindingsUserPrompt(analysis) },
          ],
          max_completion_tokens: 500,
        }),
        { context: 'Summary findings' }
      )
      log.endTimer('summary-generation', 'Summary generated')
    } catch (err) {
      log.error('Failed to generate summary', { error: getErrorMessage(err) })
    }

    // Process summary findings result
    let summaryFindings: SummaryFinding[] = []
    if (summaryResult) {
      const summaryContent = summaryResult.choices[0]?.message?.content || '[]'
      log.debug('Summary findings response', { content: summaryContent })
      try {
        // Handle potential markdown code blocks
        let jsonStr = summaryContent.trim()
        if (jsonStr.startsWith('```')) {
          jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
        }
        summaryFindings = JSON.parse(jsonStr) as SummaryFinding[]
        log.success('Summary findings parsed', { count: summaryFindings.length })
      } catch (parseError) {
        log.error('Failed to parse summary findings JSON', { error: getErrorMessage(parseError) })
        // Fallback to empty array
        summaryFindings = []
      }
    }

    // Use deterministic score from the breakdown
    const privacyScore = scoreBreakdown.totalScore
    const privacySummary = scoreBreakdown.summary

    log.success('Analysis complete', { 
      findingsCount: summaryFindings.length, 
      privacyScore,
      scoreFactors: scoreBreakdown.factors.slice(0, 3)
    })

    return {
      success: true,
      analysis,
      summaryFindings,
      privacyScore,
      privacySummary,
      scoreBreakdown,
      summary: trackingSummary,
    }
  } catch (error) {
    log.error('Analysis failed', { error: getErrorMessage(error) })
    return { success: false, error: getErrorMessage(error) }
  }
}

