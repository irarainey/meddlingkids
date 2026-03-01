<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ConsentDetails, TcfPurpose, TcfLookupResult, TcValidationResult, TcValidationFinding, AcStringData } from '../../types'

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

/** Computed TC validation result. */
function tcValidation(): TcValidationResult | null {
  return props.consentDetails?.tcValidation ?? null
}

/** Computed AC String data (Google Additional Consent Mode). */
function acStringData(): AcStringData | null {
  return props.consentDetails?.acStringData ?? null
}

/** Track collapsed/expanded state for vendor lists. */
const showTcVendors = ref(false)
const showAcProviders = ref(false)

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
        <h2 class="section-title">📊 Overview <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Key metrics extracted from the consent dialog by AI analysis of the
          dialog text. These values are approximate and may contain errors.
        </p>
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
        <h2 class="section-title">📋 Declared Purposes <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Purposes extracted from the consent dialog text by AI analysis, then
          mapped to the IAB Transparency &amp; Consent Framework (TCF) v2.2 taxonomy.
          Each purpose defines a specific way your data can be used.
          AI extraction may not capture all purposes or may misinterpret dialog wording.
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

      <!-- ── TC String Verification ─────────────────── -->
      <section v-if="tcValidation() || acStringData()" class="tc-verification-section">
        <h2 class="section-title">🔍 Consent Verification
          <span v-if="tcValidation()" class="source-badge source-tc">TC String</span>
          <span v-if="acStringData()" class="source-badge source-ac">AC String</span>
        </h2>
        <p class="section-subtitle">
          After the consent dialog was accepted, the CMP wrote machine-readable
          consent signals to browser cookies. The <em>TC String</em>
          (<code>euconsent-v2</code>) encodes IAB-registered vendor consents;
          <span v-if="acStringData()">the <em>AC String</em>
          (<code>addtl_consent</code>) lists additional non-IAB ad-tech providers
          that received consent via Google&rsquo;s Additional Consent Mode.
          Both are</span>
          <span v-else>this data is</span>
          decoded below and cross-referenced against the dialog text shown to users.
        </p>

        <!-- Findings -->
        <div v-if="tcValidation() && tcValidation()!.findings.length > 0" class="tc-findings">
          <h3 class="tc-subsection-title">Findings</h3>
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

        <!-- Vendor Comparison -->
        <div v-if="tcValidation()" class="tc-subsection">
          <h3 class="tc-subsection-title">Vendor Comparison</h3>
          <p class="tc-subsection-desc">
            The dialog&rsquo;s partner count and the TC String&rsquo;s vendor
            consent count may differ for legitimate reasons: the dialog may
            include non-TCF vendors, downstream data-sharing partners, or
            vendors using Google&rsquo;s Additional Consent Mode, none of which
            appear in the TC String. Equally, the TC String may reference
            IAB-registered vendors not individually named in the dialog.
          </p>
          <div class="tc-vendor-row">
            <div v-if="tcValidation()!.claimedPartnerCount" class="tc-stat-card" :class="{ 'tc-stat-mismatch': tcValidation()!.vendorCountMismatch }">
              <span class="tc-stat-icon">💬</span>
              <span class="tc-stat-label">Dialog Claims</span>
              <span class="tc-stat-value">{{ tcValidation()!.claimedPartnerCount }}</span>
              <span class="tc-stat-source">from dialog text</span>
            </div>
            <div class="tc-stat-card" :class="{ 'tc-stat-mismatch': tcValidation()!.vendorCountMismatch }">
              <span class="tc-stat-icon">📜</span>
              <span class="tc-stat-label">Vendor Consents</span>
              <span class="tc-stat-value">{{ tcValidation()!.vendorConsentCount }}</span>
              <span class="tc-stat-source">from TC String</span>
            </div>
            <div v-if="tcValidation()!.vendorLiCount > 0" class="tc-stat-card">
              <span class="tc-stat-icon">⚖️</span>
              <span class="tc-stat-label">Legitimate Interest</span>
              <span class="tc-stat-value">{{ tcValidation()!.vendorLiCount }}</span>
              <span class="tc-stat-source">from TC String</span>
            </div>
            <div v-if="acStringData()" class="tc-stat-card tc-stat-ac">
              <span class="tc-stat-icon">🔗</span>
              <span class="tc-stat-label">Non-IAB Vendors</span>
              <span class="tc-stat-value">{{ acStringData()!.vendorCount }}</span>
              <span class="tc-stat-source">from AC String</span>
            </div>
          </div>

          <!-- Expandable IAB vendor list -->
          <div v-if="consentDetails?.tcStringData?.resolvedVendorConsents?.length" class="vendor-list-toggle">
            <button class="vendor-toggle-btn" @click="showTcVendors = !showTcVendors">
              {{ showTcVendors ? '▾' : '▸' }}
              {{ showTcVendors ? 'Hide' : 'Show' }} IAB vendor names
              ({{ consentDetails.tcStringData.resolvedVendorConsents.length }} identified)
            </button>
            <div v-if="showTcVendors" class="vendor-name-list">
              <div
                v-for="(v, idx) in consentDetails.tcStringData.resolvedVendorConsents"
                :key="idx"
                class="vendor-name-item"
              >
                <span class="vendor-id">#{{ v.id }}</span>
                <span class="vendor-name">{{ v.name }}</span>
              </div>
              <div v-if="consentDetails.tcStringData.unresolvedVendorConsentCount" class="vendor-unresolved-note">
                + {{ consentDetails.tcStringData.unresolvedVendorConsentCount }} vendor ID{{ consentDetails.tcStringData.unresolvedVendorConsentCount === 1 ? '' : 's' }} not listed in the IAB Global Vendor List
              </div>
            </div>
          </div>

          <!-- Expandable AC provider list -->
          <div v-if="acStringData()?.resolvedProviders?.length" class="vendor-list-toggle">
            <button class="vendor-toggle-btn ac-toggle" @click="showAcProviders = !showAcProviders">
              {{ showAcProviders ? '▾' : '▸' }}
              {{ showAcProviders ? 'Hide' : 'Show' }} Google ATP provider names
              ({{ acStringData()!.resolvedProviders!.length }} identified)
            </button>
            <div v-if="showAcProviders" class="vendor-name-list">
              <div
                v-for="(p, idx) in acStringData()!.resolvedProviders"
                :key="idx"
                class="vendor-name-item"
              >
                <span class="vendor-id">#{{ p.id }}</span>
                <span class="vendor-name">{{ p.name }}</span>
                <a v-if="p.policy_url" :href="p.policy_url" target="_blank" rel="noopener" class="vendor-policy-link" title="Privacy policy">🔗</a>
              </div>
              <div v-if="acStringData()!.unresolvedProviderCount" class="vendor-unresolved-note">
                + {{ acStringData()!.unresolvedProviderCount }} provider ID{{ acStringData()!.unresolvedProviderCount === 1 ? '' : 's' }} not listed in Google&rsquo;s published ATP register
              </div>
            </div>
          </div>
        </div>

        <!-- AC String Only (no TC String) -->
        <div v-if="!tcValidation() && acStringData()" class="tc-subsection">
          <h3 class="tc-subsection-title">Google Additional Consent Mode</h3>
          <p class="tc-subsection-desc">
            The <code>addtl_consent</code> cookie contains a Google AC String
            listing non-IAB ad-tech providers that received consent. No IAB TC
            String was found for this site.
          </p>
          <div class="tc-vendor-row">
            <div class="tc-stat-card tc-stat-ac">
              <span class="tc-stat-icon">🔗</span>
              <span class="tc-stat-label">Non-IAB Vendors</span>
              <span class="tc-stat-value">{{ acStringData()!.vendorCount }}</span>
              <span class="tc-stat-source">from AC String</span>
            </div>
          </div>

          <!-- Expandable AC provider list (AC-only section) -->
          <div v-if="acStringData()?.resolvedProviders?.length" class="vendor-list-toggle">
            <button class="vendor-toggle-btn ac-toggle" @click="showAcProviders = !showAcProviders">
              {{ showAcProviders ? '▾' : '▸' }}
              {{ showAcProviders ? 'Hide' : 'Show' }} Google ATP provider names
              ({{ acStringData()!.resolvedProviders!.length }} identified)
            </button>
            <div v-if="showAcProviders" class="vendor-name-list">
              <div
                v-for="(p, idx) in acStringData()!.resolvedProviders"
                :key="idx"
                class="vendor-name-item"
              >
                <span class="vendor-id">#{{ p.id }}</span>
                <span class="vendor-name">{{ p.name }}</span>
                <a v-if="p.policy_url" :href="p.policy_url" target="_blank" rel="noopener" class="vendor-policy-link" title="Privacy policy">🔗</a>
              </div>
              <div v-if="acStringData()!.unresolvedProviderCount" class="vendor-unresolved-note">
                + {{ acStringData()!.unresolvedProviderCount }} provider ID{{ acStringData()!.unresolvedProviderCount === 1 ? '' : 's' }} not listed in Google&rsquo;s published ATP register
              </div>
            </div>
          </div>
        </div>
        <div v-if="tcValidation() && tcValidation()!.specialFeatures.length > 0" class="tc-special-features">
          <h3 class="tc-subsection-title">Special Feature Opt-ins</h3>
          <p class="tc-subsection-desc">
            Special features require explicit user consent under TCF. These are
            opted in via the TC String.
          </p>
          <div
            v-for="sf in tcValidation()!.specialFeatures"
            :key="sf"
            class="tc-special-feature-item"
          >
            ⚡ {{ sf }}
          </div>
        </div>

        <!-- Purpose Consent Matrix -->
        <div v-if="tcValidation()" class="tc-purpose-matrix">
          <h3 class="tc-subsection-title">Purpose Consent Matrix</h3>
          <p class="tc-subsection-desc">
            All 11 IAB TCF purposes and their actual consent status as encoded
            in the TC String. The &ldquo;In Dialog&rdquo; column shows whether
            each purpose was matched to the dialog text by AI analysis &mdash;
            a &ldquo;✗&rdquo; may indicate the purpose was not disclosed, or
            that the AI did not recognise the dialog&rsquo;s wording for it.
          </p>
          <div class="tc-matrix-legend">
            <span class="tc-legend-item">✅ Consent given</span>
            <span class="tc-legend-item">⚖️ Legitimate Interest</span>
            <span class="tc-legend-item"><span class="tc-disclosed">✓</span> Shown in dialog</span>
            <span class="tc-legend-item"><span class="tc-undisclosed">✗</span> Not in dialog</span>
            <span class="tc-legend-item"><span class="tc-legend-swatch"></span> Undisclosed consent</span>
          </div>
          <div class="tc-matrix-grid">
            <div class="tc-matrix-header">
              <span class="tc-matrix-col-id">ID</span>
              <span class="tc-matrix-col-name">Purpose</span>
              <span class="tc-matrix-col-status">Status</span>
              <span class="tc-matrix-col-risk">Risk</span>
              <span class="tc-matrix-col-dialog">In Dialog</span>
            </div>
            <div
              v-for="ps in tcValidation()!.purposeSignals"
              :key="ps.id"
              class="tc-matrix-row"
              :class="{
                'tc-row-undisclosed': !ps.disclosedInDialog && (ps.consented || ps.legitimateInterest),
                'tc-row-consented': ps.consented
              }"
            >
              <span class="tc-matrix-col-id">{{ ps.id }}</span>
              <span class="tc-matrix-col-name">{{ ps.name }}</span>
              <span class="tc-matrix-col-status" :title="purposeStatusLabel(ps.consented, ps.legitimateInterest)">
                {{ purposeStatusIcon(ps.consented, ps.legitimateInterest) }}
              </span>
              <span class="tc-matrix-col-risk">
                <span class="tc-risk-dot" :class="riskClass(ps.riskLevel)"></span>
                {{ ps.riskLevel }}
              </span>
              <span class="tc-matrix-col-dialog">
                <span v-if="ps.disclosedInDialog" class="tc-disclosed">✓</span>
                <span v-else-if="ps.consented || ps.legitimateInterest" class="tc-undisclosed">✗</span>
                <span v-else class="tc-na">—</span>
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Consent Categories ─────────────────────── -->
      <section v-if="consentDetails.categories.length > 0" class="categories-section">
        <h2 class="section-title">📂 Consent Categories <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Cookie consent categories disclosed in the dialog, extracted by AI
          analysis. Category names and descriptions may not be verbatim.
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

      <!-- ── Partners by Risk Level ─────────────────── -->
      <section v-if="consentDetails.partners.length > 0" class="partners-section">
        <h2 class="section-title">👥 Declared Partners <span class="source-badge source-ai">from dialog</span></h2>
        <p class="section-subtitle">
          Third-party vendors declared in the consent dialog, extracted by AI
          analysis and grouped by privacy risk classification. The AI may omit
          partners or misread names from the dialog text.
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
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-subtitle {
  font-size: 0.85rem;
  color: #6b7280;
  margin: 0 0 0.75rem;
  line-height: 1.4;
}

