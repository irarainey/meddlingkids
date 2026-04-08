<script setup lang="ts">
import { ref, watch } from 'vue'
import type { NetworkRequest } from '../../types'
import { countryFlagUrl, countryName, getResourceTypeIcon, truncateValue, stripQueryAndFragment } from '../../utils'
import { useDomainInfo } from '../../composables'

/**
 * Tab panel displaying network requests grouped by domain.
 */
const props = defineProps<{
  /** Network requests grouped by domain */
  networkByDomain: Record<string, NetworkRequest[]>
  /** Filtered network requests */
  filteredNetworkRequests: NetworkRequest[]
}>()

/** Key of the request whose query parameters are expanded (only one at a time). */
const expandedParams = ref<string | null>(null)

function toggleParams(key: string): void {
  expandedParams.value = expandedParams.value === key ? null : key
}

/** Parse query parameters from a URL. Returns empty array if none. */
function getQueryParams(url: string): { key: string; value: string }[] {
  try {
    const u = new URL(url)
    const params: { key: string; value: string }[] = []
    u.searchParams.forEach((value, key) => {
      params.push({ key, value })
    })
    return params
  } catch {
    return []
  }
}

/** Key of the request whose post data is expanded (only one at a time). */
const expandedPayload = ref<string | null>(null)

function togglePayload(key: string): void {
  expandedPayload.value = expandedPayload.value === key ? null : key
}

/** Parse post data into key-value pairs. Supports form-encoded and JSON. */
function parsePostData(data: string): { key: string; value: string }[] | null {
  // Try form-encoded (key=value&key2=value2)
  if (data.includes('=') && !data.startsWith('{') && !data.startsWith('[')) {
    try {
      const params = new URLSearchParams(data)
      const pairs: { key: string; value: string }[] = []
      params.forEach((value, key) => pairs.push({ key, value }))
      if (pairs.length > 1) return pairs
    } catch { /* fall through */ }
  }
  // Try JSON
  if (data.startsWith('{') || data.startsWith('[')) {
    try {
      const obj = JSON.parse(data)
      if (typeof obj === 'object' && obj !== null && !Array.isArray(obj)) {
        return Object.entries(obj).map(([key, value]) => ({
          key,
          value: typeof value === 'string' ? value : JSON.stringify(value),
        }))
      }
    } catch { /* fall through */ }
  }
  return null
}

const { domainInfo, fetchDomainInfo } = useDomainInfo()

watch(
  () => Object.keys(props.networkByDomain),
  (domains) => {
    if (domains.length > 0) fetchDomainInfo(domains)
  },
  { immediate: true },
)
</script>

