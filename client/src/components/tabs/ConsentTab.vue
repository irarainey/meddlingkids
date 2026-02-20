<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ConsentDetails, TcfPurpose, TcfLookupResult } from '../../types'

/**
 * Tab panel displaying consent dialog details with IAB TCF purpose breakdown.
 *
 * Shows:
 * - Consent metadata (platform, partner counts, manage options)
 * - TCF Purpose Breakdown — matched purposes with risk levels,
 *   descriptions, lawful bases, and notes
 * - Consent categories from the dialog
 * - Partners grouped by risk level
 */
const props = defineProps<{
  /** Extracted consent details (may be null if not yet captured) */
  consentDetails: ConsentDetails | null
}>()

/** Cached TCF purpose lookup results. */
const tcfResult = ref<TcfLookupResult | null>(null)
const tcfLoading = ref(false)
const tcfError = ref(false)

/** Track whether we've already looked up purposes for the current data. */
const lastLookedUpPurposes = ref<string>('')

/**
 * Fetch TCF purpose mapping from the server when consent details
 * become available and contain purposes.
 */
watch(
  () => props.consentDetails?.purposes,
  async (purposes) => {
    if (!purposes || purposes.length === 0) {
      tcfResult.value = null
      lastLookedUpPurposes.value = ''
      return
    }

    // Avoid re-fetching if the purposes haven't changed.
    const key = purposes.join('|')
    if (key === lastLookedUpPurposes.value) return
    lastLookedUpPurposes.value = key

    tcfLoading.value = true
    tcfError.value = false
    try {
      const apiBase = import.meta.env.VITE_API_URL || ''
      const response = await fetch(`${apiBase}/api/tcf-purposes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purposes }),
      })
      if (response.ok) {
        tcfResult.value = await response.json()
      } else {
        tcfError.value = true
      }
    } catch {
      tcfError.value = true
    } finally {
      tcfLoading.value = false
    }
  },
  { immediate: true },
)

/** Group partners by risk level for the partner breakdown. */
function partnersByRisk(details: ConsentDetails) {
  const groups: Record<string, typeof details.partners> = {}
  for (const p of details.partners) {
    const level = p.riskLevel || 'unknown'
    if (!groups[level]) groups[level] = []
    groups[level].push(p)
  }
  return groups
}

/** Order for risk level display (worst first). */
const riskOrder = ['critical', 'high', 'medium', 'low', 'unknown']

function riskClass(level: string): string {
  const classes: Record<string, string> = {
    'low': 'risk-low',
    'medium': 'risk-medium',
    'high': 'risk-high',
    'critical': 'risk-critical',
    'unknown': 'risk-unknown',
  }
  return classes[level] || 'risk-unknown'
}

function categoryLabel(cat: TcfPurpose['category']): string {
  const labels: Record<string, string> = {
    'purpose': 'Purpose',
    'special-purpose': 'Special Purpose',
    'feature': 'Feature',
    'special-feature': 'Special Feature',
  }
  return labels[cat] || cat
}

function categoryIcon(cat: TcfPurpose['category']): string {
  const icons: Record<string, string> = {
    'purpose': '🎯',
    'special-purpose': '🔒',
    'feature': '⚙️',
    'special-feature': '⚡',
  }
  return icons[cat] || '📋'
}

function lawfulBasisLabel(basis: string): string {
  const labels: Record<string, string> = {
    'consent': '✋ Consent',
    'legitimate_interest': '⚖️ Legitimate Interest',
  }
  return labels[basis] || basis
}

function riskEmoji(level: string): string {
  const emojis: Record<string, string> = {
    'low': '🟢',
    'medium': '🟡',
    'high': '🟠',
    'critical': '🔴',
  }
  return emojis[level] || '⚪'
}

/** Expanded state for partner risk groups. */
const expandedRiskGroups = ref<Set<string>>(new Set())

function toggleRiskGroup(level: string): void {
  if (expandedRiskGroups.value.has(level)) {
    expandedRiskGroups.value.delete(level)
  } else {
    expandedRiskGroups.value.add(level)
  }
}
</script>

<template>
  <div class="tab-content">
    <div v-if="!consentDetails" class="empty-state">
      No consent dialog was detected
    </div>

    <div v-else class="consent-layout">

      <!-- ── Consent Metadata ────────────────────────── -->
      <section class="consent-meta">
        <div class="meta-cards">
          <div v-if="consentDetails.consentPlatform" class="meta-card">
            <span class="meta-icon">🛡️</span>
            <span class="meta-label">Platform</span>
            <span class="meta-value">{{ consentDetails.consentPlatform }}</span>
          </div>
          <div v-if="consentDetails.claimedPartnerCount" class="meta-card">
            <span class="meta-icon">📢</span>
            <span class="meta-label">Partners Claimed</span>
            <span class="meta-value">{{ consentDetails.claimedPartnerCount }}</span>
          </div>
          <div v-if="consentDetails.categories.length > 0" class="meta-card">
            <span class="meta-icon">📂</span>
            <span class="meta-label">Categories</span>
            <span class="meta-value">{{ consentDetails.categories.length }}</span>
          </div>
          <div v-if="consentDetails.purposes.length > 0" class="meta-card">
            <span class="meta-icon">🎯</span>
            <span class="meta-label">Purposes</span>
            <span class="meta-value">{{ consentDetails.purposes.length }}</span>
          </div>
          <div class="meta-card">
            <span class="meta-icon">⚙️</span>
            <span class="meta-label">Manage Options</span>
            <span class="meta-value">{{ consentDetails.hasManageOptions ? 'Yes' : 'No' }}</span>
          </div>
        </div>
      </section>

      <!-- ── TCF Purpose Breakdown ──────────────────── -->
      <section v-if="consentDetails.purposes.length > 0" class="tcf-section">
        <h2 class="section-title">🎯 TCF Purpose Breakdown</h2>
        <p class="section-subtitle">
          IAB Transparency &amp; Consent Framework purposes this site claims.
          Each purpose defines what your data can be used for.
        </p>

        <div v-if="tcfLoading" class="tcf-loading">
          <span class="spinner"></span>
          Mapping purposes to TCF taxonomy…
        </div>

        <div v-else-if="tcfResult" class="tcf-purposes">
          <div
            v-for="purpose in tcfResult.matched"
            :key="`${purpose.category}-${purpose.id}`"
            class="tcf-card"
            :class="riskClass(purpose.riskLevel)"
          >
            <div class="tcf-card-header">
              <span class="tcf-category-badge" :class="riskClass(purpose.riskLevel)">
                {{ categoryIcon(purpose.category) }} {{ categoryLabel(purpose.category) }} {{ purpose.id }}
              </span>
              <span class="tcf-risk-badge" :class="riskClass(purpose.riskLevel)">
                {{ riskEmoji(purpose.riskLevel) }} {{ purpose.riskLevel }}
              </span>
            </div>
            <h3 class="tcf-name">{{ purpose.name }}</h3>
            <p class="tcf-description">{{ purpose.description }}</p>
            <div class="tcf-meta-row">
              <div v-if="purpose.lawfulBases.length" class="tcf-bases">
                <span class="tcf-meta-label">Legal basis:</span>
                <span
                  v-for="basis in purpose.lawfulBases"
                  :key="basis"
                  class="basis-tag"
                >
                  {{ lawfulBasisLabel(basis) }}
                </span>
              </div>
            </div>
            <p v-if="purpose.notes" class="tcf-notes">💡 {{ purpose.notes }}</p>
          </div>

          <!-- Unmatched purposes -->
          <div v-if="tcfResult.unmatched.length > 0" class="unmatched-section">
            <h3 class="unmatched-title">Other Purposes</h3>
            <p class="section-subtitle">
              These declared purposes did not match a standard IAB TCF v2.2 purpose.
            </p>
            <div
              v-for="(purpose, idx) in tcfResult.unmatched"
              :key="idx"
              class="unmatched-item"
            >
              {{ purpose }}
            </div>
          </div>
        </div>
      </section>

      <!-- ── Consent Categories ─────────────────────── -->
      <section v-if="consentDetails.categories.length > 0" class="categories-section">
        <h2 class="section-title">📂 Consent Categories</h2>
        <div class="category-list">
          <div
            v-for="cat in consentDetails.categories"
            :key="cat.name"
            class="category-card"
          >
            <div class="category-header">
              <span class="category-name">{{ cat.name }}</span>
              <span v-if="cat.required" class="required-badge">Required</span>
              <span v-else class="optional-badge">Optional</span>
            </div>
            <p v-if="cat.description" class="category-desc">{{ cat.description }}</p>
          </div>
        </div>
      </section>

      <!-- ── Partners by Risk Level ─────────────────── -->
      <section v-if="consentDetails.partners.length > 0" class="partners-section">
        <h2 class="section-title">👥 Consent Partners</h2>
        <p class="section-subtitle">
          Third-party vendors declared in the consent dialog, grouped by risk classification.
        </p>

        <div class="partner-groups">
          <div
            v-for="level in riskOrder"
            :key="level"
            class="partner-group"
          >
            <template v-if="partnersByRisk(consentDetails)[level]?.length">
              <div
                class="partner-group-header"
                @click="toggleRiskGroup(level)"
              >
                <span class="expand-arrow" :class="{ expanded: expandedRiskGroups.has(level) }">▸</span>
                <span class="risk-badge" :class="riskClass(level)">
                  {{ level }}
                </span>
                <span class="partner-group-count">
                  {{ partnersByRisk(consentDetails)[level]?.length ?? 0 }} partner{{ partnersByRisk(consentDetails)[level]?.length === 1 ? '' : 's' }}
                </span>
              </div>
              <div v-if="expandedRiskGroups.has(level)" class="partner-list">
                <div
                  v-for="partner in partnersByRisk(consentDetails)[level]"
                  :key="partner.name"
                  class="partner-item"
                >
                  <div class="partner-name">
                    <a v-if="partner.url" :href="partner.url" target="_blank" rel="noopener">{{ partner.name }}</a>
                    <span v-else>{{ partner.name }}</span>
                  </div>
                  <div class="partner-purpose">{{ partner.purpose }}</div>
                  <div v-if="partner.concerns?.length" class="partner-concerns">
                    <span v-for="(concern, i) in partner.concerns" :key="i" class="concern-tag">⚠️ {{ concern }}</span>
                  </div>
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
.consent-layout {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* ── Metadata Cards ─────────────────────────── */
.meta-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.meta-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  background: #1a1e30;
  border-radius: 8px;
  padding: 0.75rem 1rem;
  min-width: 7rem;
  flex: 1;
}

.meta-icon {
  font-size: 1.5rem;
}

.meta-label {
  font-size: 0.7rem;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: 1.3rem;
  font-weight: 700;
  color: #e0e7ff;
}

/* ── Section Titles ──────────────────────────── */
.section-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #e0e7ff;
  margin: 0 0 0.25rem;
}

.section-subtitle {
  font-size: 0.85rem;
  color: #6b7280;
  margin: 0 0 0.75rem;
}

/* ── TCF Purpose Cards ──────────────────────── */
.tcf-section {
  border-top: 1px solid #3d4663;
  padding-top: 1rem;
}

.tcf-loading {
  color: #6b7280;
  font-style: italic;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
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

.tcf-purposes {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.tcf-card {
  background: #1a1e30;
  border-radius: 8px;
  padding: 0.85rem 1rem;
  border-left: 4px solid #3d4663;
}

.tcf-card.risk-low {
  border-left-color: #22d3ee;
}

.tcf-card.risk-medium {
  border-left-color: #fbbf24;
}

.tcf-card.risk-high {
  border-left-color: #f87171;
}

.tcf-card.risk-critical {
  border-left-color: #f472b6;
}

.tcf-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
}

.tcf-category-badge {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  background: #2a2f45;
  color: #9ca3af;
}

.tcf-category-badge.risk-low { color: #22d3ee; }
.tcf-category-badge.risk-medium { color: #fbbf24; }
.tcf-category-badge.risk-high { color: #f87171; }
.tcf-category-badge.risk-critical { color: #f472b6; }

.tcf-risk-badge {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  margin-left: auto;
}

.tcf-risk-badge.risk-low { background: #1a2e3d; color: #22d3ee; }
.tcf-risk-badge.risk-medium { background: #3d3520; color: #fbbf24; }
.tcf-risk-badge.risk-high { background: #3d2020; color: #f87171; }
.tcf-risk-badge.risk-critical { background: #4a1a2e; color: #f472b6; }

.tcf-name {
  font-size: 0.95rem;
  font-weight: 600;
  color: #e0e7ff;
  margin: 0 0 0.35rem;
}

.tcf-description {
  font-size: 0.85rem;
  color: #9ca3af;
  margin: 0 0 0.4rem;
  line-height: 1.4;
}

.tcf-meta-row {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  margin-bottom: 0.25rem;
}

.tcf-bases {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.tcf-meta-label {
  font-size: 0.75rem;
  color: #6b7280;
}

.basis-tag {
  font-size: 0.72rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: #2a2f45;
  color: #d1d5db;
}

.tcf-notes {
  font-size: 0.8rem;
  color: #f59e0b;
  margin: 0.3rem 0 0;
  line-height: 1.3;
}

/* ── Unmatched Purposes ─────────────────────── */
.unmatched-section {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid #3d4663;
}

.unmatched-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #9ca3af;
  margin: 0 0 0.25rem;
}

.unmatched-item {
  padding: 0.4rem 0.75rem;
  background: #1a1e30;
  border-radius: 4px;
  font-size: 0.85rem;
  color: #9ca3af;
  margin-bottom: 0.35rem;
}

/* ── Consent Categories ─────────────────────── */
.categories-section {
  border-top: 1px solid #3d4663;
  padding-top: 1rem;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.category-card {
  background: #1a1e30;
  border-radius: 6px;
  padding: 0.6rem 0.85rem;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.category-name {
  font-weight: 600;
  color: #e0e7ff;
  font-size: 0.9rem;
}

.required-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: #1a3a2a;
  color: #4ade80;
}

.optional-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: #2a2f45;
  color: #6b7280;
}

.category-desc {
  font-size: 0.82rem;
  color: #9ca3af;
  margin: 0.3rem 0 0;
  line-height: 1.3;
}

/* ── Partners ────────────────────────────────── */
.partners-section {
  border-top: 1px solid #3d4663;
  padding-top: 1rem;
}

.partner-groups {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.partner-group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.25rem;
  cursor: pointer;
  user-select: none;
}

.partner-group-header:hover {
  background: #1a1e30;
  border-radius: 4px;
}

.expand-arrow {
  color: #6b7280;
  font-size: 0.75rem;
  transition: transform 0.2s;
}

.expand-arrow.expanded {
  transform: rotate(90deg);
}

.partner-group-count {
  color: #6b7280;
  font-size: 0.82rem;
  margin-left: auto;
}

.partner-list {
  padding: 0 0 0.5rem 1.5rem;
}

.partner-item {
  padding: 0.4rem 0;
  border-bottom: 1px solid #2a2f45;
}

.partner-item:last-child {
  border-bottom: none;
}

.partner-name {
  font-weight: 600;
  color: #e0e7ff;
  font-size: 0.85rem;
}

.partner-name a {
  color: #7CB8E4;
  text-decoration: none;
}

.partner-name a:hover {
  text-decoration: underline;
}

.partner-purpose {
  font-size: 0.8rem;
  color: #9ca3af;
  margin-top: 0.1rem;
}

.partner-concerns {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.25rem;
}

.concern-tag {
  font-size: 0.72rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: #3d2020;
  color: #f87171;
}

/* ── Risk Badges (shared) ──────────────────── */
.risk-badge {
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
}

.risk-badge.risk-low { background: #1a2e3d; color: #22d3ee; }
.risk-badge.risk-medium { background: #3d3520; color: #fbbf24; }
.risk-badge.risk-high { background: #3d2020; color: #f87171; }
.risk-badge.risk-critical { background: #4a1a2e; color: #f472b6; }
.risk-badge.risk-unknown { background: #2a2f45; color: #6b7280; }
</style>
