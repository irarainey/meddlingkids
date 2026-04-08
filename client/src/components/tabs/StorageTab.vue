<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { StorageItem, StorageInfo, StructuredReport } from '../../types'
import { truncateValue, stripMarkdown, purposeLabel, riskClass, API_BASE } from '../../utils'

/**
 * Tab panel displaying localStorage and sessionStorage items.
 * Supports click-to-expand storage key information lookup via the server API.
 */
const props = defineProps<{
  /** localStorage items */
  localStorage: StorageItem[]
  /** sessionStorage items */
  sessionStorage: StorageItem[]
  /** Structured report for the AI storage analysis section */
  structuredReport?: StructuredReport | null
}>()

/** Cache of storage info results, keyed by "storageType|key". */
const storageInfoCache = reactive<Record<string, StorageInfo>>({})

/** Set of storage keys currently being loaded. */
const loadingKeys = reactive<Set<string>>(new Set())

/** Set of storage keys that are expanded (info panel visible). */
const expandedKeys = reactive<Set<string>>(new Set())

/** Cache of deterministic storage key hints, keyed by key name. */
const storageKeyHints = reactive<Record<string, { setBy: string | null; description: string | null }>>({})

/** Fetch known descriptions for storage keys from the deterministic endpoint. */
async function fetchStorageKeyHints(keys: string[]): Promise<void> {
  const unknown = keys.filter((k) => !(k in storageKeyHints))
  if (unknown.length === 0) return

  try {
    const response = await fetch(`${API_BASE}/api/storage-key-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys: unknown }),
    })
    if (response.ok) {
      const data = await response.json()
      for (const [key, info] of Object.entries(data)) {
        storageKeyHints[key] = info as { setBy: string | null; description: string | null }
      }
    }
  } catch {
    // Silently fail — hints are non-critical
  }
}

watch(
  () => [...props.localStorage.map((i) => i.key), ...props.sessionStorage.map((i) => i.key)],
  (keys) => {
    if (keys.length > 0) fetchStorageKeyHints(keys)
  },
  { immediate: true },
)

function itemKey(storageType: string, item: StorageItem): string {
  return `${storageType}|${item.key}`
}

async function toggleStorageInfo(storageType: string, item: StorageItem): Promise<void> {
  const key = itemKey(storageType, item)

  // If already expanded, just collapse
  if (expandedKeys.has(key)) {
    expandedKeys.delete(key)
    return
  }

  // Expand the panel
  expandedKeys.add(key)

  // If we already have the info cached, nothing more to do
  if (storageInfoCache[key]) {
    return
  }

  // Fetch from server
  loadingKeys.add(key)
  try {
    const response = await fetch(`${API_BASE}/api/storage-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key: item.key,
        storageType,
        value: item.value,
      }),
    })
    if (response.ok) {
      storageInfoCache[key] = await response.json()
    }
  } catch {
    // Silently fail — the user can try again
  } finally {
    loadingKeys.delete(key)
  }
}

function isUnknownPurpose(info: StorageInfo | undefined): boolean {
  return info?.purpose === 'unknown'
}

</script>

