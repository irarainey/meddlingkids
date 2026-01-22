/**
 * @fileoverview Utilities for building tracking data summaries.
 * Aggregates cookies, scripts, and network requests by domain
 * and prepares data for LLM analysis.
 */

import type {
  TrackedCookie,
  TrackedScript,
  NetworkRequest,
  StorageItem,
  DomainData,
  DomainBreakdown,
  TrackingSummary,
} from '../types.js'

/**
 * Group tracking data (cookies, scripts, network requests) by domain.
 * Creates a lookup table for analyzing which domains are tracking users.
 *
 * @param cookies - Array of tracked cookies
 * @param scripts - Array of detected scripts
 * @param networkRequests - Array of network requests
 * @returns Object mapping domain names to their tracking data
 */
function groupByDomain(
  cookies: TrackedCookie[],
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[]
): Record<string, DomainData> {
  const domainData: Record<string, DomainData> = {}

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

  return domainData
}

/**
 * Identify third-party domains relative to the analyzed URL.
 * Compares base domains to determine which are external trackers.
 *
 * @param domainData - Grouped tracking data by domain
 * @param analyzedUrl - The URL of the page being analyzed
 * @returns Array of domain names that are third-party
 */
function getThirdPartyDomains(domainData: Record<string, DomainData>, analyzedUrl: string): string[] {
  return Object.keys(domainData).filter((domain) => {
    try {
      const pageBaseDomain = new URL(analyzedUrl).hostname.split('.').slice(-2).join('.')
      const domainBase = domain.split('.').slice(-2).join('.')
      return pageBaseDomain !== domainBase
    } catch {
      return true
    }
  })
}

/**
 * Build a summary breakdown for each domain's tracking activity.
 * Extracts counts and types of tracking elements per domain.
 *
 * @param domainData - Grouped tracking data by domain
 * @returns Array of domain breakdown summaries
 */
function buildDomainBreakdown(domainData: Record<string, DomainData>): DomainBreakdown[] {
  return Object.entries(domainData).map(([domain, data]) => ({
    domain,
    cookieCount: data.cookies.length,
    cookieNames: data.cookies.map((c) => c.name),
    scriptCount: data.scripts.length,
    requestCount: data.networkRequests.length,
    requestTypes: [...new Set(data.networkRequests.map((r) => r.resourceType))],
  }))
}

/**
 * Build preview of storage items for analysis.
 * Truncates values to first 100 characters to reduce payload size.
 *
 * @param items - Array of storage items
 * @returns Array of objects with key and truncated value preview
 */
function buildStoragePreview(items: StorageItem[]): { key: string; valuePreview: string }[] {
  return (items || []).map((item) => ({
    key: item.key,
    valuePreview: item.value.substring(0, 100),
  }))
}

/**
 * Build a complete tracking summary for LLM privacy analysis.
 * Aggregates all tracking data into a structured format suitable for AI processing.
 *
 * @param cookies - Array of captured cookies
 * @param scripts - Array of detected scripts
 * @param networkRequests - Array of network requests
 * @param localStorage - Array of localStorage items
 * @param sessionStorage - Array of sessionStorage items
 * @param analyzedUrl - The URL of the page being analyzed
 * @returns Complete tracking summary with counts, domains, and breakdowns
 */
export function buildTrackingSummary(
  cookies: TrackedCookie[],
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[],
  localStorage: StorageItem[],
  sessionStorage: StorageItem[],
  analyzedUrl: string
): TrackingSummary {
  const domainData = groupByDomain(cookies, scripts, networkRequests)

  return {
    analyzedUrl,
    totalCookies: cookies?.length || 0,
    totalScripts: scripts?.length || 0,
    totalNetworkRequests: networkRequests?.length || 0,
    localStorageItems: localStorage?.length || 0,
    sessionStorageItems: sessionStorage?.length || 0,
    thirdPartyDomains: getThirdPartyDomains(domainData, analyzedUrl),
    domainBreakdown: buildDomainBreakdown(domainData),
    localStorage: buildStoragePreview(localStorage),
    sessionStorage: buildStoragePreview(sessionStorage),
  }
}