.section-subtitle code {
  font-size: 0.78rem;
  background: #2a2f45;
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
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.15rem 0.45rem;
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

/* ── TC String Verification ────────────────── */
.tc-verification-section {
  border-top: 1px solid #3d4663;
  padding-top: 1rem;
}

/* ── TC Sub-sections ───────────────────────── */
.tc-subsection {
  margin-bottom: 0.75rem;
}

.tc-subsection-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #e0e7ff;
  margin: 0.75rem 0 0.2rem;
}

.tc-subsection-desc {
  font-size: 0.8rem;
  color: #6b7280;
  margin: 0 0 0.5rem;
  line-height: 1.4;
}

.tc-findings {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.tc-finding {
  border-radius: 6px;
  padding: 0.6rem 0.85rem;
  border-left: 4px solid #3d4663;
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
  font-size: 0.8rem;
  color: #9ca3af;
  margin: 0;
  line-height: 1.4;
}

/* ── TC Vendor / Stats Row ─────────────────── */
.tc-vendor-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.tc-stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  background: #1a1e30;
  border-radius: 8px;
  padding: 0.65rem 0.85rem;
  min-width: 7rem;
  flex: 1;
}

.tc-stat-card.tc-stat-mismatch {
  border: 1px solid #f87171;
  background: #1f1520;
}

