<script setup lang="ts">
import { reactive } from 'vue'
import type { StorageItem, StorageInfo } from '../../types'
import { truncateValue } from '../../utils'

/**
 * Tab panel displaying localStorage and sessionStorage items.
 * Supports click-to-expand storage key information lookup via the server API.
 */
defineProps<{
  /** localStorage items */
  localStorage: StorageItem[]
  /** sessionStorage items */
  sessionStorage: StorageItem[]
}>()

/** Cache of storage info results, keyed by "storageType|key". */
const storageInfoCache = reactive<Record<string, StorageInfo>>({})

/** Set of storage keys currently being loaded. */
const loadingKeys = reactive<Set<string>>(new Set())

/** Set of storage keys that are expanded (info panel visible). */
const expandedKeys = reactive<Set<string>>(new Set())

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
    const apiBase = import.meta.env.VITE_API_URL || ''
    const response = await fetch(`${apiBase}/api/storage-info`, {
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

function purposeLabel(purpose: string): string {
  const labels: Record<string, string> = {
    'analytics': '📊 Analytics',
    'advertising': '📢 Advertising',
    'functional': '⚙️ Functional',
    'session': '🔑 Session',
    'consent': '✅ Consent',
    'social-media': '👥 Social Media',
    'fingerprinting': '🔍 Fingerprinting',
    'identity-resolution': '🆔 Identity Resolution',
    'unknown': '❓ Unknown',
  }
  return labels[purpose] || purpose
}

function riskClass(level: string): string {
  const classes: Record<string, string> = {
    'none': 'risk-none',
    'low': 'risk-low',
    'medium': 'risk-medium',
    'high': 'risk-high',
    'critical': 'risk-critical',
  }
  return classes[level] || 'risk-low'
}
</script>

<template>
  <div class="tab-content">
    <div v-if="localStorage.length === 0 && sessionStorage.length === 0" class="empty-state">
      No storage data detected
    </div>
    <div v-else class="domain-groups">
      <div v-if="localStorage.length > 0" class="domain-group">
        <h3 class="domain-header">📦 Local Storage ({{ localStorage.length }})</h3>
        <div v-for="item in localStorage" :key="item.key" class="storage-item">
          <div class="storage-header" @click="toggleStorageInfo('localStorage', item)">
            <div class="storage-key">
              <span class="info-toggle" :class="{ expanded: expandedKeys.has(itemKey('localStorage', item)) }" title="Storage key details">ℹ</span>
              {{ item.key }}
            </div>
          </div>
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
            </div>
          </div>
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
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.storage-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
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
  color: #7CB8E4;
}

.storage-key {
  font-weight: 600;
  color: #e0e7ff;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: color 0.15s;
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
  border: 1px solid #3d4663;
  flex-shrink: 0;
}

.storage-header:hover .info-toggle {
  color: #7CB8E4;
  border-color: #7CB8E4;
}

.info-toggle.expanded {
  background: #7CB8E4;
  color: #111827;
  border-color: #7CB8E4;
}

.storage-value {
  color: #9ca3af;
  word-break: break-all;
  font-family: monospace;
  font-size: 0.9rem;
  background: #2a2f45;
  padding: 0.25rem;
  border-radius: 4px;
  margin-top: 0.25rem;
}

/* Storage Info Panel */
.storage-info-panel {
  margin-top: 0.5rem;
  padding: 0.6rem 0.75rem;
  background: #1a1e30;
  border-radius: 6px;
  border-left: 3px solid #3d4663;
  font-size: 0.85rem;
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
  border: 2px solid #3d4663;
  border-top-color: #7CB8E4;
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
  gap: 0.35rem;
}

.info-row {
  display: flex;
  gap: 0.75rem;
}

.info-label {
  color: #6b7280;
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
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
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
</style>