<template>
  <div class="tab-content">
    <div v-if="localStorage.length === 0 && sessionStorage.length === 0 && !(structuredReport && (structuredReport.storageAnalysis.localStorageCount > 0 || structuredReport.storageAnalysis.sessionStorageCount > 0))" class="empty-state">
      No storage data detected
    </div>

    <!-- ── Overview ──────────────────────────────── -->
    <section
      v-if="structuredReport && (structuredReport.storageAnalysis.localStorageCount > 0
        || structuredReport.storageAnalysis.sessionStorageCount > 0)"
      class="ai-storage-analysis"
    >
      <h2 class="ai-section-title">💾 Overview</h2>
      <p class="ai-section-subtitle">
        Analysis of localStorage and sessionStorage usage patterns determined
        by AI examination of key names and values.
      </p>
      <p class="ai-section-summary">
        Websites can store data directly in your browser using two mechanisms:
        localStorage persists indefinitely (even after closing the browser),
        while sessionStorage is cleared when the tab is closed.
        Unlike cookies, storage data is never sent to servers automatically — but scripts
        on the page can read it freely. Some companies prefer storage over cookies because
        it has no size limits, is harder for users to discover or clear, and is not affected
        by cookie-blocking browser settings or consent tools.
      </p>
      <p v-if="structuredReport.storageAnalysis.summary" class="ai-section-summary">
        {{ stripMarkdown(structuredReport.storageAnalysis.summary) }}
      </p>
      <div class="storage-ai-stats">
        <div class="ai-stat-card">
          <span class="ai-stat-value">{{ structuredReport.storageAnalysis.localStorageCount }}</span>
          <span class="storage-type-badge local">localStorage</span>
        </div>
        <div class="ai-stat-card">
          <span class="ai-stat-value">{{ structuredReport.storageAnalysis.sessionStorageCount }}</span>
          <span class="storage-type-badge session">sessionStorage</span>
        </div>
      </div>
      <hr v-if="structuredReport.storageAnalysis.localStorageConcerns.length > 0 || structuredReport.storageAnalysis.sessionStorageConcerns.length > 0" class="section-divider">
      <div v-if="structuredReport.storageAnalysis.localStorageConcerns.length > 0 || structuredReport.storageAnalysis.sessionStorageConcerns.length > 0" class="storage-ai-concerns">
        <h3>⚠️ Concerning Storage</h3>
        <div v-if="structuredReport.storageAnalysis.localStorageConcerns.length > 0" class="concern-group">
          <span class="storage-type-badge local">localStorage</span>
          <ul>
            <li v-for="(concern, i) in structuredReport.storageAnalysis.localStorageConcerns" :key="i">{{ stripMarkdown(concern) }}</li>
          </ul>
        </div>
        <div v-if="structuredReport.storageAnalysis.sessionStorageConcerns.length > 0" class="concern-group">
          <span class="storage-type-badge session">sessionStorage</span>
          <ul>
            <li v-for="(concern, i) in structuredReport.storageAnalysis.sessionStorageConcerns" :key="i">{{ stripMarkdown(concern) }}</li>
          </ul>
        </div>
      </div>
    </section>

    <!-- ── Analysis ──────────────────────────────── -->
    <section v-if="localStorage.length > 0 || sessionStorage.length > 0" class="storage-analysis-section">
      <h2 class="ai-section-title">🔍 Analysis</h2>
      <p class="ai-section-subtitle">
        All storage keys set by the page. Click on any item to see more details.
      </p>
      <div class="domain-groups">
      <div v-if="localStorage.length > 0" class="domain-group">
        <h3 class="domain-header">📦 Local Storage ({{ localStorage.length }})</h3>
        <div v-for="item in localStorage" :key="item.key" class="storage-item">
          <div class="storage-header" @click="toggleStorageInfo('localStorage', item)">
            <div class="storage-key">
              <span class="info-toggle" :class="{ expanded: expandedKeys.has(itemKey('localStorage', item)) }" title="Storage key details">ℹ</span>
              {{ item.key }}
              <span v-if="storageKeyHints[item.key]?.setBy" class="storage-key-hint">— {{ storageKeyHints[item.key]?.setBy }}</span>
            </div>
          </div>
          <p v-if="storageKeyHints[item.key]?.description" class="domain-description">
            {{ storageKeyHints[item.key]?.description }}
          </p>
          <div class="storage-value" :title="item.value">{{ truncateValue(item.value, 512) }}</div>

          <!-- Expandable Storage Info Panel -->
          <div v-if="expandedKeys.has(itemKey('localStorage', item))" class="storage-info-panel">
            <div v-if="loadingKeys.has(itemKey('localStorage', item))" class="storage-info-loading">
              <span class="spinner"></span>
              Looking up storage key information…
            </div>
            <div v-else-if="storageInfoCache[itemKey('localStorage', item)]" class="storage-info-content">
              <div class="info-row">
                <span class="info-label">What it does</span>
                <span class="info-value">{{ storageInfoCache[itemKey('localStorage', item)]?.description }}</span>
              </div>
              <template v-if="!isUnknownPurpose(storageInfoCache[itemKey('localStorage', item)])">
                <div class="info-row">
                  <span class="info-label">Set by</span>
                  <span class="info-value">{{ storageInfoCache[itemKey('localStorage', item)]?.setBy }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Purpose</span>
                  <span class="info-value">{{ purposeLabel(storageInfoCache[itemKey('localStorage', item)]?.purpose ?? '') }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Risk</span>
                  <span class="info-value">
                    <span class="risk-badge" :class="riskClass(storageInfoCache[itemKey('localStorage', item)]?.riskLevel ?? '')">
                      {{ storageInfoCache[itemKey('localStorage', item)]?.riskLevel }}
                    </span>
                  </span>
                </div>
                <div v-if="storageInfoCache[itemKey('localStorage', item)]?.privacyNote" class="info-row">
                  <span class="info-label">Privacy</span>
                  <span class="info-value privacy-note">{{ storageInfoCache[itemKey('localStorage', item)]?.privacyNote }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div v-if="sessionStorage.length > 0" class="domain-group">
        <h3 class="domain-header">⏱️ Session Storage ({{ sessionStorage.length }})</h3>
        <div v-for="item in sessionStorage" :key="item.key" class="storage-item">
          <div class="storage-header" @click="toggleStorageInfo('sessionStorage', item)">
            <div class="storage-key">
              <span class="info-toggle" :class="{ expanded: expandedKeys.has(itemKey('sessionStorage', item)) }" title="Storage key details">ℹ</span>
              {{ item.key }}
              <span v-if="storageKeyHints[item.key]?.setBy" class="storage-key-hint">— {{ storageKeyHints[item.key]?.setBy }}</span>
            </div>
          </div>
          <p v-if="storageKeyHints[item.key]?.description" class="domain-description">
            {{ storageKeyHints[item.key]?.description }}
          </p>
          <div class="storage-value" :title="item.value">{{ truncateValue(item.value, 512) }}</div>

          <!-- Expandable Storage Info Panel -->
          <div v-if="expandedKeys.has(itemKey('sessionStorage', item))" class="storage-info-panel">
            <div v-if="loadingKeys.has(itemKey('sessionStorage', item))" class="storage-info-loading">
              <span class="spinner"></span>
              Looking up storage key information…
            </div>
            <div v-else-if="storageInfoCache[itemKey('sessionStorage', item)]" class="storage-info-content">
              <div class="info-row">
                <span class="info-label">What it does</span>
                <span class="info-value">{{ storageInfoCache[itemKey('sessionStorage', item)]?.description }}</span>
              </div>
              <template v-if="!isUnknownPurpose(storageInfoCache[itemKey('sessionStorage', item)])">
                <div class="info-row">
                  <span class="info-label">Set by</span>
                  <span class="info-value">{{ storageInfoCache[itemKey('sessionStorage', item)]?.setBy }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Purpose</span>
                  <span class="info-value">{{ purposeLabel(storageInfoCache[itemKey('sessionStorage', item)]?.purpose ?? '') }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Risk</span>
                  <span class="info-value">
                    <span class="risk-badge" :class="riskClass(storageInfoCache[itemKey('sessionStorage', item)]?.riskLevel ?? '')">
                      {{ storageInfoCache[itemKey('sessionStorage', item)]?.riskLevel }}
                    </span>
                  </span>
                </div>
                <div v-if="storageInfoCache[itemKey('sessionStorage', item)]?.privacyNote" class="info-row">
                  <span class="info-label">Privacy</span>
                  <span class="info-value privacy-note">{{ storageInfoCache[itemKey('sessionStorage', item)]?.privacyNote }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
    </section>
  </div>
</template>

<style scoped>
.storage-item {
  padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--border-separator);
  font-size: 0.95rem;
}

.storage-item:last-child {
  border-bottom: none;
}

.storage-header {
  cursor: pointer;
  display: flex;
  align-items: center;
}

.storage-header:hover .storage-key {
  color: var(--link-color);
}

.storage-key {
  font-weight: 600;
  color: #e0e7ff;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: color 0.15s;
}

.storage-key-hint {
  font-weight: 400;
  font-size: 0.8rem;
  color: #8892b0;
}

.info-toggle {
  font-size: 0.7rem;
  color: #4b5e78;
  transition: color 0.15s, transform 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.1rem;
  height: 1.1rem;
  border-radius: 50%;
  border: 1px solid var(--border-separator);
  flex-shrink: 0;
}

.storage-header:hover .info-toggle {
  color: var(--link-color);
  border-color: var(--link-color);
}

.info-toggle.expanded {
  background: var(--link-color);
  color: #111827;
  border-color: var(--link-color);
}

.storage-value {
  color: var(--muted-light);
  word-break: break-all;
  font-family: monospace;
  font-size: 0.9rem;
  background: var(--surface-code);
  padding: 0.25rem;
  border-radius: 4px;
  margin-top: 0.4rem;
}

/* Storage Info Panel */
.storage-info-panel {
  margin-top: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--surface-card);
  border-radius: 6px;
  border-left: 3px solid var(--border-separator);
  font-size: var(--body-size);
}

.storage-info-loading {
  color: #6b7280;
  font-style: italic;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border-separator);
  border-top-color: var(--link-color);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.storage-info-content {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.info-row {
  display: flex;
  gap: 0.75rem;
  padding: 0.1rem 0;
}

.info-label {
  color: var(--muted-color);
  min-width: 5.5rem;
  flex-shrink: 0;
  font-size: 0.8rem;
}

.info-value {
  color: #d1d5db;
}

.privacy-note {
  color: #f59e0b;
  font-size: 0.82rem;
}

/* Risk badges */
.risk-badge {
  padding: var(--badge-padding);
  border-radius: var(--badge-radius);
  font-size: var(--badge-size);
  font-weight: 600;
  text-transform: uppercase;
}

.risk-none {
  background: #1a3a2a;
  color: #4ade80;
}

.risk-low {
  background: #1a2e3d;
  color: #7CB8E4;
}

.risk-medium {
  background: #3d3520;
  color: #fbbf24;
}

.risk-high {
  background: #3d2020;
  color: #f87171;
}

.risk-critical {
  background: #4a1a2e;
  color: #f472b6;
}

/* ── AI Storage Analysis ─────────────────────── */
.ai-storage-analysis {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.storage-analysis-section {
  margin-bottom: 0.75rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.ai-section-title {
  font-size: var(--section-title-size);
  font-weight: var(--section-title-weight);
  color: var(--section-title-color);
  margin: 0 0 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.ai-section-subtitle {
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

.section-divider {
  border: none;
  border-top: 1px solid var(--border-card);
  margin: 0.75rem 0;
}

.source-badge {
  font-size: var(--source-badge-size);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: var(--source-badge-padding);
  border-radius: 4px;
  white-space: nowrap;
}

.source-ai {
  background: #1a2e3d;
  color: #22d3ee;
}

.storage-ai-stats {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.ai-stat-card {
  background: var(--surface-card-inner);
  border: 1px solid var(--border-card);
  border-radius: 6px;
  padding: 0.75rem 1.25rem;
  text-align: center;
  flex: 1;
}

.ai-stat-value {
  display: block;
  font-size: var(--stat-value-size);
  font-weight: 700;
  color: var(--stat-value-color);
}

.ai-stat-label {
  font-size: var(--stat-label-size);
  color: var(--stat-label-color);
}

.storage-ai-concerns {
  margin-top: 0.5rem;
}

.storage-ai-concerns h3 {
  font-size: var(--subheading-size);
  color: var(--section-title-color);
  margin: 0.5rem 0 0.25rem;
}

.concern-group {
  margin-top: 0.5rem;
}

.concern-group + .concern-group {
  margin-top: 0.75rem;
}

.storage-type-badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: var(--badge-radius);
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.storage-type-badge.local {
  background: #1a2e3d;
  color: #22d3ee;
}

.storage-type-badge.session {
  background: #2a2040;
  color: #a78bfa;
}

.storage-ai-concerns ul {
  margin: 0.25rem 0 0 0.75rem;
  padding-left: 0.75rem;
  font-size: var(--summary-size);
  color: var(--body-color);
  line-height: 1.7;
}

.storage-ai-concerns li strong {
  color: #f1f5f9;
}
</style>
