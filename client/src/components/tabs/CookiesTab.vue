<script setup lang="ts">
import { reactive } from 'vue'
import type { TrackedCookie, CookieInfo } from '../../types'
import { formatExpiry, truncateValue } from '../../utils'

/**
 * Tab panel displaying cookies grouped by domain.
 * Supports click-to-expand cookie information lookup via the server API.
 */
defineProps<{
  /** Cookies grouped by domain */
  cookiesByDomain: Record<string, TrackedCookie[]>
  /** Total number of cookies */
  cookieCount: number
}>()

/** Cache of cookie info results, keyed by "domain|name". */
const cookieInfoCache = reactive<Record<string, CookieInfo>>({})

/** Set of cookie keys currently being loaded. */
const loadingKeys = reactive<Set<string>>(new Set())

/** Set of cookie keys that are expanded (info panel visible). */
const expandedKeys = reactive<Set<string>>(new Set())

function cookieKey(cookie: TrackedCookie): string {
  return `${cookie.domain}|${cookie.name}`
}

async function toggleCookieInfo(cookie: TrackedCookie): Promise<void> {
  const key = cookieKey(cookie)

  // If already expanded, just collapse
  if (expandedKeys.has(key)) {
    expandedKeys.delete(key)
    return
  }

  // Expand the panel
  expandedKeys.add(key)

  // If we already have the info cached, nothing more to do
  if (cookieInfoCache[key]) {
    return
  }

  // Fetch from server
  loadingKeys.add(key)
  try {
    const apiBase = import.meta.env.VITE_API_URL || ''
    const response = await fetch(`${apiBase}/api/cookie-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: cookie.name,
        domain: cookie.domain,
        value: cookie.value,
      }),
    })
    if (response.ok) {
      cookieInfoCache[key] = await response.json()
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

function isUnknownPurpose(info: CookieInfo | undefined): boolean {
  return info?.purpose === 'unknown'
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
    <div v-if="cookieCount === 0" class="empty-state">No cookies detected</div>
    <div v-else class="domain-groups">
      <div v-for="(domainCookies, domain) in cookiesByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">{{ domain }} ({{ domainCookies.length }})</h3>
        <div
          v-for="cookie in domainCookies"
          :key="`${cookie.domain}-${cookie.name}`"
          class="cookie-item"
        >
          <div class="cookie-header" @click="toggleCookieInfo(cookie)">
            <div class="cookie-name">
              <span class="info-toggle" :class="{ expanded: expandedKeys.has(cookieKey(cookie)) }" title="Cookie details">ℹ</span>
              {{ cookie.name }}
            </div>
          </div>
          <div class="cookie-details">
            <span class="cookie-value" :title="cookie.value">{{ truncateValue(cookie.value, 512) }}</span>
            <div class="cookie-meta">
              <span v-if="cookie.httpOnly" class="badge">HttpOnly</span>
              <span v-if="cookie.secure" class="badge">Secure</span>
              <span class="badge">{{ cookie.sameSite }}</span>
              <span class="expiry">Expires: {{ formatExpiry(cookie.expires) }}</span>
            </div>
          </div>

          <!-- Expandable Cookie Info Panel -->
          <div v-if="expandedKeys.has(cookieKey(cookie))" class="cookie-info-panel">
            <div v-if="loadingKeys.has(cookieKey(cookie))" class="cookie-info-loading">
              <span class="spinner"></span>
              Looking up cookie information…
            </div>
            <div v-else-if="cookieInfoCache[cookieKey(cookie)]" class="cookie-info-content">
              <div class="info-row">
                <span class="info-label">What it does</span>
                <span class="info-value">{{ cookieInfoCache[cookieKey(cookie)]?.description }}</span>
              </div>
              <template v-if="!isUnknownPurpose(cookieInfoCache[cookieKey(cookie)])">
                <div class="info-row">
                  <span class="info-label">Set by</span>
                  <span class="info-value">{{ cookieInfoCache[cookieKey(cookie)]?.setBy }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Purpose</span>
                  <span class="info-value">{{ purposeLabel(cookieInfoCache[cookieKey(cookie)]?.purpose ?? '') }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">Risk</span>
                  <span class="info-value">
                    <span class="risk-badge" :class="riskClass(cookieInfoCache[cookieKey(cookie)]?.riskLevel ?? '')">
                      {{ cookieInfoCache[cookieKey(cookie)]?.riskLevel }}
                    </span>
                  </span>
                </div>
                <div v-if="cookieInfoCache[cookieKey(cookie)]?.privacyNote" class="info-row">
                  <span class="info-label">Privacy</span>
                  <span class="info-value privacy-note">{{ cookieInfoCache[cookieKey(cookie)]?.privacyNote }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cookie-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
  font-size: 0.95rem;
}

.cookie-item:last-child {
  border-bottom: none;
}

.cookie-header {
  cursor: pointer;
  display: flex;
  align-items: center;
}

.cookie-header:hover .cookie-name {
  color: #7CB8E4;
}

.cookie-name {
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

.cookie-header:hover .info-toggle {
  color: #7CB8E4;
  border-color: #7CB8E4;
}

.info-toggle.expanded {
  background: #7CB8E4;
  color: #111827;
  border-color: #7CB8E4;
}

.cookie-value {
  color: #9ca3af;
  word-break: break-all;
}

.cookie-meta {
  margin-top: 0.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.expiry {
  font-size: 0.85rem;
  color: #9ca3af;
}

/* Cookie Info Panel */
.cookie-info-panel {
  margin-top: 0.5rem;
  padding: 0.6rem 0.75rem;
  background: #1a1e30;
  border-radius: 6px;
  border-left: 3px solid #3d4663;
  font-size: 0.85rem;
}

.cookie-info-loading {
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

.cookie-info-content {
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
