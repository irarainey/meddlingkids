/**
 * @fileoverview Shared composable for fetching and caching domain info.
 *
 * Module-level state ensures all components share a single cache,
 * avoiding redundant API calls when multiple tabs need the same data.
 */

import { reactive } from 'vue'
import { API_BASE } from '../utils/api'

export interface DomainInfoEntry {
  company: string | null
  description: string | null
  url?: string | null
  country?: string | null
}

const cache = reactive<Record<string, DomainInfoEntry>>({})
const BATCH_SIZE = 30

export function useDomainInfo() {
  async function fetchDomainInfo(domains: string[]): Promise<void> {
    const unknown = domains.filter((d) => !(d in cache))
    if (unknown.length === 0) return

    for (let i = 0; i < unknown.length; i += BATCH_SIZE) {
      const batch = unknown.slice(i, i + BATCH_SIZE)
      try {
        const response = await fetch(`${API_BASE}/api/domain-info`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ domains: batch }),
        })
        if (response.ok) {
          const data = await response.json()
          for (const [domain, info] of Object.entries(data)) {
            if (typeof info === 'object' && info !== null) {
              const entry = info as Record<string, unknown>
              cache[domain] = {
                company: typeof entry.company === 'string' ? entry.company : null,
                description: typeof entry.description === 'string' ? entry.description : null,
                url: typeof entry.url === 'string' ? entry.url : null,
                country: typeof entry.country === 'string' ? entry.country : null,
              }
            }
          }
        }
      } catch (err) {
        console.warn('[DomainInfo] Failed to fetch domain info batch:', err)
      }
    }
  }

  return {
    domainInfo: cache,
    fetchDomainInfo,
  }
}
