<script setup lang="ts">
import type { TrackedScript, ScriptGroup } from '../../types'

/** Return the URL without query string or fragment for display purposes. */
function baseUrl(url: string): string {
  try {
    const u = new URL(url)
    return u.origin + u.pathname
  } catch {
    const noQuery = url.indexOf('?') >= 0 ? url.substring(0, url.indexOf('?')) : url
    const noFrag = noQuery.indexOf('#') >= 0 ? noQuery.substring(0, noQuery.indexOf('#')) : noQuery
    return noFrag
  }
}

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
    <div v-if="scriptCount === 0" class="empty-state">No scripts detected</div>
    <div v-else>
      <section class="scripts-overview-section">
        <h2 class="section-title">📜 Overview
          <span class="count-badge">{{ scriptCount }} scripts</span>
        </h2>
        <p class="section-subtitle">
          JavaScript files loaded during the page scan.
        </p>
        <p class="ai-section-summary">
          Every website relies on JavaScript to add interactivity, but many of the scripts
          loaded come from third parties — advertising networks, analytics providers, and
          data brokers. These scripts run with full access to the page and can read cookies,
          monitor your clicks, record form inputs, and send data to remote servers. Reviewing
          what scripts are loaded helps reveal who has a presence on the site and what they
          may be doing behind the scenes.
        </p>
      </section>

      <!-- Script Groups (application chunks, vendor bundles, etc.) -->
      <section v-if="scriptGroups && scriptGroups.length > 0" class="scripts-analysis-section">
        <h2 class="section-title">📦 Grouped Scripts</h2>
        <p class="section-subtitle">
          Similar scripts bundled together, such as application chunks and vendor libraries.
        </p>
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
                <a :href="url" target="_blank" :title="url">{{ baseUrl(url) }}</a>
              </li>
            </ul>
          </details>
        </div>
      </section>

      <!-- Individual Scripts by Domain -->
      <section class="scripts-analysis-section">
        <h2 class="section-title">🔎 Analysis</h2>
        <p class="section-subtitle">
          All individual scripts grouped by domain. Click on any URL to view it in a new tab.
        </p>
        <div class="domain-groups">
        <div v-for="(domainScripts, domain) in scriptsByDomain" :key="domain" class="domain-group">
          <template v-if="domainScripts.some(s => !s.isGrouped)">
            <h3 class="domain-header">{{ domain }} ({{ domainScripts.filter(s => !s.isGrouped).length }})</h3>
            <div v-for="script in domainScripts.filter(s => !s.isGrouped)" :key="script.url" class="script-item">
              <div class="script-main">
                <a :href="script.url" target="_blank" class="script-url" :title="script.url">{{ baseUrl(script.url) }}</a>
                <span v-if="script.description" class="script-description">{{ script.description }}</span>
              </div>
            </div>
          </template>
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

.section-subtitle {
  font-size: var(--section-subtitle-size);
  color: var(--section-subtitle-color);
  margin: 0 0 0.75rem;
  line-height: 1.4;
}

.ai-section-summary {
  color: var(--summary-color);
  margin: 0.25rem 0 0.75rem 0;
  font-size: var(--summary-size);
}

.count-badge {
  font-size: var(--badge-size);
  font-weight: 600;
  background: var(--surface-code);
  color: var(--muted-light);
  padding: 0.15rem 0.5rem;
  border-radius: var(--badge-radius);
}

.scripts-overview-section {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.scripts-analysis-section {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.script-group {
  background: var(--surface-panel);
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
  color: var(--muted-light);
  font-size: 0.9rem;
  background: #374151;
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
}

.group-description {
  color: var(--body-color);
  font-size: var(--body-size);
  margin-bottom: 0.25rem;
}

.group-domain {
  color: #6b7280;
  font-size: 0.9rem;
}

.group-examples {
  margin-top: 0.5rem;
  font-size: 0.9rem;
}

.group-examples summary {
  color: var(--link-color);
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
  color: var(--muted-light);
  text-decoration: none;
  word-break: break-all;
}

.example-url a:hover {
  text-decoration: underline;
}

.script-item {
  padding: 0.5rem;
  border-bottom: 1px solid var(--border-separator);
  font-size: 0.95rem;
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
  color: var(--link-color);
  word-break: break-all;
  text-decoration: none;
}

.script-url:hover {
  text-decoration: underline;
}

.script-description {
  color: var(--body-color);
  font-size: 0.9rem;
  font-style: italic;
}
</style>
