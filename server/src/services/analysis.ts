// AI-powered tracking analysis service

import { getOpenAIClient, getDeploymentName } from './openai.js'
import {
  TRACKING_ANALYSIS_SYSTEM_PROMPT,
  HIGH_RISKS_SYSTEM_PROMPT,
  buildTrackingAnalysisUserPrompt,
  buildHighRisksUserPrompt,
} from '../prompts/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest, ConsentDetails, AnalysisResult } from '../types.js'

// Run comprehensive tracking analysis using Azure OpenAI
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
    // Group data by domain for analysis
    const domainData: Record<
      string,
      {
        cookies: TrackedCookie[]
        scripts: TrackedScript[]
        networkRequests: NetworkRequest[]
      }
    > = {}

    for (const cookie of cookies || []) {
      if (!domainData[cookie.domain]) {
        domainData[cookie.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[cookie.domain].cookies.push(cookie)
    }

    for (const script of scripts || []) {
      if (!domainData[script.domain]) {
        domainData[script.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[script.domain].scripts.push(script)
    }

    for (const request of networkRequests || []) {
      if (!domainData[request.domain]) {
        domainData[request.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[request.domain].networkRequests.push(request)
    }

    const trackingSummary = {
      analyzedUrl,
      totalCookies: cookies?.length || 0,
      totalScripts: scripts?.length || 0,
      totalNetworkRequests: networkRequests?.length || 0,
      localStorageItems: localStorage?.length || 0,
      sessionStorageItems: sessionStorage?.length || 0,
      thirdPartyDomains: Object.keys(domainData).filter((domain) => {
        try {
          const pageBaseDomain = new URL(analyzedUrl).hostname.split('.').slice(-2).join('.')
          const domainBase = domain.split('.').slice(-2).join('.')
          return pageBaseDomain !== domainBase
        } catch {
          return true
        }
      }),
      domainBreakdown: Object.entries(domainData).map(([domain, data]) => ({
        domain,
        cookieCount: data.cookies.length,
        cookieNames: data.cookies.map((c) => c.name),
        scriptCount: data.scripts.length,
        requestCount: data.networkRequests.length,
        requestTypes: [...new Set(data.networkRequests.map((r) => r.resourceType))],
      })),
      localStorage:
        localStorage?.map((item: StorageItem) => ({
          key: item.key,
          valuePreview: item.value.substring(0, 100),
        })) || [],
      sessionStorage:
        sessionStorage?.map((item: StorageItem) => ({
          key: item.key,
          valuePreview: item.value.substring(0, 100),
        })) || [],
    }

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
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
}
