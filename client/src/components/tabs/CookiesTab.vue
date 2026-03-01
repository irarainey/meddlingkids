<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { TrackedCookie, CookieInfo, DecodedCookies, StructuredReport } from '../../types'
import { formatExpiry, truncateValue, stripMarkdown } from '../../utils'

/**
 * Tab panel displaying cookies grouped by domain.
 * Supports click-to-expand cookie information lookup via the server API.
 */
const props = defineProps<{
  /** Cookies grouped by domain */
  cookiesByDomain: Record<string, TrackedCookie[]>
  /** Total number of cookies */
  cookieCount: number
  /** The URL being analyzed (used to identify first-party domains) */
  analyzedUrl?: string
  /** Decoded privacy cookies (USP, GPP, GA, Facebook, Google Ads, CMP, etc.) */
  decodedCookies?: DecodedCookies | null
  /** Structured report for the AI cookie analysis section */
  structuredReport?: StructuredReport | null
}>()

/** Extract the registrable base domain from a hostname (e.g. "www.bbc.co.uk" → "bbc.co.uk"). */
function baseDomain(hostname: string): string {
  const parts = hostname.replace(/^\./, '').split('.')
  // Handle two-part TLDs like co.uk, com.au, org.uk
  const twoPartTlds = ['co.uk', 'com.au', 'org.uk', 'co.jp', 'com.br', 'co.nz', 'co.za', 'com.mx']
  const last2 = parts.slice(-2).join('.')
  if (twoPartTlds.includes(last2) && parts.length >= 3) {
    return parts.slice(-3).join('.')
  }
  return parts.slice(-2).join('.')
}

/** The base domain of the analyzed URL, used to detect first-party cookies. */
const firstPartyDomain = computed(() => {
  if (!props.analyzedUrl) return ''
  try {
    return baseDomain(new URL(props.analyzedUrl).hostname)
  } catch {
    return ''
  }
})

/** Check whether a cookie domain belongs to the first party. */
function isFirstParty(domain: string): boolean {
  if (!firstPartyDomain.value) return false
  const clean = domain.replace(/^\./, '')
  return clean === firstPartyDomain.value || clean.endsWith('.' + firstPartyDomain.value)
}

/** Cache of cookie info results, keyed by "domain|name". */
const cookieInfoCache = reactive<Record<string, CookieInfo>>({})

/** Set of cookie keys currently being loaded. */
const loadingKeys = reactive<Set<string>>(new Set())

/** Set of cookie keys that are expanded (info panel visible). */
const expandedKeys = reactive<Set<string>>(new Set())

/** Cache of domain descriptions, keyed by domain. */
const domainDescriptions = reactive<Record<string, { company: string | null; description: string | null }>>({})

/**
 * Resolve the description to display for a domain.
 * First-party domains get a "First-party cookie" label even
 * if the server lookup returns nothing.
 */
function domainDescription(domain: string): string | null {
  const info = domainDescriptions[domain]
  if (info?.description) return info.description
  if (isFirstParty(domain)) return 'First-party cookie'
  return null
}

/** Fetch domain descriptions for all visible cookie domains. */
async function fetchDomainDescriptions(domains: string[]): Promise<void> {
  const unknown = domains.filter((d) => !(d in domainDescriptions))
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
        domainDescriptions[domain] = info as { company: string | null; description: string | null }
      }
    }
  } catch {
    // Silently fail — descriptions are non-critical
  }
}

watch(
  () => Object.keys(props.cookiesByDomain),
  (domains) => {
    if (domains.length > 0) fetchDomainDescriptions(domains)
  },
  { immediate: true },
)

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

/** Colour-coded severity/risk badge class for AI analysis. */
function severityClass(level: string): string {
  switch (level) {
    case 'critical':
    case 'very-high':
      return 'badge-critical'
    case 'high':
      return 'badge-high'
    case 'medium':
      return 'badge-medium'
    case 'low':
      return 'badge-low'
    case 'none':
      return 'badge-none'
    default:
      return 'badge-medium'
  }
}

/** Human-readable label for risk levels. */
function riskLabel(level: string): string {
  switch (level) {
    case 'very-high':
      return 'Very High'
    case 'critical':
      return 'Critical'
    case 'high':
      return 'High'
    case 'medium':
      return 'Medium'
    case 'low':
      return 'Low'
    case 'none':
      return 'None'
    default:
      return level
  }
}
</script>

