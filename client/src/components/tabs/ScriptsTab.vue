<script setup lang="ts">
import type { TrackedScript, ScriptGroup } from '../../types'

/**
 * Tab panel displaying scripts grouped by domain.
 * Also shows script groups for similar scripts (e.g., application chunks).
 */
defineProps<{
  /** Scripts grouped by domain */
  scriptsByDomain: Record<string, TrackedScript[]>
  /** Total number of scripts */
  scriptCount: number
  /** Groups of similar scripts */
  scriptGroups?: ScriptGroup[]
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="scriptCount === 0" class="empty-state">No scripts detected yet</div>
    <div v-else class="domain-groups">
      <!-- Script Groups (application chunks, vendor bundles, etc.) -->
      <div v-if="scriptGroups && scriptGroups.length > 0" class="grouped-scripts-section">
        <h3 class="section-header">Grouped Scripts</h3>
        <div v-for="group in scriptGroups" :key="group.id" class="script-group">
          <div class="group-header">
            <span class="group-name">{{ group.name }}</span>
            <span class="group-count">{{ group.count }} scripts</span>
          </div>
          <div class="group-description">{{ group.description }}</div>
          <div class="group-domain">Domain: {{ group.domain }}</div>
          <details class="group-examples">
            <summary>Show examples</summary>
            <ul>
              <li v-for="url in group.exampleUrls" :key="url" class="example-url">
                <a :href="url" target="_blank">{{ url }}</a>
              </li>
            </ul>
          </details>
        </div>
      </div>

      <!-- Individual Scripts by Domain -->
      <h3 v-if="scriptGroups && scriptGroups.length > 0" class="section-header">Individual Scripts</h3>
      <div v-for="(domainScripts, domain) in scriptsByDomain" :key="domain" class="domain-group">
        <!-- Only show non-grouped scripts -->
        <template v-if="domainScripts.some(s => !s.isGrouped)">
          <h3 class="domain-header">{{ domain }} ({{ domainScripts.filter(s => !s.isGrouped).length }})</h3>
          <div v-for="script in domainScripts.filter(s => !s.isGrouped)" :key="script.url" class="script-item">
            <div class="script-main">
              <a :href="script.url" target="_blank" class="script-url">{{ script.url }}</a>
              <span v-if="script.description" class="script-description">{{ script.description }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.section-header {
  color: #f0f0f0;
  font-size: 1rem;
  font-weight: 600;
  margin: 1rem 0 0.5rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #4a5568;
}

.grouped-scripts-section {
  margin-bottom: 1.5rem;
}

.script-group {
  background: #2a3142;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.25rem;
}

.group-name {
  color: #e0e0e0;
  font-weight: 500;
}

.group-count {
  color: #9ca3af;
  font-size: 0.8rem;
  background: #374151;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
}

.group-description {
  color: #9ca3af;
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
}

.group-domain {
  color: #6b7280;
  font-size: 0.8rem;
}

.group-examples {
  margin-top: 0.5rem;
  font-size: 0.8rem;
}

.group-examples summary {
  color: #60a5fa;
  cursor: pointer;
}

.group-examples ul {
  margin: 0.25rem 0 0 1rem;
  padding: 0;
  list-style: none;
}

.example-url {
  margin: 0.25rem 0;
}

.example-url a {
  color: #9ca3af;
  text-decoration: none;
  word-break: break-all;
}

.example-url a:hover {
  text-decoration: underline;
}

.script-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
  font-size: 0.85rem;
}

.script-item:last-child {
  border-bottom: none;
}

.script-main {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.script-url {
  color: #60a5fa;
  word-break: break-all;
  text-decoration: none;
}

.script-url:hover {
  text-decoration: underline;
}

.script-description {
  color: #9ca3af;
  font-size: 0.8rem;
  font-style: italic;
}
</style>
