<script setup lang="ts">
import type { NetworkRequest } from '../../types'
import { getResourceTypeIcon } from '../../utils'

/**
 * Tab panel displaying network requests grouped by domain.
 */
defineProps<{
  /** Network requests grouped by domain */
  networkByDomain: Record<string, NetworkRequest[]>
  /** Filtered network requests */
  filteredNetworkRequests: NetworkRequest[]
  /** Count of unique third-party domains */
  thirdPartyDomainCount: number
  /** Whether to show only third-party requests */
  showOnlyThirdParty: boolean
}>()

const emit = defineEmits<{
  /** Emitted when the filter checkbox changes */
  'update:showOnlyThirdParty': [value: boolean]
}>()

function onFilterChange(event: Event) {
  const target = event.target as HTMLInputElement
  emit('update:showOnlyThirdParty', target.checked)
}
</script>

<template>
  <div class="tab-content">
    <div class="filter-bar">
      <label class="filter-checkbox">
        <input type="checkbox" :checked="showOnlyThirdParty" @change="onFilterChange" />
        Show only third-party requests ({{ thirdPartyDomainCount }} domains)
      </label>
    </div>
    <div v-if="filteredNetworkRequests.length === 0" class="empty-state">
      No network requests detected yet
    </div>
    <div v-else class="domain-groups">
      <div v-for="(domainRequests, domain) in networkByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">
          <span v-if="domainRequests[0]?.isThirdParty" class="third-party-badge">3rd Party</span>
          {{ domain }} ({{ domainRequests.length }})
        </h3>
        <div v-for="request in domainRequests" :key="request.url" class="network-item">
          <span class="resource-type"
            >{{ getResourceTypeIcon(request.resourceType) }} {{ request.resourceType }}</span
          >
          <span class="request-method">{{ request.method }}</span>
          <a :href="request.url" target="_blank" class="request-url">{{ request.url }}</a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-bar {
  padding: 0.5rem;
  background: #2a2f45;
  border-bottom: 1px solid #3d4663;
}

.filter-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  cursor: pointer;
  color: #e0e7ff;
}

.filter-checkbox input {
  cursor: pointer;
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  margin-right: 0.5rem;
}

.network-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
  font-size: 0.85rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
}

.network-item:last-child {
  border-bottom: none;
}

.resource-type {
  font-size: 0.75rem;
  color: #9ca3af;
  min-width: 80px;
}

.request-method {
  font-size: 0.7rem;
  font-weight: 600;
  background: #3d4663;
  color: #c7d2fe;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.request-url {
  color: #60a5fa;
  word-break: break-all;
  text-decoration: none;
  font-size: 0.8rem;
}

.request-url:hover {
  text-decoration: underline;
}
</style>
