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
import { getErrorMessage, buildTrackingSummary, createLogger } from '../utils/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest, ConsentDetails, AnalysisResult } from '../types.js'

const log = createLogger('AI-Analysis')

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
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: TRACKING_ANALYSIS_SYSTEM_PROMPT },
        { role: 'user', content: buildTrackingAnalysisUserPrompt(trackingSummary, consentDetails) },
      ],
      max_completion_tokens: 3000,
    })

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'
    log.endTimer('main-analysis', 'Main analysis complete')
    log.info('Analysis generated', { length: analysis.length })

    // Step 2: Run high risks and privacy score in PARALLEL (both depend on main analysis)
    log.startTimer('parallel-analysis')
    log.info('Running summary and score generation in parallel...')
    
    const [highRisksResult, scoreResult] = await Promise.all([
      // High risks summary
      (async () => {
        log.startTimer('summary-generation')
        try {
          const result = await client.chat.completions.create({
            model: deployment,
            messages: [
              { role: 'system', content: HIGH_RISKS_SYSTEM_PROMPT },
              { role: 'user', content: buildHighRisksUserPrompt(analysis) },
            ],
            max_completion_tokens: 500,
          })
          log.endTimer('summary-generation', 'Summary generated')
          return result
        } catch (err) {
          log.error('Failed to generate summary', { error: getErrorMessage(err) })
          return null
        }
      })(),
      
      // Privacy score
      (async () => {
        log.startTimer('score-generation')
        try {
          const result = await client.chat.completions.create({
            model: deployment,
            messages: [
              { role: 'system', content: PRIVACY_SCORE_SYSTEM_PROMPT },
              { role: 'user', content: buildPrivacyScoreUserPrompt(analysis, analyzedUrl) },
            ],
            max_completion_tokens: 200,
          })
          log.endTimer('score-generation', 'Score generated')
          return result
        } catch (err) {
          log.error('Failed to generate privacy score', { error: getErrorMessage(err) })
          return null
        }
      })()
    ])
    
    log.endTimer('parallel-analysis', 'Parallel analysis complete')

    // Process summary content result
    const summaryContent = highRisksResult?.choices[0]?.message?.content || ''
    if (summaryContent) {
      log.success('Summary content extracted', { length: summaryContent.length })
    }

    // Process privacy score result
    let privacyScore: number | undefined
    let privacySummary: string | undefined
    
    if (scoreResult) {
      const scoreContent = scoreResult.choices[0]?.message?.content || ''
      log.debug('Privacy score response', { content: scoreContent })
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
        
        log.success('Privacy score calculated', { score: privacyScore })
      } catch (parseError) {
        log.error('Failed to parse privacy score JSON', { error: getErrorMessage(parseError) })
        privacyScore = 50
        privacySummary = 'Unable to generate summary'
      }
    }

    log.success('Analysis complete', { summaryLength: summaryContent.length, privacyScore })

    return {
      success: true,
      analysis,
      summaryContent,
      privacyScore,
      privacySummary,
      summary: trackingSummary,
    }
  } catch (error) {
    log.error('Analysis failed', { error: getErrorMessage(error) })
    return { success: false, error: getErrorMessage(error) }
  }
}
