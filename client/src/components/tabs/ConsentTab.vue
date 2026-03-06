<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { ConsentDetails, TcfPurpose, TcfLookupResult, TcValidationResult, TcValidationFinding, AcStringData, StructuredReport } from '../../types'
import { stripMarkdown } from '../../utils'

/**
 * Tab panel displaying consent dialog details with IAB TCF purpose breakdown.
 *
 * Shows:
 * - Unified overview with verified stats from TC/AC Strings and AI dialog metrics
 * - TCF Purpose Breakdown — matched purposes with risk levels
 * - Purpose Consent Matrix — all 11 IAB purposes with actual consent status
 * - Verified vendors & partners from TC/AC Strings with enrichment badges
 * - Consent categories from the dialog
 */
const props = defineProps<{
  /** Extracted consent details (may be null if not yet captured) */
  consentDetails: ConsentDetails | null
  /** Structured report for the AI consent analysis and vendor sections */
  structuredReport?: StructuredReport | null
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

/** Computed TC validation result. */
function tcValidation(): TcValidationResult | null {
  return props.consentDetails?.tcValidation ?? null
}

/** Computed AC String data (Google Additional Consent Mode). */
function acStringData(): AcStringData | null {
  return props.consentDetails?.acStringData ?? null
}

/** Category icon mapping for the vendor summary. */
function categoryEmoji(category: string): string {
  const icons: Record<string, string> = {
    'Ad Network': '📡',
    'Ad Technology': '📡',
    'Analytics': '📊',
    'Data Broker': '🔴',
    'Identity Tracker': '🔍',
    'Session Replay': '🎥',
    'Social Tracker': '💬',
    'Mobile SDK': '📱',
    'Consent Provider': '🛡️',
    'Content Delivery': '🌐',
    'Essential Service': '🌐',
    'Measurement': '📊',
  }
  return icons[category] ?? '📋'
}

/** Aggregated vendor summary across TC consents, TC LI, and AC providers. */
const vendorSummary = computed(() => {
  const categoryCounts: Record<string, number> = {}
  let totalConcerns = 0
  let vendorsWithConcerns = 0
  const seen = new Set<string>()

  function process(name: string, category?: string, concerns?: string[]) {
    // De-duplicate by name so vendors appearing in both consent & LI aren't double-counted
    if (seen.has(name)) return
    seen.add(name)
    if (category) {
      categoryCounts[category] = (categoryCounts[category] || 0) + 1
    }
    if (concerns?.length) {
      totalConcerns += concerns.length
      vendorsWithConcerns++
    }
  }

  for (const v of props.consentDetails?.tcStringData?.resolvedVendorConsents ?? []) {
    process(v.name, v.category, v.concerns)
  }
  for (const v of props.consentDetails?.tcStringData?.resolvedVendorLi ?? []) {
    process(v.name, v.category, v.concerns)
  }
  for (const p of acStringData()?.resolvedProviders ?? []) {
    process(p.name, p.category, p.concerns)
  }

  // Sort categories by count descending
  const sorted = Object.entries(categoryCounts)
    .sort((a, b) => b[1] - a[1])

  return {
    categories: sorted,
    totalVendors: seen.size,
    totalConcerns,
    vendorsWithConcerns,
  }
})

/** Track collapsed/expanded state for vendor lists. */
const showTcVendors = ref(false)
const showTcVendorsLi = ref(false)
const showAcProviders = ref(false)

/** CSS class for vendor category badges. */
function vendorCategoryClass(category: string): string {
  const map: Record<string, string> = {
    'Ad Network': 'vendor-cat-ad',
    'Ad Technology': 'vendor-cat-ad',
    'Analytics': 'vendor-cat-analytics',
    'Data Broker': 'vendor-cat-broker',
    'Identity Tracker': 'vendor-cat-identity',
    'Session Replay': 'vendor-cat-replay',
    'Social Tracker': 'vendor-cat-social',
    'Mobile SDK': 'vendor-cat-mobile',
    'Consent Provider': 'vendor-cat-consent',
    'Content Delivery': 'vendor-cat-other',
    'Essential Service': 'vendor-cat-other',
    'Measurement': 'vendor-cat-analytics',
  }
  return map[category] ?? 'vendor-cat-other'
}

/** Severity icon for TC validation findings. */
function findingSeverityIcon(severity: TcValidationFinding['severity']): string {
  const icons: Record<string, string> = {
    'critical': '🔴',
    'high': '🟠',
    'moderate': '🟡',
    'info': 'ℹ️',
  }
  return icons[severity] || '⚪'
}

/** CSS class for finding severity. */
function findingSeverityClass(severity: TcValidationFinding['severity']): string {
  const classes: Record<string, string> = {
    'critical': 'finding-critical',
    'high': 'finding-high',
    'moderate': 'finding-moderate',
    'info': 'finding-info',
  }
  return classes[severity] || 'finding-info'
}

/** Purpose status icon — shows consent/LI/none status. */
function purposeStatusIcon(consented: boolean, li: boolean): string {
  if (consented && li) return '✅⚖️'
  if (consented) return '✅'
  if (li) return '⚖️'
  return '—'
}

/** Purpose status label for screen readers / tooltips. */
function purposeStatusLabel(consented: boolean, li: boolean): string {
  if (consented && li) return 'Consent + Legitimate Interest'
  if (consented) return 'Consent'
  if (li) return 'Legitimate Interest only'
  return 'No consent'
}


</script>

<template>
  <div class="tab-content">
    <div v-if="!consentDetails" class="empty-state">
      No consent dialog was detected
    </div>

    <div v-else class="consent-layout">

      <!-- ── Overview ────────────────────────────────── -->
      <section class="consent-meta">
        <h2 class="section-title">📊 Overview</h2>
        <p class="section-subtitle">
          Consent metrics from dialog analysis and verified consent signals
          decoded from TC &amp; AC Strings.
        </p>
        <p class="ai-section-summary">
          Under GDPR and ePrivacy rules, websites must obtain your informed consent before
          setting non-essential cookies or tracking your activity. Most sites use a Consent
          Management Platform (CMP) to present a dialog and record your choices. This tab
          shows what the dialog disclosed, which purposes and vendors were declared, and
          whether the encoded consent signals match what was actually presented to you.
        </p>
        <div class="meta-cards">
          <div v-if="consentDetails.consentPlatform" class="meta-card">
            <span class="meta-icon">🛡️</span>
            <span class="meta-label">Platform</span>
            <span class="meta-value">{{ consentDetails.consentPlatform }}</span>
          </div>
          <div v-if="consentDetails.claimedPartnerCount" class="meta-card"
               :class="{ 'meta-card-alert': tcValidation()?.vendorCountMismatch }">
            <span class="meta-icon">📢</span>
            <span class="meta-label">Partners Claimed</span>
            <span class="meta-value">{{ consentDetails.claimedPartnerCount }}</span>
            <span class="source-badge source-ai">dialog</span>
          </div>
          <div v-if="tcValidation()" class="meta-card"
               :class="{ 'meta-card-alert': tcValidation()!.vendorCountMismatch }">
            <span class="meta-icon">📜</span>
            <span class="meta-label">Vendor Consents</span>
            <span class="meta-value">{{ tcValidation()!.vendorConsentCount }}</span>
            <span class="source-badge source-tc">TC String</span>
          </div>
          <div v-if="tcValidation() && tcValidation()!.vendorLiCount > 0" class="meta-card">
            <span class="meta-icon">⚖️</span>
            <span class="meta-label">Legitimate Interest</span>
            <span class="meta-value">{{ tcValidation()!.vendorLiCount }}</span>
            <span class="source-badge source-tc">TC String</span>
          </div>
          <div v-if="acStringData()" class="meta-card">
            <span class="meta-icon">🔗</span>
            <span class="meta-label">Non-IAB Vendors</span>
            <span class="meta-value">{{ acStringData()!.vendorCount }}</span>
            <span class="source-badge source-ac">AC String</span>
          </div>
          <div v-if="consentDetails.purposes.length > 0" class="meta-card">
            <span class="meta-icon">🎯</span>
            <span class="meta-label">Purposes</span>
            <span class="meta-value">{{ consentDetails.purposes.length }}</span>
          </div>
          <div v-if="consentDetails.categories.length > 0" class="meta-card">
            <span class="meta-icon">📂</span>
            <span class="meta-label">Categories</span>
            <span class="meta-value">{{ consentDetails.categories.length }}</span>
          </div>
          <div class="meta-card">
            <span class="meta-icon">⚙️</span>
            <span class="meta-label">Manage Options</span>
            <span class="meta-value">{{ consentDetails.hasManageOptions ? 'Yes' : 'No' }}</span>
          </div>
        </div>

        <!-- Your Rights — deterministic note about user privacy rights -->
        <div v-if="structuredReport?.consentAnalysis?.userRightsNote" class="user-rights-note">
          <div class="user-rights-header">
            <span class="user-rights-icon">⚖️</span>
            <span class="user-rights-title">Your Rights</span>
          </div>
          <p class="user-rights-text">
            {{ structuredReport.consentAnalysis.userRightsNote }}
          </p>
        </div>

        <!-- AI Summary -->
        <p v-if="structuredReport?.consentAnalysis?.summary" class="overview-summary">
          {{ stripMarkdown(structuredReport.consentAnalysis.summary) }}
        </p>

        <!-- Vendor Summary -->
        <div v-if="vendorSummary.categories.length > 0" class="vendor-summary">
          <div class="vendor-summary-stats">
            <div class="vendor-summary-stat">
              <span class="vendor-summary-value">{{ vendorSummary.totalVendors }}</span>
              <span class="vendor-summary-label">Vendors Identified</span>
            </div>
            <div v-if="vendorSummary.vendorsWithConcerns > 0" class="vendor-summary-stat vendor-summary-warn">
              <span class="vendor-summary-value">{{ vendorSummary.vendorsWithConcerns }}</span>
              <span class="vendor-summary-label">With Concerns</span>
            </div>
          </div>
          <div class="vendor-category-summary">
            <div
              v-for="[cat, count] in vendorSummary.categories"
              :key="cat"
              class="vendor-cat-pill"
              :class="vendorCategoryClass(cat)"
            >
              <span class="vendor-cat-emoji">{{ categoryEmoji(cat) }}</span>
              <span class="vendor-cat-name">{{ cat }}</span>
              <span class="vendor-cat-count">{{ count }}</span>
            </div>
          </div>
        </div>

        <!-- IAB Vendor Consents -->
        <div v-if="consentDetails?.tcStringData?.resolvedVendorConsents?.length" class="vendor-list-toggle">
          <button class="vendor-toggle-btn" @click="showTcVendors = !showTcVendors">
            {{ showTcVendors ? '▾' : '▸' }}
            📜 IAB Vendor Consents
            ({{ consentDetails.tcStringData.resolvedVendorConsents.length }} identified)
          </button>
          <div v-if="showTcVendors" class="vendor-name-list">
            <div
              v-for="(v, idx) in consentDetails.tcStringData.resolvedVendorConsents"
              :key="idx"
              class="vendor-name-item"
              :class="{ 'vendor-has-concerns': v.concerns?.length }"
            >
              <div class="vendor-name-row">
                <span class="vendor-id">#{{ v.id }}</span>
                <a v-if="v.url" :href="v.url" target="_blank" rel="noopener" class="vendor-name vendor-name-link">{{ v.name }}</a>
                <span v-else class="vendor-name">{{ v.name }}</span>
                <a v-if="v.policy_url" :href="v.policy_url" target="_blank" rel="noopener" class="vendor-policy-link" title="Privacy policy">🔒</a>
                <span v-if="v.category" class="vendor-category-badge" :class="vendorCategoryClass(v.category)">{{ v.category }}</span>
              </div>
              <div v-if="v.concerns?.length" class="vendor-concerns-row">
                <span v-for="(c, ci) in v.concerns" :key="ci" class="concern-tag">⚠️ {{ c }}</span>
              </div>
            </div>
            <div v-if="consentDetails.tcStringData.unresolvedVendorConsentCount" class="vendor-unresolved-note">
              + {{ consentDetails.tcStringData.unresolvedVendorConsentCount }} vendor ID{{ consentDetails.tcStringData.unresolvedVendorConsentCount === 1 ? '' : 's' }} not listed in the IAB Global Vendor List
            </div>
          </div>
        </div>

        <!-- IAB Legitimate Interest Vendors -->
        <div v-if="consentDetails?.tcStringData?.resolvedVendorLi?.length" class="vendor-list-toggle">
          <button class="vendor-toggle-btn" @click="showTcVendorsLi = !showTcVendorsLi">
            {{ showTcVendorsLi ? '▾' : '▸' }}
            ⚖️ IAB Legitimate Interest Vendors
            ({{ consentDetails.tcStringData.resolvedVendorLi.length }} identified)
          </button>
          <div v-if="showTcVendorsLi" class="vendor-name-list">
            <div
              v-for="(v, idx) in consentDetails.tcStringData.resolvedVendorLi"
              :key="idx"
              class="vendor-name-item"
              :class="{ 'vendor-has-concerns': v.concerns?.length }"
            >
              <div class="vendor-name-row">
                <span class="vendor-id">#{{ v.id }}</span>
                <a v-if="v.url" :href="v.url" target="_blank" rel="noopener" class="vendor-name vendor-name-link">{{ v.name }}</a>
                <span v-else class="vendor-name">{{ v.name }}</span>
                <a v-if="v.policy_url" :href="v.policy_url" target="_blank" rel="noopener" class="vendor-policy-link" title="Privacy policy">🔒</a>
                <span v-if="v.category" class="vendor-category-badge" :class="vendorCategoryClass(v.category)">{{ v.category }}</span>
              </div>
              <div v-if="v.concerns?.length" class="vendor-concerns-row">
                <span v-for="(c, ci) in v.concerns" :key="ci" class="concern-tag">⚠️ {{ c }}</span>
              </div>
            </div>
            <div v-if="consentDetails.tcStringData.unresolvedVendorLiCount" class="vendor-unresolved-note">
              + {{ consentDetails.tcStringData.unresolvedVendorLiCount }} vendor ID{{ consentDetails.tcStringData.unresolvedVendorLiCount === 1 ? '' : 's' }} not listed in the IAB Global Vendor List
            </div>
          </div>
        </div>

        <!-- Google ATP Providers (AC String) -->
        <div v-if="acStringData()?.resolvedProviders?.length" class="vendor-list-toggle">
          <button class="vendor-toggle-btn ac-toggle" @click="showAcProviders = !showAcProviders">
            {{ showAcProviders ? '▾' : '▸' }}
            🔗 Google ATP Providers
            ({{ acStringData()!.resolvedProviders!.length }} identified)
          </button>
          <div v-if="showAcProviders" class="vendor-name-list">
            <div
              v-for="(p, idx) in acStringData()!.resolvedProviders"
              :key="idx"
              class="vendor-name-item"
              :class="{ 'vendor-has-concerns': p.concerns?.length }"
            >
              <div class="vendor-name-row">
                <span class="vendor-id">#{{ p.id }}</span>
                <a v-if="p.policy_url" :href="p.policy_url" target="_blank" rel="noopener" class="vendor-name vendor-name-link" title="Privacy policy">{{ p.name }}</a>
                <span v-else class="vendor-name">{{ p.name }}</span>
                <span v-if="p.category" class="vendor-category-badge" :class="vendorCategoryClass(p.category)">{{ p.category }}</span>
              </div>
              <div v-if="p.concerns?.length" class="vendor-concerns-row">
                <span v-for="(c, ci) in p.concerns" :key="ci" class="concern-tag">⚠️ {{ c }}</span>
              </div>
            </div>
            <div v-if="acStringData()!.unresolvedProviderCount" class="vendor-unresolved-note">
              + {{ acStringData()!.unresolvedProviderCount }} provider ID{{ acStringData()!.unresolvedProviderCount === 1 ? '' : 's' }} not listed in Google&rsquo;s published ATP register
            </div>
          </div>
        </div>

        <!-- Findings -->
        <div v-if="tcValidation()?.findings?.length" class="tc-findings">
          <h3 class="tc-subsection-title">Concerns</h3>
          <div
            v-for="(finding, idx) in tcValidation()!.findings"
            :key="idx"
            class="tc-finding"
            :class="findingSeverityClass(finding.severity)"
          >
            <div class="tc-finding-header">
              <span class="tc-finding-icon">{{ findingSeverityIcon(finding.severity) }}</span>
              <span class="tc-finding-severity" :class="findingSeverityClass(finding.severity)">{{ finding.severity }}</span>
              <span class="tc-finding-title">{{ finding.title }}</span>
            </div>
            <p class="tc-finding-detail">{{ finding.detail }}</p>
          </div>
        </div>

      </section>

      <!-- ── TCF Purpose Breakdown ──────────────────── -->
      <section v-if="consentDetails.purposes.length > 0" class="tcf-section">
        <h2 class="section-title">📋 Declared Purposes <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Purposes found in the consent dialog text by AI analysis, then
          mapped to the IAB Transparency &amp; Consent Framework (TCF) v2.2 taxonomy.
          Each purpose defines a specific way your data can be used.
          Some purposes may not be easily determined from the dialog wording
          and additional purposes may exist that could not be identified.
        </p>

        <div v-if="tcfLoading" class="tcf-loading">
          <span class="spinner"></span>
          Mapping purposes to TCF taxonomy…
        </div>

        <div v-else-if="tcfResult" class="tcf-purposes">
          <div
            v-for="purpose in tcfResult.matched"
            :key="`${purpose.category}-${purpose.id}`"
            class="purpose-card"
            :class="riskClass(purpose.riskLevel)"
          >
            <div class="purpose-card-header">
              <span class="purpose-id-badge" :class="riskClass(purpose.riskLevel)">
                {{ categoryIcon(purpose.category) }} {{ categoryLabel(purpose.category) }} {{ purpose.id }}
              </span>
              <span class="purpose-name">{{ purpose.name }}</span>
              <span class="purpose-risk-badge" :class="riskClass(purpose.riskLevel)">
                {{ riskEmoji(purpose.riskLevel) }} {{ purpose.riskLevel }}
              </span>
            </div>
            <p class="purpose-description">{{ purpose.description }}</p>
            <div class="purpose-footer">
              <div v-if="purpose.lawfulBases.length" class="purpose-bases">
                <span
                  v-for="basis in purpose.lawfulBases"
                  :key="basis"
                  class="basis-tag"
                >
                  {{ lawfulBasisLabel(basis) }}
                </span>
              </div>
              <span v-if="purpose.notes" class="purpose-note">💡 {{ purpose.notes }}</span>
            </div>
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

      <!-- ── Purpose Consent Matrix ─────────────────── -->
      <section v-if="tcValidation()" class="tc-verification-section">
        <h2 class="section-title">📊 Purpose Consent Matrix <span class="source-badge source-tc">TC String</span></h2>
        <p class="section-subtitle">
          All 11 IAB TCF purposes and their actual consent status as encoded
          in the TC String. The disclosure indicator shows whether each purpose
          could be matched to the dialog text by AI analysis &mdash; a
          &ldquo;not found&rdquo; marker means the purpose could not be easily
          determined from the dialog wording, not necessarily that it was
          absent.
        </p>
        <div class="tc-matrix-legend">
          <span class="tc-legend-item">✅ Consent given</span>
          <span class="tc-legend-item">⚖️ Legitimate Interest</span>
          <span class="tc-legend-item"><span class="tc-disclosed">✓</span> Disclosed in dialog</span>
          <span class="tc-legend-item"><span class="tc-undisclosed">?</span> Not found in dialog</span>
        </div>
        <div class="tcf-purposes">
          <div
            v-for="ps in tcValidation()!.purposeSignals"
            :key="ps.id"
            class="purpose-card"
            :class="[riskClass(ps.riskLevel), {
              'purpose-card-undisclosed': !ps.disclosedInDialog && (ps.consented || ps.legitimateInterest)
            }]"
          >
            <div class="purpose-card-header">
              <span class="purpose-id-badge" :class="riskClass(ps.riskLevel)">🎯 Purpose {{ ps.id }}</span>
              <span class="purpose-name">{{ ps.name }}</span>
              <span class="purpose-status-badges">
                <span v-if="ps.disclosedInDialog" class="purpose-disclosure-badge tc-disclosed" title="Disclosed in dialog">✓ Disclosed</span>
                <span v-else-if="ps.consented || ps.legitimateInterest" class="purpose-disclosure-badge tc-undisclosed" title="Could not be found easily in dialog text">? Not found</span>
                <span class="purpose-consent-badge" :title="purposeStatusLabel(ps.consented, ps.legitimateInterest)">
                  {{ purposeStatusIcon(ps.consented, ps.legitimateInterest) }}
                </span>
                <span class="purpose-risk-badge" :class="riskClass(ps.riskLevel)">
                  {{ riskEmoji(ps.riskLevel) }} {{ ps.riskLevel }}
                </span>
              </span>
            </div>
            <p class="purpose-description">{{ ps.description }}</p>
          </div>
        </div>
      </section>

      <!-- ── Consent Categories ─────────────────────── -->
      <section v-if="consentDetails.categories.length > 0" class="categories-section">
        <h2 class="section-title">📂 Consent Categories <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Cookie consent categories found in the dialog by AI analysis.
          Category names and descriptions may not be verbatim, and some
          categories may not have been easily determined from the dialog text.
        </p>
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

    </div>
  </div>