<template>
  <div class="tab-content">
    <div v-if="cookieCount === 0 && !decodedCookies && !structuredReport" class="empty-state">No cookies detected</div>

    <!-- ── Overview (AI Cookie Analysis) ──────────── -->
    <section v-if="structuredReport && structuredReport.cookieAnalysis.groups.length > 0" class="ai-cookie-analysis">
      <h2 class="section-title">🍪 Overview
        <span class="count-badge">{{ structuredReport.cookieAnalysis.total }} cookies</span>
      </h2>
      <p class="section-subtitle">
        Cookie categories and risk levels determined by AI analysis of cookie
        names, domains, and values.
      </p>
      <div
        v-for="(group, i) in structuredReport.cookieAnalysis.groups"
        :key="i"
        class="cookie-ai-group"
      >
        <div class="cookie-ai-group-header">
          <h3>{{ group.category }}</h3>
          <span class="badge" :class="severityClass(group.concernLevel)">{{ riskLabel(group.concernLevel) }}</span>
          <span v-if="group.lifespan" class="lifespan-tag">⏱ {{ group.lifespan }}</span>
        </div>
        <div class="cookie-ai-names">
          <code v-for="cookie in group.cookies" :key="cookie">{{ cookie }}</code>
        </div>
      </div>
      <div v-if="structuredReport.cookieAnalysis.concerningCookies.length" class="concerning-section">
        <h3>⚠️ Concerning Cookies</h3>
        <ul>
          <li v-for="(concern, i) in structuredReport.cookieAnalysis.concerningCookies" :key="i">
            {{ stripMarkdown(concern) }}
          </li>
        </ul>
      </div>
    </section>

    <!-- ── Decoded Privacy Cookies ───────────────── -->
    <section v-if="decodedCookies && Object.keys(decodedCookies).length > 0" class="decoded-cookies-section">
      <h2 class="section-title">🔍 Decoded Privacy Cookies</h2>
      <p class="section-subtitle">
        Privacy-relevant cookies found on this site, decoded from
        their raw values into human-readable data. These cookies are set by
        ad-tech platforms, analytics providers, and consent management tools.
      </p>

      <!-- USP String (CCPA) -->
      <div v-if="decodedCookies.uspString" class="decoded-card">
        <h3 class="decoded-card-title">
          🇺🇸 USP String <span class="decoded-cookie-name">usprivacy</span>
        </h3>
        <p class="decoded-card-desc">IAB US Privacy String — CCPA opt-out signal</p>
        <div class="decoded-fields">
          <div class="decoded-field">
            <span class="decoded-field-label">Version</span>
            <span class="decoded-field-value">{{ decodedCookies.uspString.version }}</span>
          </div>
          <div class="decoded-field">
            <span class="decoded-field-label">Notice Given</span>
            <span class="decoded-field-value" :class="decodedCookies.uspString.noticeGiven ? 'val-yes' : 'val-no'">
              {{ decodedCookies.uspString.noticeLabel }}
            </span>
          </div>
          <div class="decoded-field">
            <span class="decoded-field-label">Opted Out of Sale</span>
            <span class="decoded-field-value" :class="decodedCookies.uspString.optedOut ? 'val-warn' : 'val-ok'">
              {{ decodedCookies.uspString.optOutLabel }}
            </span>
          </div>
          <div class="decoded-field">
            <span class="decoded-field-label">LSPA Covered</span>
            <span class="decoded-field-value">{{ decodedCookies.uspString.lspaLabel }}</span>
          </div>
        </div>
        <div class="decoded-raw">{{ decodedCookies.uspString.rawString }}</div>
      </div>

      <!-- GPP String -->
      <div v-if="decodedCookies.gppString" class="decoded-card">
        <h3 class="decoded-card-title">
          🌐 GPP String <span class="decoded-cookie-name">__gpp</span>
        </h3>
        <p class="decoded-card-desc">IAB Global Privacy Platform — multi-jurisdiction consent signal</p>
        <div class="decoded-fields">
          <div v-if="decodedCookies.gppString.version" class="decoded-field">
            <span class="decoded-field-label">Version</span>
            <span class="decoded-field-value">{{ decodedCookies.gppString.version }}</span>
          </div>
          <div class="decoded-field">
            <span class="decoded-field-label">Segments</span>
            <span class="decoded-field-value">{{ decodedCookies.gppString.segmentCount }}</span>
          </div>
          <div v-if="decodedCookies.gppString.sections.length > 0" class="decoded-field decoded-field-wide">
            <span class="decoded-field-label">Applicable Sections</span>
            <div class="decoded-section-list">
              <span
                v-for="sec in decodedCookies.gppString.sections"
                :key="sec.id"
                class="decoded-section-tag"
              >
                {{ sec.name }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Google Analytics -->
      <div v-if="decodedCookies.googleAnalytics" class="decoded-card">
        <h3 class="decoded-card-title">
          📊 Google Analytics <span class="decoded-cookie-name">_ga</span>
        </h3>
        <p class="decoded-card-desc">Cross-session user tracking identifier</p>
        <div class="decoded-fields">
          <div class="decoded-field">
            <span class="decoded-field-label">Client ID</span>
            <span class="decoded-field-value decoded-mono">{{ decodedCookies.googleAnalytics.clientId }}</span>
          </div>
          <div v-if="decodedCookies.googleAnalytics.firstVisit" class="decoded-field">
            <span class="decoded-field-label">First Visit</span>
            <span class="decoded-field-value">{{ decodedCookies.googleAnalytics.firstVisit }}</span>
          </div>
        </div>
      </div>

      <!-- Facebook Pixel -->
      <div v-if="decodedCookies.facebookPixel" class="decoded-card">
        <h3 class="decoded-card-title">
          📘 Facebook Pixel <span class="decoded-cookie-name">_fbp / _fbc</span>
        </h3>
        <p class="decoded-card-desc">Meta/Facebook cross-site tracking and ad attribution</p>
        <div class="decoded-fields">
          <template v-if="decodedCookies.facebookPixel.fbp">
            <div class="decoded-field">
              <span class="decoded-field-label">Browser ID</span>
              <span class="decoded-field-value decoded-mono">{{ decodedCookies.facebookPixel.fbp.browserId }}</span>
            </div>
            <div v-if="decodedCookies.facebookPixel.fbp.created" class="decoded-field">
              <span class="decoded-field-label">Created</span>
              <span class="decoded-field-value">{{ decodedCookies.facebookPixel.fbp.created }}</span>
            </div>
          </template>
          <template v-if="decodedCookies.facebookPixel.fbc">
            <div class="decoded-field">
              <span class="decoded-field-label">Click ID (fbclid)</span>
              <span class="decoded-field-value decoded-mono">{{ decodedCookies.facebookPixel.fbc.fbclid }}</span>
            </div>
            <div v-if="decodedCookies.facebookPixel.fbc.clicked" class="decoded-field">
              <span class="decoded-field-label">Clicked</span>
              <span class="decoded-field-value">{{ decodedCookies.facebookPixel.fbc.clicked }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- Google Ads -->
      <div v-if="decodedCookies.googleAds" class="decoded-card">
        <h3 class="decoded-card-title">
          📢 Google Ads <span class="decoded-cookie-name">_gcl_au / _gcl_aw</span>
        </h3>
        <p class="decoded-card-desc">Google Ads conversion tracking and click attribution</p>
        <div class="decoded-fields">
          <template v-if="decodedCookies.googleAds.gclAu">
            <div class="decoded-field">
              <span class="decoded-field-label">Conversion Linker</span>
              <span class="decoded-field-value">v{{ decodedCookies.googleAds.gclAu.version }}</span>
            </div>
            <div v-if="decodedCookies.googleAds.gclAu.created" class="decoded-field">
              <span class="decoded-field-label">Created</span>
              <span class="decoded-field-value">{{ decodedCookies.googleAds.gclAu.created }}</span>
            </div>
          </template>
          <template v-if="decodedCookies.googleAds.gclAw">
            <div class="decoded-field">
              <span class="decoded-field-label">Click ID (gclid)</span>
              <span class="decoded-field-value decoded-mono">{{ decodedCookies.googleAds.gclAw.gclid }}</span>
            </div>
            <div v-if="decodedCookies.googleAds.gclAw.clicked" class="decoded-field">
              <span class="decoded-field-label">Clicked</span>
              <span class="decoded-field-value">{{ decodedCookies.googleAds.gclAw.clicked }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- OneTrust -->
      <div v-if="decodedCookies.oneTrust" class="decoded-card">
        <h3 class="decoded-card-title">
          🛡️ OneTrust <span class="decoded-cookie-name">OptanonConsent</span>
        </h3>
        <p class="decoded-card-desc">OneTrust CMP category-level consent status</p>
        <div class="decoded-fields">
          <div v-for="cat in decodedCookies.oneTrust.categories" :key="cat.id" class="decoded-field">
            <span class="decoded-field-label">{{ cat.name }}</span>
            <span class="decoded-field-value" :class="cat.consented ? 'val-yes' : 'val-no'">
              {{ cat.consented ? '✅ Consented' : '❌ Rejected' }}
            </span>
          </div>
          <div v-if="decodedCookies.oneTrust.isGpcApplied" class="decoded-field">
            <span class="decoded-field-label">GPC Applied</span>
            <span class="decoded-field-value val-yes">Yes</span>
          </div>
        </div>
      </div>

      <!-- Cookiebot -->
      <div v-if="decodedCookies.cookiebot" class="decoded-card">
        <h3 class="decoded-card-title">
          🤖 Cookiebot <span class="decoded-cookie-name">CookieConsent</span>
        </h3>
        <p class="decoded-card-desc">Cookiebot CMP category-level consent status</p>
        <div class="decoded-fields">
          <div v-for="(cat, idx) in decodedCookies.cookiebot.categories" :key="idx" class="decoded-field">
            <span class="decoded-field-label">{{ cat.name }}</span>
            <span class="decoded-field-value" :class="cat.consented ? 'val-yes' : 'val-no'">
              {{ cat.consented ? '✅ Consented' : '❌ Rejected' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Google SOCS -->
      <div v-if="decodedCookies.googleSocs" class="decoded-card">
        <h3 class="decoded-card-title">
          🔵 Google Consent <span class="decoded-cookie-name">SOCS</span>
        </h3>
        <p class="decoded-card-desc">Google services consent mode signal</p>
        <div class="decoded-fields">
          <div class="decoded-field">
            <span class="decoded-field-label">Consent Mode</span>
            <span class="decoded-field-value">{{ decodedCookies.googleSocs.consentMode }}</span>
          </div>
        </div>
      </div>

      <!-- GPC / DNT -->
      <div v-if="decodedCookies.gpcDnt" class="decoded-card">
        <h3 class="decoded-card-title">
          🛑 Privacy Signals <span class="decoded-cookie-name">GPC / DNT</span>
        </h3>
        <p class="decoded-card-desc">Browser-level privacy preference signals</p>
        <div class="decoded-fields">
          <div class="decoded-field">
            <span class="decoded-field-label">Global Privacy Control</span>
            <span class="decoded-field-value" :class="decodedCookies.gpcDnt.gpcEnabled ? 'val-yes' : 'val-no'">
              {{ decodedCookies.gpcDnt.gpcEnabled ? '✅ Enabled' : '❌ Not detected' }}
            </span>
          </div>
          <div class="decoded-field">
            <span class="decoded-field-label">Do Not Track</span>
            <span class="decoded-field-value" :class="decodedCookies.gpcDnt.dntEnabled ? 'val-yes' : 'val-no'">
              {{ decodedCookies.gpcDnt.dntEnabled ? '✅ Enabled' : '❌ Not detected' }}
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- ── Analysis (cookie listing by domain) ───── -->
    <section v-if="cookieCount > 0" class="cookie-analysis-section">
      <h2 class="section-title">🔎 Analysis</h2>
      <p class="section-subtitle">
        All cookies set on this site, grouped by domain.
        Click a cookie to look up its purpose and risk level.
      </p>
      <div class="domain-groups">
      <div v-for="(domainCookies, domain) in cookiesByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">
          {{ domain }} ({{ domainCookies.length }})
          <span v-if="domainDescription(String(domain))" class="domain-description">
            {{ domainDescription(String(domain)) }}
          </span>
        </h3>
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
    </section>
  </div>
</template>

<style scoped>
.cookie-item {
  padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--border-separator);
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
  color: var(--link-color);
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
  border: 1px solid var(--border-separator);
  flex-shrink: 0;
}

.cookie-header:hover .info-toggle {
  color: var(--link-color);
  border-color: var(--link-color);
}

.info-toggle.expanded {
  background: var(--link-color);
  color: #111827;
  border-color: var(--link-color);
}

.cookie-value {
  color: var(--muted-light);
  word-break: break-all;
  font-family: monospace;
  font-size: 0.9rem;
  background: var(--surface-code);
  padding: 0.25rem;
  border-radius: 4px;
  margin-top: 0.4rem;
}

.cookie-meta {
  margin-top: 0.35rem;
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
  padding: 0.75rem 1rem;
  background: var(--surface-card);
  border-radius: 6px;
  border-left: 3px solid var(--border-separator);
  font-size: var(--body-size);
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
  border: 2px solid var(--border-separator);
  border-top-color: var(--link-color);
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

/* ── Decoded Privacy Cookies ─────────────────── */
.decoded-cookies-section {
  margin-bottom: 1.5rem;
}

/* ── Cookie Analysis (domain listing) ────────── */
.cookie-analysis-section {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

/* ── AI Cookie Analysis ──────────────────────── */
.ai-cookie-analysis {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.cookie-ai-group {
  margin-bottom: 0.75rem;
}

.cookie-ai-group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.cookie-ai-group-header h3 {
  margin: 0;
  font-size: var(--subheading-size);
  color: var(--subheading-color);
}

.lifespan-tag {
  font-size: 0.82rem;
  color: #9ca3af;
}

.cookie-ai-names {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.4rem;
}

.cookie-ai-names code {
  background: var(--surface-code);
  color: var(--link-color);
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: var(--body-size);
  font-family: monospace;
}

.concerning-section {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-card);
}

.concerning-section h3 {
  font-size: var(--subheading-size);
  color: var(--subheading-color);
  margin: 0 0 0.5rem;
}

.concerning-section ul {
  margin: 0.25rem 0 0 1.25rem;
  font-size: 0.95rem;
  color: #fdba74;
}

.count-badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: var(--badge-radius);
  font-size: 0.72rem;
  font-weight: 600;
  background: #2a3555;
  color: var(--link-color);
  margin-left: auto;
}

.badge {
  display: inline-block;
  padding: var(--badge-padding);
  border-radius: var(--badge-radius);
  font-size: var(--badge-size);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.badge-critical {
  background: #450a0a;
  color: #fca5a5;
  border: 1px solid #ef4444;
}

.badge-high {
  background: #431407;
  color: #fdba74;
  border: 1px solid #f97316;
}

.badge-medium {
  background: #422006;
  color: #fde047;
  border: 1px solid #eab308;
}

.badge-low {
  background: #052e16;
  color: #86efac;
  border: 1px solid #22c55e;
}

.badge-none {
  background: #1e293b;
  color: #94a3b8;
  border: 1px solid #475569;
}

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

.decoded-card {
  background: var(--surface-card);
  border-radius: 8px;
  padding: 1rem 1.25rem;
  margin-bottom: 0.75rem;
  border: 1px solid var(--border-card);
}

.decoded-card-title {
  font-size: 0.95rem;
  font-weight: 700;
  color: #e0e7ff;
  margin: 0 0 0.25rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.decoded-cookie-name {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  background: var(--surface-code);
  color: var(--muted-light);
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  font-weight: 400;
}

.decoded-card-desc {
  font-size: var(--body-size);
  color: var(--muted-color);
  margin: 0 0 0.75rem;
}

.decoded-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.25rem;
}

.decoded-field {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 8rem;
}

.decoded-field-wide {
  flex-basis: 100%;
}

.decoded-field-label {
  font-size: var(--stat-label-size);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--muted-color);
}

.decoded-field-value {
  font-size: 0.9rem;
  color: #d1d5db;
  font-weight: 600;
}

.decoded-field-value.decoded-mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.82rem;
  word-break: break-all;
}

.decoded-field-value.val-yes {
  color: #4ade80;
}

.decoded-field-value.val-no {
  color: #f87171;
}

.decoded-field-value.val-warn {
  color: #fbbf24;
}

.decoded-field-value.val-ok {
  color: #4ade80;
}

.decoded-raw {
  margin-top: 0.5rem;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  color: #4b5563;
  word-break: break-all;
  background: #12152080;
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
}

.decoded-section-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.25rem;
}

.decoded-section-tag {
  font-size: 0.75rem;
  background: var(--surface-code);
  color: #a5b4fc;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  border: 1px solid #3b4566;
}

.source-badge {
  font-size: var(--source-badge-size);
  padding: var(--source-badge-padding);
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.source-cookie {
  background: #854d0e;
  color: #fef3c7;
}
</style>
