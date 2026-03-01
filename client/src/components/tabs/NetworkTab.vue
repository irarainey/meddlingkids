<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { NetworkRequest } from '../../types'
import { getResourceTypeIcon, truncateValue } from '../../utils'

/**
 * Tab panel displaying network requests grouped by domain.
 */
const props = defineProps<{
  /** Network requests grouped by domain */
  networkByDomain: Record<string, NetworkRequest[]>
  /** Filtered network requests */
  filteredNetworkRequests: NetworkRequest[]
}>()

/** Cached domain info keyed by domain. */
const domainInfo = reactive<Record<string, { company: string | null; description: string | null; url: string | null }>>({})

/** Fetch company/description info for all visible domains. */
async function fetchDomainInfo(domains: string[]): Promise<void> {
  const unknown = domains.filter((d) => !(d in domainInfo))
  if (unknown.length === 0) return

  try {
    const apiBase = import.meta.env.VITE_API_URL || ''
    const response = await fetch(`${apiBase}/api/domain-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domains: unknown }),
    })
    if (response.ok) {
      const data = await response.json()
      for (const [domain, info] of Object.entries(data)) {
        domainInfo[domain] = info as { company: string | null; description: string | null; url: string | null }
      }
    }
  } catch {
    // Silently fail — enrichment is non-critical
  }
}

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
    <div v-else class="domain-groups">
      <p class="filter-note">
        Showing {{ filteredNetworkRequests.length }} data requests (XHR, fetch, and POST only).
        Script, stylesheet, image, font, and document loads are excluded.
      </p>
      <div v-for="(domainRequests, domain) in networkByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">
          <div class="domain-header-line">
            <span v-if="domainRequests[0]?.isThirdParty" class="third-party-badge">3rd Party</span>
            {{ domain }} ({{ domainRequests.length }})
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
        <div v-for="request in domainRequests" :key="`${request.method}-${request.url}`" class="network-item">
          <div class="network-item-header">
            <span v-if="request.preConsent" class="pre-consent-badge" title="Sent before consent was granted">Pre-consent</span>
            <span class="resource-type"
              >{{ getResourceTypeIcon(request.resourceType) }} {{ request.resourceType }}</span
            >
            <span class="request-method">{{ request.method }}</span>
            <span v-if="request.duplicateCount && request.duplicateCount > 1" class="duplicate-badge"
              >×{{ request.duplicateCount }}</span
            >
            <a :href="request.url" target="_blank" class="request-url">{{ request.url }}</a>
          </div>
          <div v-if="request.postData" class="post-data">
            <span class="post-data-label">Payload:</span>
            <code class="post-data-value" :title="request.postData">{{ truncateValue(request.postData, 512) }}</code>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-note {
  font-size: var(--body-size);
  color: var(--muted-light);
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--surface-panel);
  border-radius: 6px;
  border-left: 3px solid var(--border-accent);
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