</template>

<style scoped>
.consent-layout {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.consent-meta {
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
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
  background: var(--surface-card);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  min-width: 7rem;
  flex: 1;
}

.meta-card-alert {
  border: 1px solid #f59e0b;
  background: #1f1a15;
}

.meta-icon {
  font-size: 1.5rem;
}

.meta-label {
  font-size: var(--stat-label-size);
  color: var(--stat-label-color);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.meta-value {
  font-size: var(--stat-value-size);
  font-weight: 700;
  color: var(--stat-value-color);
  text-align: center;
}

/* ── User Rights Note ────────────────────────── */
.user-rights-note {
  margin: 0.5rem 0 0;
  padding: 0.85rem 1rem;
  background: color-mix(in srgb, #10b981 8%, var(--surface-card));
  border-left: 3px solid #10b981;
  border-radius: 6px;
}

.user-rights-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.4rem;
}

.user-rights-icon {
  font-size: 1rem;
}

.user-rights-title {
  font-size: 0.82rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #10b981;
}

.user-rights-text {
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.55;
  color: var(--text-primary);
}

/* ── Overview Summary ────────────────────────── */
.overview-summary {
  color: var(--summary-color);
  font-size: 0.92rem;
  line-height: 1.5;
  margin: 0.75rem 0 0;
  padding: 0.65rem 0.85rem;
  background: var(--surface-card);
  border-radius: 6px;
}

/* ── Section Titles ──────────────────────────── */
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

.section-subtitle code {
  font-size: 0.78rem;
  background: var(--surface-code);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  color: #d1d5db;
}

.section-subtitle em {
  color: #9ca3af;
  font-style: italic;
}

/* ── Data Source Badges ──────────────────────── */
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

.source-tc {
  background: #1e1a3d;
  color: #a78bfa;
}

.source-ac {
  background: #1a3d27;
  color: #4ade80;
}

/* ── TCF Purpose Cards ──────────────────────── */
.tcf-section {
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
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
  border: 2px solid var(--border-separator);
  border-top-color: var(--link-color);
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
  gap: 0.5rem;
}

/* ── Unified Purpose Card ────────────────────── */
.purpose-card {
  background: var(--surface-card);
  border-radius: 6px;
  padding: 0.6rem 0.85rem;
  border-left: 4px solid var(--border-separator);
}

.purpose-card.risk-low { border-left-color: #22d3ee; }
.purpose-card.risk-medium { border-left-color: #fbbf24; }
.purpose-card.risk-high { border-left-color: #f87171; }
.purpose-card.risk-critical { border-left-color: #f472b6; }

.purpose-card-undisclosed {
  background: #1f1520;
}

.purpose-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.purpose-id-badge {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.12rem 0.45rem;
  border-radius: 4px;
  background: var(--surface-code);
  color: var(--muted-light);
  white-space: nowrap;
  flex-shrink: 0;
}

.purpose-id-badge.risk-low { color: #22d3ee; }
.purpose-id-badge.risk-medium { color: #fbbf24; }
.purpose-id-badge.risk-high { color: #f87171; }
.purpose-id-badge.risk-critical { color: #f472b6; }

.purpose-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: #e0e7ff;
  flex: 1;
  min-width: 0;
}

.purpose-risk-badge {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 0.12rem 0.45rem;
  border-radius: 4px;
  white-space: nowrap;
  flex-shrink: 0;
}

.purpose-risk-badge.risk-low { background: #1a2e3d; color: #22d3ee; }
.purpose-risk-badge.risk-medium { background: #3d3520; color: #fbbf24; }
.purpose-risk-badge.risk-high { background: #3d2020; color: #f87171; }
.purpose-risk-badge.risk-critical { background: #4a1a2e; color: #f472b6; }

.purpose-status-badges {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-left: auto;
  flex-shrink: 0;
}

.purpose-consent-badge {
  font-size: 0.8rem;
}

.purpose-disclosure-badge {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  white-space: nowrap;
}

.purpose-disclosure-badge.tc-disclosed {
  background: #052e16;
  color: #4ade80;
}

.purpose-disclosure-badge.tc-undisclosed {
  background: #3d2020;
  color: #f87171;
}

.purpose-description {
  font-size: var(--body-size);
  color: var(--body-color);
  margin: 0.3rem 0 0;
  line-height: 1.35;
}

.purpose-footer {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 0.35rem;
}

.purpose-bases {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.basis-tag {
  font-size: 0.7rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--surface-code);
  color: #d1d5db;
}

.purpose-note {
  font-size: 0.78rem;
  color: #f59e0b;
  line-height: 1.3;
}

/* ── Unmatched Purposes ─────────────────────── */
.unmatched-section {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-separator);
}

.unmatched-title {
  font-size: var(--subheading-size);
  font-weight: 600;
  color: var(--subheading-color);
  margin: 0 0 0.25rem;
}

.unmatched-item {
  padding: 0.4rem 0.75rem;
  background: var(--surface-card);
  border-radius: 4px;
  font-size: var(--body-size);
  color: var(--body-color);
  margin-bottom: 0.35rem;
}

/* ── Consent Categories ─────────────────────── */
.categories-section {
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.category-card {
  background: var(--surface-card);
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
  background: var(--surface-code);
  color: var(--muted-color);
}

.category-desc {
  font-size: var(--body-size);
  color: var(--body-color);
  margin: 0.3rem 0 0;
  line-height: 1.3;
}

/* ── TC String / Purpose Matrix ────────────── */
.tc-verification-section {
  padding: 1rem;
  background: var(--surface-section);
  border-radius: 8px;
  border: 1px solid var(--border-card);
}

.tc-subsection-title {
  font-size: var(--subheading-size);
  font-weight: 600;
  color: var(--subheading-color);
  margin: 0.75rem 0 0.2rem;
}

.tc-subsection-desc {
  font-size: var(--body-size);
  color: var(--muted-color);
  margin: 0 0 0.5rem;
  line-height: 1.4;
}

.tc-findings {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 1rem;
}

.tc-finding {
  border-radius: 6px;
  padding: 0.6rem 0.85rem;
  border-left: 4px solid var(--border-separator);
}

.tc-finding.finding-critical {
  background: #2d1520;
  border-left-color: #f472b6;
}

.tc-finding.finding-high {
  background: #2d1a15;
  border-left-color: #f87171;
}

.tc-finding.finding-moderate {
  background: #2d2815;
  border-left-color: #fbbf24;
}

.tc-finding.finding-info {
  background: #1a2030;
  border-left-color: #60a5fa;
}

.tc-finding-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.25rem;
}

.tc-finding-icon {
  font-size: 0.85rem;
}

.tc-finding-severity {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
}

.tc-finding-severity.finding-critical { background: #4a1a2e; color: #f472b6; }
.tc-finding-severity.finding-high { background: #3d2020; color: #f87171; }
.tc-finding-severity.finding-moderate { background: #3d3520; color: #fbbf24; }
.tc-finding-severity.finding-info { background: #1a2e3d; color: #60a5fa; }

.tc-finding-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #e0e7ff;
}

.tc-finding-detail {
  font-size: var(--body-size);
  color: var(--body-color);
  margin: 0;
  line-height: 1.4;
}

/* ── TC Purpose Matrix ─────────────────────── */
.tc-matrix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--surface-card);
  border-radius: 6px;
  margin-bottom: 0.5rem;
  font-size: 0.75rem;
  color: var(--muted-light);
}

.tc-legend-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.tc-disclosed {
  color: #4ade80;
  font-weight: 600;
}

.tc-undisclosed {
  color: #f87171;
  font-weight: 600;
}

/* ── Vendors Section ───────────────────────── */
.vendors-section {
  border-top: 1px solid var(--border-separator);
  padding-top: 1rem;
}

/* ── Vendor Summary ────────────────────────── */
.vendor-summary {
  background: var(--surface-card);
  border-radius: 8px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.25rem;
}

.vendor-summary-stats {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.vendor-summary-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
  background: #141726;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  min-width: 6.5rem;
}

.vendor-summary-stat.vendor-summary-warn {
  border: 1px solid #f59e0b55;
}

.vendor-summary-value {
  font-size: var(--stat-value-size);
  font-weight: 700;
  color: var(--stat-value-color);
}

.vendor-summary-warn .vendor-summary-value {
  color: #fbbf24;
}

.vendor-summary-label {
  font-size: var(--stat-label-size);
  color: var(--stat-label-color);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.vendor-category-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.vendor-cat-pill {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.6rem;
  border-radius: 16px;
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--surface-panel);
  color: #d1d5db;
}

.vendor-cat-pill.vendor-cat-ad { background: #7c2d1230; color: #fca5a5; }
.vendor-cat-pill.vendor-cat-broker { background: #7c2d1230; color: #f87171; }
.vendor-cat-pill.vendor-cat-identity { background: #78350f30; color: #fbbf24; }
.vendor-cat-pill.vendor-cat-replay { background: #78350f30; color: #fcd34d; }
.vendor-cat-pill.vendor-cat-analytics { background: #1e3a5f30; color: #93c5fd; }
.vendor-cat-pill.vendor-cat-social { background: #312e8130; color: #a5b4fc; }
.vendor-cat-pill.vendor-cat-mobile { background: #14532d30; color: #86efac; }
.vendor-cat-pill.vendor-cat-consent { background: #1f293730; color: #9ca3af; }
.vendor-cat-pill.vendor-cat-other { background: #1f293730; color: #9ca3af; }

.vendor-cat-emoji {
  font-size: 0.85rem;
}

.vendor-cat-name {
  white-space: nowrap;
}

.vendor-cat-count {
  background: #ffffff15;
  padding: 0.05rem 0.35rem;
  border-radius: 8px;
  font-size: 0.68rem;
  font-weight: 700;
  min-width: 1.2rem;
  text-align: center;
}

.vendor-list-toggle {
  margin-top: 0.5rem;
}

.vendor-toggle-btn {
  background: #1f2937;
  border: 1px solid #4b5563;
  border-radius: 4px;
  color: #e5e7eb;
  font-size: 0.92rem;
  font-weight: 500;
  padding: 0.5rem 0.85rem;
  cursor: pointer;
  transition: all 0.15s ease;
  width: 100%;
  text-align: left;
}

.vendor-toggle-btn:hover {
  background: #374151;
  color: #f9fafb;
  border-color: #6b7280;
}

.vendor-toggle-btn.ac-toggle:hover {
  border-color: #818cf8;
}

.vendor-name-list {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid #4b5563;
  border-top: none;
  border-radius: 0 0 4px 4px;
  background: #111827;
}

.vendor-name-item {
  padding: 0.3rem 0.75rem;
  font-size: 0.75rem;
  color: #d1d5db;
  border-bottom: 1px solid #1e293b;
}

.vendor-name-item:nth-child(even) {
  background: #1a2332;
}

.vendor-name-item:hover {
  background: #1e293b;
}

.vendor-name-item:last-child {
  border-bottom: none;
}

.vendor-name-item.vendor-has-concerns {
  padding-bottom: 0.45rem;
}

.vendor-name-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.vendor-concerns-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.25rem;
  padding-left: 3.5rem;
}

.vendor-id {
  color: #6b7280;
  font-family: monospace;
  font-size: 0.7rem;
  min-width: 3.5rem;
}

.vendor-name {
  flex: 1;
}

.vendor-name-link {
  color: var(--link-color);
  text-decoration: none;
  transition: color 0.15s;
}

.vendor-name-link:hover {
  color: var(--link-hover);
  text-decoration: underline;
}

.vendor-policy-link {
  font-size: 0.7rem;
  text-decoration: none;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.vendor-policy-link:hover {
  opacity: 1;
}

/* ── Vendor Enrichment Badges ──────────────── */
.vendor-category-badge {
  font-size: 0.6rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex-shrink: 0;
}

.vendor-cat-ad { background: #7c2d1240; color: #fca5a5; }
.vendor-cat-broker { background: #7c2d1240; color: #f87171; }
.vendor-cat-identity { background: #78350f40; color: #fbbf24; }
.vendor-cat-replay { background: #78350f40; color: #fcd34d; }
.vendor-cat-analytics { background: #1e3a5f40; color: #93c5fd; }
.vendor-cat-social { background: #312e8140; color: #a5b4fc; }
.vendor-cat-mobile { background: #14532d40; color: #86efac; }
.vendor-cat-consent { background: #1f293740; color: #9ca3af; }
.vendor-cat-other { background: #1f293740; color: #9ca3af; }

.concern-tag {
  font-size: 0.72rem;
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  background: #3d2020;
  color: #f87171;
}

.vendor-unresolved-note {
  padding: 0.4rem 0.65rem;
  font-size: 0.72rem;
  color: #6b7280;
  font-style: italic;
  border-top: 1px solid #1f2937;
}

/* ── TC Special Features ───────────────────── */
.tc-special-features {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 0.75rem;
}

.tc-special-feature-item {
  background: #2d1a20;
  border: 1px solid #f59e0b;
  border-radius: 4px;
  padding: 0.4rem 0.65rem;
  font-size: 0.82rem;
  color: #fbbf24;
  font-weight: 500;
}

</style>