<template>
  <div class="tab-content">
    <div v-if="filteredNetworkRequests.length === 0" class="empty-state">
      No network requests detected
    </div>
    <div v-else>
      <section class="network-overview-section">
        <h2 class="section-title">🌐 Overview</h2>
        <p class="section-subtitle">
          Network data transfers detected during the page scan.
        </p>
        <p class="ai-section-summary">
          When you visit a website, your browser makes network requests to load content
          and send data to remote servers. These requests reveal what is being shared,
          with whom, and whether it happens before or after consent. Scripts often silently
          transmit personal data — such as device fingerprints, browsing history, or unique
          identifiers — to third-party trackers without any visible indication on the page.
          This view focuses on data-transfer requests (XHR, fetch, and POST) as these are
          most likely to carry personal data. Script, stylesheet, image, font, and document
          loads are filtered out as they are the building blocks of the page and rarely
          pose a direct privacy concern.
        </p>
      </section>
      <section class="network-analysis-section">
        <h2 class="section-title">🔎 Analysis
          <span class="count-badge">{{ filteredNetworkRequests.length }} requests</span>
        </h2>
        <p class="section-subtitle">
          All data requests grouped by domain. Click on any URL to view it in a new tab.
        </p>
        <p class="section-disclaimer">🏳️ Flags show where an IP address is registered, not necessarily where the server is physically located. Services using CDNs may show a different country to where your data is actually handled.</p>
        <div class="domain-groups">
        <div v-for="(domainRequests, domain) in networkByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">
          <div class="domain-header-line">
            <span v-if="domainRequests[0]?.isThirdParty" class="third-party-badge">3rd Party</span>
            <span v-if="domainInfo[String(domain)]?.country" class="country-badge" :title="countryName(domainInfo[String(domain)]!.country!)">
              <img :src="countryFlagUrl(domainInfo[String(domain)]!.country!)" :alt="domainInfo[String(domain)]!.country!" class="country-flag" />
            </span>
            <a
              v-if="domainInfo[String(domain)]?.url"
              :href="domainInfo[String(domain)]!.url!"
              target="_blank"
              rel="noopener noreferrer"
              class="domain-name-link"
            >{{ domain }}</a>
            <span v-else>{{ domain }}</span>
            ({{ domainRequests.length }})
          </div>
          <div v-if="domainInfo[String(domain)]?.company || domainInfo[String(domain)]?.description" class="domain-org-info">
            <span class="org-caption">Vendor:</span>
            <a
              v-if="domainInfo[String(domain)]?.company && domainInfo[String(domain)]?.url"
              :href="domainInfo[String(domain)]!.url!"
              target="_blank"
              rel="noopener noreferrer"
              class="org-name-link"
            >{{ domainInfo[String(domain)]!.company }}</a>
            <span v-else-if="domainInfo[String(domain)]?.company" class="org-name">{{ domainInfo[String(domain)]!.company }}</span>
            <span v-if="domainInfo[String(domain)]?.description" class="org-description">{{ domainInfo[String(domain)]!.description }}</span>
          </div>
        </h3>
        <div v-for="(request, rIdx) in domainRequests" :key="`${domain}-${rIdx}`" class="network-item">
          <div class="network-item-header">
            <span v-if="request.preConsent" class="pre-consent-badge" title="Sent before consent was granted">Pre-consent</span>
            <span class="resource-type"
              >{{ getResourceTypeIcon(request.resourceType) }} {{ request.resourceType }}</span
            >
            <span class="request-method">{{ request.method }}</span>
            <span v-if="request.duplicateCount && request.duplicateCount > 1" class="duplicate-badge"
              >×{{ request.duplicateCount }}</span
            >
            <a :href="request.url" target="_blank" class="request-url" :title="request.url">{{ stripQueryAndFragment(request.url) }}</a>
            <button
              v-if="getQueryParams(request.url).length > 0"
              class="params-toggle"
              :title="expandedParams === `${domain}-${rIdx}` ? 'Hide parameters' : 'Show parameters'"
              @click="toggleParams(`${domain}-${rIdx}`)"
            >
              {{ getQueryParams(request.url).length }} param{{ getQueryParams(request.url).length !== 1 ? 's' : '' }}
              {{ expandedParams === `${domain}-${rIdx}` ? '▲' : '▼' }}
            </button>
          </div>
          <div v-if="expandedParams === `${domain}-${rIdx}`" class="query-params">
            <div v-for="(param, idx) in getQueryParams(request.url)" :key="idx" class="query-param">
              <span class="param-key">{{ param.key }}</span>
              <span class="param-eq">=</span>
              <span class="param-value">{{ truncateValue(decodeURIComponent(param.value), 200) }}</span>
            </div>
          </div>
          <div v-if="request.postData" class="post-data">
            <span class="post-data-label">Payload:</span>
            <button
              class="params-toggle"
              :title="expandedPayload === `${domain}-${rIdx}` ? 'Hide payload' : 'Show payload'"
              @click="togglePayload(`${domain}-${rIdx}`)"
            >
              <template v-if="parsePostData(request.postData)">
                {{ parsePostData(request.postData)!.length }} field{{ parsePostData(request.postData)!.length !== 1 ? 's' : '' }}
              </template>
              <template v-else>Data</template>
              {{ expandedPayload === `${domain}-${rIdx}` ? '▲' : '▼' }}
            </button>
            <div v-if="expandedPayload === `${domain}-${rIdx}`" class="query-params" style="margin-top: 0.3rem">
              <template v-if="parsePostData(request.postData)">
                <div v-for="(param, idx) in parsePostData(request.postData)" :key="idx" class="query-param">
                  <span class="param-key">{{ param.key }}</span>
                  <span class="param-eq">=</span>
                  <span class="param-value">{{ truncateValue(param.value, 200) }}</span>
                </div>
              </template>
              <code v-else class="post-data-value">{{ truncateValue(request.postData, 512) }}</code>
            </div>
          </div>
        </div>
      </div>
      </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.section-title {
  font-size: var(--section-title-size);
  font-weight: var(--section-title-weight);
  color: var(--section-title-color);
  margin: 0 0 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.network-overview-section {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.network-analysis-section {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.section-subtitle {
  font-size: var(--section-subtitle-size);
  color: var(--section-subtitle-color);
  margin: 0 0 0.75rem;
  line-height: 1.4;
}

.count-badge {
  font-size: var(--badge-size);
  font-weight: 600;
  background: var(--surface-code);
  color: var(--muted-light);
  padding: 0.15rem 0.5rem;
  border-radius: var(--badge-radius);
}

.ai-section-summary {
  color: var(--summary-color);
  margin: 0.25rem 0 0.75rem 0;
  font-size: var(--summary-size);
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: var(--badge-padding);
  border-radius: var(--badge-radius);
  font-size: var(--badge-size);
  font-weight: 600;
  margin-right: 0.5rem;
}

.network-item {
  padding: 0.5rem;
  border-bottom: 1px solid var(--border-separator);
  font-size: 0.95rem;
}

.network-item:last-child {
  border-bottom: none;
}

.network-item-header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
}

.resource-type {
  font-size: var(--body-size);
  color: var(--muted-light);
  min-width: 80px;
}

.request-method {
  font-size: 0.8rem;
  font-weight: 600;
  background: var(--border-separator);
  color: #c7d2fe;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.pre-consent-badge {
  font-size: var(--badge-size);
  font-weight: 600;
  background: #7c2d12;
  color: #fed7aa;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  cursor: help;
}

.duplicate-badge {
  font-size: var(--badge-size);
  font-weight: 600;
  background: #854d0e;
  color: #fef08a;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}

.request-url {
  color: var(--link-color);
  word-break: break-all;
  text-decoration: none;
  font-size: 0.9rem;
}

.request-url:hover {
  text-decoration: underline;
}

.params-toggle {
  background: var(--surface-code);
  border: 1px solid var(--border-separator);
  border-radius: 4px;
  color: #9ca3af;
  font-size: 0.75rem;
  padding: 0.1rem 0.4rem;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.15s, border-color 0.15s;
}

.params-toggle:hover {
  color: #e0e7ff;
  border-color: #6366f1;
}

.query-params {
  margin-top: 0.3rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface-code);
  border-radius: 4px;
  border-left: 3px solid #6366f1;
  font-size: 0.8rem;
  max-height: 200px;
  overflow-y: auto;
}

.query-param {
  display: flex;
  gap: 0.25rem;
  padding: 0.15rem 0;
  border-bottom: 1px solid var(--border-separator);
  word-break: break-all;
}

.query-param:last-child {
  border-bottom: none;
}

.param-key {
  color: #c7d2fe;
  font-weight: 600;
  flex-shrink: 0;
}

.param-eq {
  color: #6b7280;
  flex-shrink: 0;
}

.param-value {
  color: #d1d5db;
}

.post-data {
  margin-top: 0.35rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface-code);
  border-radius: 4px;
  border-left: 3px solid #f59e0b;
}

.post-data-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #f59e0b;
  margin-right: 0.5rem;
}

.post-data-value {
  font-size: var(--body-size);
  color: #d1d5db;
  word-break: break-all;
  white-space: pre-wrap;
}

/* ── Domain Organisation Info ────────────────── */
.domain-org-info {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem;
  font-size: 0.85rem;
  font-weight: 400;
  margin-top: 0.25rem;
  padding-top: 0.25rem;
}

.org-caption {
  color: var(--muted-color);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.org-name-link {
  color: var(--link-color);
  text-decoration: none;
  font-weight: 600;
  font-size: var(--body-size);
}

.org-name-link:hover {
  text-decoration: underline;
  color: var(--link-hover);
}

.domain-name-link {
  color: inherit;
  text-decoration: none;
}

.domain-name-link:hover {
  text-decoration: underline;
  color: var(--link-hover);
}

.org-name {
  color: var(--link-color);
  font-weight: 600;
  font-size: var(--body-size);
}

.org-description {
  color: var(--muted-color);
  font-size: 0.82rem;
  font-weight: 400;
}

.org-name-link + .org-description::before,
.org-name + .org-description::before {
  content: '·';
  margin-right: 0.35rem;
  color: #4b5563;
}
</style>
