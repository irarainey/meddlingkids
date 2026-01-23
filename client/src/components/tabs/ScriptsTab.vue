<script setup lang="ts">
import type { TrackedScript } from '../../types'

/**
 * Tab panel displaying scripts grouped by domain.
 */
defineProps<{
  /** Scripts grouped by domain */
  scriptsByDomain: Record<string, TrackedScript[]>
  /** Total number of scripts */
  scriptCount: number
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="scriptCount === 0" class="empty-state">No scripts detected yet</div>
    <div v-else class="domain-groups">
      <div v-for="(domainScripts, domain) in scriptsByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">{{ domain }} ({{ domainScripts.length }})</h3>
        <div v-for="script in domainScripts" :key="script.url" class="script-item">
          <a :href="script.url" target="_blank" class="script-url">{{ script.url }}</a>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.script-item {
  padding: 0.5rem;
  border-bottom: 1px solid #eee;
  font-size: 0.85rem;
}

.script-item:last-child {
  border-bottom: none;
}

.script-url {
  color: #2563eb;
  word-break: break-all;
  text-decoration: none;
}

.script-url:hover {
  text-decoration: underline;
}
</style>
