<script setup lang="ts">
import type { NetworkRequest } from '../../types'
import { getResourceTypeIcon, truncateValue } from '../../utils'

/**
 * Tab panel displaying network requests grouped by domain.
 */
defineProps<{
  /** Network requests grouped by domain */
  networkByDomain: Record<string, NetworkRequest[]>
  /** Filtered network requests */
  filteredNetworkRequests: NetworkRequest[]
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="filteredNetworkRequests.length === 0" class="empty-state">
      No network requests detected yet
    </div>
    <div v-else class="domain-groups">
      <p class="filter-note">
        Showing {{ filteredNetworkRequests.length }} data requests (XHR, fetch, and POST only).
        Script, stylesheet, image, font, and document loads are excluded.
      </p>
      <div v-for="(domainRequests, domain) in networkByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">
          <span v-if="domainRequests[0]?.isThirdParty" class="third-party-badge">3rd Party</span>
          {{ domain }} ({{ domainRequests.length }})
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
  font-size: 0.85rem;
  color: #9ca3af;
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #2a2f45;
  border-radius: 6px;
  border-left: 3px solid #6366f1;
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.8rem;
  margin-right: 0.5rem;
}

.network-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
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
  font-size: 0.85rem;
  color: #9ca3af;
  min-width: 80px;
}

.request-method {
  font-size: 0.8rem;
  font-weight: 600;
  background: #3d4663;
  color: #c7d2fe;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.pre-consent-badge {
  font-size: 0.75rem;
  font-weight: 600;
  background: #7c2d12;
  color: #fed7aa;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  cursor: help;
}

.duplicate-badge {
  font-size: 0.8rem;
  font-weight: 600;
  background: #854d0e;
  color: #fef08a;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
}

.request-url {
  color: #60a5fa;
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
  background: #2a2f45;
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
  font-size: 0.85rem;
  color: #d1d5db;
  word-break: break-all;
  white-space: pre-wrap;
}
</style>