.tc-stat-card.tc-stat-alert {
  border: 1px solid #f59e0b;
  background: #1f1a15;
}

.tc-stat-card.tc-stat-ac {
  border: 1px solid #4ade80;
  background: #0f1f15;
}

.tc-stat-icon {
  font-size: 1.3rem;
}

.tc-stat-label {
  font-size: 0.65rem;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-align: center;
}

.tc-stat-value {
  font-size: 1.2rem;
  font-weight: 700;
  color: #e0e7ff;
}

.tc-stat-source {
  font-size: 0.6rem;
  color: #4b5563;
  font-style: italic;
  text-align: center;
}

/* ── Vendor Name Lists ─────────────────────── */
.vendor-list-toggle {
  margin-top: 0.5rem;
}

.vendor-toggle-btn {
  background: transparent;
  border: 1px solid #374151;
  border-radius: 4px;
  color: #9ca3af;
  font-size: 0.78rem;
  padding: 0.3rem 0.65rem;
  cursor: pointer;
  transition: all 0.15s ease;
  width: 100%;
  text-align: left;
}

.vendor-toggle-btn:hover {
  background: #1f2937;
  color: #e5e7eb;
  border-color: #4b5563;
}

.vendor-toggle-btn.ac-toggle:hover {
  border-color: #6366f1;
}

