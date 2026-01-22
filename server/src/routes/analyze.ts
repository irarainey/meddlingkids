// Analysis endpoint for manual tracking analysis

import type { Request, Response } from 'express'
import { getOpenAIClient, getDeploymentName } from '../services/openai.js'
import { TRACKING_ANALYSIS_SYSTEM_PROMPT, buildTrackingAnalysisUserPrompt } from '../prompts/index.js'
import type { TrackedCookie, TrackedScript, StorageItem, NetworkRequest } from '../types.js'

interface AnalyzeRequestBody {
  cookies: TrackedCookie[]
  localStorage: StorageItem[]
  sessionStorage: StorageItem[]
  networkRequests: NetworkRequest[]
  scripts: TrackedScript[]
  pageUrl: string
}

// Analyze tracking data with Azure OpenAI
export async function analyzeHandler(req: Request, res: Response): Promise<void> {
  const { cookies, localStorage, sessionStorage, networkRequests, scripts, pageUrl: analyzedUrl } =
    req.body as AnalyzeRequestBody

  const client = getOpenAIClient()
  if (!client) {
    res.status(503).json({
      error:
        'Azure OpenAI not configured. Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT in .env file.',
    })
    return
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

    // Group cookies by domain
    for (const cookie of cookies || []) {
      if (!domainData[cookie.domain]) {
        domainData[cookie.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[cookie.domain].cookies.push(cookie)
    }

    // Group scripts by domain
    for (const script of scripts || []) {
      if (!domainData[script.domain]) {
        domainData[script.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[script.domain].scripts.push(script)
    }

    // Group network requests by domain
    for (const request of networkRequests || []) {
      if (!domainData[request.domain]) {
        domainData[request.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[request.domain].networkRequests.push(request)
    }

    // Prepare summary for LLM
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
        { role: 'user', content: buildTrackingAnalysisUserPrompt(trackingSummary) },
      ],
      max_completion_tokens: 2000,
    })

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'

    res.json({
      success: true,
      analysis,
      summary: trackingSummary,
    })
  } catch (error) {
    console.error('Analysis error:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: `Analysis failed: ${message}` })
  }
}