.vendor-name-list {
  max-height: 240px;
  overflow-y: auto;
  border: 1px solid #374151;
  border-top: none;
  border-radius: 0 0 4px 4px;
  background: #111827;
}

.vendor-name-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.65rem;
  font-size: 0.75rem;
  color: #d1d5db;
  border-bottom: 1px solid #1f2937;
}

.vendor-name-item:last-child {
  border-bottom: none;
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

.vendor-policy-link {
  font-size: 0.7rem;
  text-decoration: none;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.vendor-policy-link:hover {
  opacity: 1;
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
  margin-bottom: 0.75rem;
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

/* ── TC Purpose Matrix ─────────────────────── */
.tc-purpose-matrix {
  margin-top: 0.5rem;
}

.tc-matrix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #1a1e30;
  border-radius: 6px;
  margin-bottom: 0.5rem;
  font-size: 0.75rem;
  color: #9ca3af;
}

.tc-legend-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.tc-legend-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  background: #1f1520;
  border: 1px solid #3d2040;
}

.tc-matrix-grid {
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #2a2f45;
}

.tc-matrix-header {
  display: grid;
  grid-template-columns: 2.5rem 1fr 4rem 5rem 5rem;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #1a1e30;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6b7280;
}

.tc-matrix-row {
  display: grid;
  grid-template-columns: 2.5rem 1fr 4rem 5rem 5rem;
  gap: 0.5rem;
  padding: 0.4rem 0.75rem;
  border-top: 1px solid #1e2235;
  font-size: 0.82rem;
  color: #d1d5db;
  align-items: center;
}

.tc-matrix-row:hover {
  background: #1a1e30;
}

.tc-matrix-row.tc-row-undisclosed {
  background: #1f1520;
}

.tc-matrix-row.tc-row-undisclosed:hover {
  background: #251a28;
}

.tc-matrix-col-id {
  color: #6b7280;
  font-weight: 600;
  text-align: center;
}

.tc-matrix-col-name {
  color: #e0e7ff;
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tc-matrix-col-status {
  text-align: center;
}

.tc-matrix-col-risk {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.72rem;
  text-transform: capitalize;
}

.tc-risk-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  background: #6b7280;
}

.tc-risk-dot.risk-low { background: #22d3ee; }
.tc-risk-dot.risk-medium { background: #fbbf24; }
.tc-risk-dot.risk-high { background: #f87171; }
.tc-risk-dot.risk-critical { background: #f472b6; }

.tc-matrix-col-dialog {
  text-align: center;
}

.tc-disclosed {
  color: #4ade80;
  font-weight: 600;
}

.tc-undisclosed {
  color: #f87171;
  font-weight: 600;
}

.tc-na {
  color: #4b5563;
}
</style>
