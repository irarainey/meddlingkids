<script setup lang="ts">
import type { StructuredReport, TrackerEntry, SummaryFinding, SummaryFindingType } from '../../types'
import { getExclamation, getRiskLevel, getScoreClass } from '../../utils'

/**
 * Tab panel displaying structured privacy analysis report.
 *
 * Includes a summary section with privacy score and key findings
 * at the top, followed by deterministic sections rendered from
 * typed data rather than free-form markdown.
 */
defineProps<{
  /** Whether analysis is currently in progress */
  isAnalyzing: boolean
  /** Analysis error message if failed */
  analysisError: string
  /** Structured report from per-section LLM calls */
  structuredReport: StructuredReport | null
  /** Structured summary findings from AI analysis */
  summaryFindings: SummaryFinding[]
  /** Privacy score (0-100) */
  privacyScore: number | null
  /** One-sentence score summary from deterministic scorer */
  privacySummary: string
}>()

/** Colour-coded severity/risk badge class. */
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

/** Flat list of all trackers across all categories. */
function allTrackers(report: StructuredReport): TrackerEntry[] {
  const t = report.trackingTechnologies
  return [
    ...t.analytics,
    ...t.advertising,
    ...t.identityResolution,
    ...t.socialMedia,
    ...t.other,
  ]
}

/** Whether a tracker category has entries. */
function hasTrackers(entries: TrackerEntry[]): boolean {
  return entries.length > 0
}

/** Map summary finding type to badge class. */
function findingSeverityClass(type: SummaryFindingType): string {
  switch (type) {
    case 'critical': return 'badge-critical'
    case 'high': return 'badge-high'
    case 'moderate': return 'badge-medium'
    case 'info': return 'badge-none'
    case 'positive': return 'badge-low'
    default: return 'badge-medium'
  }
}

/** Map summary finding type to display label. */
function findingLabel(type: SummaryFindingType): string {
  switch (type) {
    case 'critical': return 'Critical'
    case 'high': return 'High'
    case 'moderate': return 'Moderate'
    case 'info': return 'Info'
    case 'positive': return 'Good'
    default: return type
  }
}
</script>

<template>
  <div class="tab-content analysis-content">
    <!-- Loading state -->
    <div v-if="isAnalyzing" class="analyzing-state">
      <div class="analyzing-spinner"></div>
      <p>Building structured privacy report...</p>
      <p class="analyzing-hint">Analysing each section individually for accuracy</p>
    </div>

    <!-- Error state -->
    <div v-else-if="analysisError" class="analysis-error">
      <p>⚠️ {{ analysisError }}</p>
    </div>

    <!-- Structured report -->
    <div v-else-if="structuredReport" class="structured-report">

      <!-- Score banner at the very top -->
      <div v-if="privacyScore != null && privacyScore >= 0" class="privacy-score-banner" :class="getScoreClass(privacyScore)">
        <div class="score-heading">
          <span class="score-exclamation">{{ getExclamation(privacyScore) }}</span>
          <span class="score-value">{{ privacyScore }}</span>
          <span class="score-label">{{ getRiskLevel(privacyScore) }}</span>
        </div>
        <p v-if="privacySummary" class="score-summary">{{ privacySummary }} The score is calculated deterministically from tracking data — the AI analysis below may highlight individual practices that are more or less severe.</p>
      </div>

      <!-- ── Summary: Key Findings ─────────────────────────── -->
      <section v-if="summaryFindings.length > 0" class="report-section">
        <h2>
          <span class="section-icon">🛡️</span>
          Summary
        </h2>
        <ul class="factor-list">
          <li
            v-for="(finding, index) in summaryFindings"
            :key="index"
            class="factor-item"
          >
            <span class="severity-dot" :class="findingSeverityClass(finding.type)"></span>
            <span class="factor-text">{{ finding.text }}</span>
            <span class="badge" :class="findingSeverityClass(finding.type)">{{ findingLabel(finding.type) }}</span>
          </li>
        </ul>
      </section>

      <!-- ── Section 1: Privacy Risk Assessment ─────────────── -->
      <section class="report-section risk-section">
        <h2>
          <span class="section-icon">🛡️</span>
          Privacy Risk Assessment
          <span
            class="risk-badge"
            :class="severityClass(structuredReport.privacyRisk.overallRisk)"
          >{{ riskLabel(structuredReport.privacyRisk.overallRisk) }} Risk</span>
        </h2>
        <p v-if="structuredReport.privacyRisk.summary" class="section-summary">
          {{ structuredReport.privacyRisk.summary }}
        </p>
        <ul v-if="structuredReport.privacyRisk.factors.length" class="factor-list">
          <li
            v-for="(factor, i) in structuredReport.privacyRisk.factors"
            :key="i"
            class="factor-item"
          >
            <span class="severity-dot" :class="severityClass(factor.severity)"></span>
            <span class="factor-text">{{ factor.description }}</span>
            <span class="badge" :class="severityClass(factor.severity)">{{ riskLabel(factor.severity) }}</span>
          </li>
        </ul>
      </section>

      <!-- ── Section 2: Tracking Technologies ───────────────── -->
      <section class="report-section">
        <h2>
          <span class="section-icon">📡</span>
          Tracking Technologies
          <span class="count-badge">{{ allTrackers(structuredReport).length }} detected</span>
        </h2>

        <!-- Analytics -->
        <div v-if="hasTrackers(structuredReport.trackingTechnologies.analytics)" class="tracker-category">
          <h3>📊 Analytics &amp; Measurement</h3>
          <div
            v-for="tracker in structuredReport.trackingTechnologies.analytics"
            :key="tracker.name"
            class="tracker-card"
          >
            <div class="tracker-header">
              <strong>{{ tracker.name }}</strong>
              <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
            </div>
            <p class="tracker-purpose">{{ tracker.purpose }}</p>
            <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
              <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
              <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
            </div>
          </div>
        </div>

        <!-- Advertising -->
        <div v-if="hasTrackers(structuredReport.trackingTechnologies.advertising)" class="tracker-category">
          <h3>📢 Advertising Networks</h3>
          <div
            v-for="tracker in structuredReport.trackingTechnologies.advertising"
            :key="tracker.name"
            class="tracker-card"
          >
            <div class="tracker-header">
              <strong>{{ tracker.name }}</strong>
              <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
            </div>
            <p class="tracker-purpose">{{ tracker.purpose }}</p>
            <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
              <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
              <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
            </div>
          </div>
        </div>

        <!-- Identity Resolution -->
        <div v-if="hasTrackers(structuredReport.trackingTechnologies.identityResolution)" class="tracker-category">
          <h3>🔗 Identity Resolution</h3>
          <div
            v-for="tracker in structuredReport.trackingTechnologies.identityResolution"
            :key="tracker.name"
            class="tracker-card"
          >
            <div class="tracker-header">
              <strong>{{ tracker.name }}</strong>
              <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
            </div>
            <p class="tracker-purpose">{{ tracker.purpose }}</p>
            <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
              <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
              <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
            </div>
          </div>
        </div>

        <!-- Social Media -->
        <div v-if="hasTrackers(structuredReport.trackingTechnologies.socialMedia)" class="tracker-category">
          <h3>💬 Social Media</h3>
          <div
            v-for="tracker in structuredReport.trackingTechnologies.socialMedia"
            :key="tracker.name"
            class="tracker-card"
          >
            <div class="tracker-header">
              <strong>{{ tracker.name }}</strong>
              <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
            </div>
            <p class="tracker-purpose">{{ tracker.purpose }}</p>
            <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
              <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
              <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
            </div>
          </div>
        </div>

        <!-- Other -->
        <div v-if="hasTrackers(structuredReport.trackingTechnologies.other)" class="tracker-category">
          <h3>🔧 Other Technologies</h3>
          <div
            v-for="tracker in structuredReport.trackingTechnologies.other"
            :key="tracker.name"
            class="tracker-card"
          >
            <div class="tracker-header">
              <strong>{{ tracker.name }}</strong>
              <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
            </div>
            <p class="tracker-purpose">{{ tracker.purpose }}</p>
            <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
              <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
              <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Section 3: Data Collection ──────────────────────── -->
      <section v-if="structuredReport.dataCollection.items.length" class="report-section">
        <h2>
          <span class="section-icon">📥</span>
          Data Collection
        </h2>
        <div
          v-for="(item, i) in structuredReport.dataCollection.items"
          :key="i"
          class="data-card"
          :class="{ 'data-card-sensitive': item.sensitive }"
        >
          <div class="data-card-header">
            <strong>{{ item.category }}</strong>
            <span v-if="item.sensitive" class="badge badge-sensitive">⚠ Sensitive</span>
            <span class="badge" :class="severityClass(item.risk)">{{ riskLabel(item.risk) }}</span>
          </div>
          <ul class="data-details">
            <li v-for="(detail, j) in item.details" :key="j">{{ detail }}</li>
          </ul>
          <div v-if="item.sharedWith.length" class="shared-with">
            <span class="shared-label">Shared with:</span>
            <span v-for="party in item.sharedWith" :key="party" class="shared-chip">{{ party }}</span>
          </div>
        </div>
      </section>

      <!-- ── Section 4: Third-Party Services ─────────────────── -->
      <section v-if="structuredReport.thirdPartyServices.groups.length" class="report-section">
        <h2>
          <span class="section-icon">🌐</span>
          Third-Party Services
          <span class="count-badge">{{ structuredReport.thirdPartyServices.totalDomains }} domains</span>
        </h2>
        <p v-if="structuredReport.thirdPartyServices.summary" class="section-summary">
          {{ structuredReport.thirdPartyServices.summary }}
        </p>
        <div
          v-for="(group, i) in structuredReport.thirdPartyServices.groups"
          :key="i"
          class="third-party-group"
        >
          <h3>{{ group.category }}</h3>
          <div class="services-list">
            <span v-for="service in group.services" :key="service" class="service-chip">
              {{ service }}
            </span>
          </div>
          <p class="impact-text">{{ group.privacyImpact }}</p>
        </div>
      </section>

      <!-- ── Section 5: Cookie Analysis ──────────────────────── -->
      <section v-if="structuredReport.cookieAnalysis.groups.length" class="report-section">
        <h2>
          <span class="section-icon">🍪</span>
          Cookie Analysis
          <span class="count-badge">{{ structuredReport.cookieAnalysis.total }} cookies</span>
        </h2>
        <div
          v-for="(group, i) in structuredReport.cookieAnalysis.groups"
          :key="i"
          class="cookie-group"
        >
          <div class="cookie-group-header">
            <h3>{{ group.category }}</h3>
            <span class="badge" :class="severityClass(group.concernLevel)">{{ riskLabel(group.concernLevel) }}</span>
            <span v-if="group.lifespan" class="lifespan-tag">⏱ {{ group.lifespan }}</span>
          </div>
          <div class="cookie-names">
            <code v-for="cookie in group.cookies" :key="cookie">{{ cookie }}</code>
          </div>
        </div>
        <div v-if="structuredReport.cookieAnalysis.concerningCookies.length" class="concerning-section">
          <h3>⚠️ Concerning Cookies</h3>
          <ul>
            <li v-for="(concern, i) in structuredReport.cookieAnalysis.concerningCookies" :key="i">
              {{ concern }}
            </li>
          </ul>
        </div>
      </section>

      <!-- ── Section 6: Storage Analysis ─────────────────────── -->
      <section
        v-if="structuredReport.storageAnalysis.localStorageCount > 0
          || structuredReport.storageAnalysis.sessionStorageCount > 0"
        class="report-section"
      >
        <h2>
          <span class="section-icon">💾</span>
          Storage Analysis
        </h2>
        <div class="storage-stats">
          <div class="stat-card">
            <span class="stat-value">{{ structuredReport.storageAnalysis.localStorageCount }}</span>
            <span class="stat-label">localStorage items</span>
          </div>
          <div class="stat-card">
            <span class="stat-value">{{ structuredReport.storageAnalysis.sessionStorageCount }}</span>
            <span class="stat-label">sessionStorage items</span>
          </div>
        </div>
        <p v-if="structuredReport.storageAnalysis.summary" class="section-summary">
          {{ structuredReport.storageAnalysis.summary }}
        </p>
        <div v-if="structuredReport.storageAnalysis.localStorageConcerns.length" class="storage-concerns">
          <h3>localStorage Concerns</h3>
          <ul>
            <li v-for="(concern, i) in structuredReport.storageAnalysis.localStorageConcerns" :key="i">{{ concern }}</li>
          </ul>
        </div>
        <div v-if="structuredReport.storageAnalysis.sessionStorageConcerns.length" class="storage-concerns">
          <h3>sessionStorage Concerns</h3>
          <ul>
            <li v-for="(concern, i) in structuredReport.storageAnalysis.sessionStorageConcerns" :key="i">{{ concern }}</li>
          </ul>
        </div>
      </section>

      <!-- ── Section 7: Consent Analysis ─────────────────────── -->
      <section v-if="structuredReport.consentAnalysis.hasConsentDialog" class="report-section">
        <h2>
          <span class="section-icon">🎯</span>
          Consent Dialog Analysis
        </h2>
        <div class="consent-stats">
          <div class="stat-card">
            <span class="stat-value">{{ structuredReport.consentAnalysis.categoriesDisclosed }}</span>
            <span class="stat-label">Categories Disclosed</span>
          </div>
          <div class="stat-card">
            <span class="stat-value">{{ structuredReport.consentAnalysis.partnersDisclosed }}</span>
            <span class="stat-label">Partners Disclosed</span>
          </div>
        </div>
        <p v-if="structuredReport.consentAnalysis.summary" class="section-summary">
          {{ structuredReport.consentAnalysis.summary }}
        </p>
        <div v-if="structuredReport.consentAnalysis.discrepancies.length" class="discrepancies">
          <h3>⚠️ Discrepancies Found</h3>
          <div
            v-for="(d, i) in structuredReport.consentAnalysis.discrepancies"
            :key="i"
            class="discrepancy-card"
          >
            <span class="badge" :class="severityClass(d.severity)">{{ riskLabel(d.severity) }}</span>
            <div class="discrepancy-detail">
              <div class="discrepancy-row">
                <span class="discrepancy-label">Claimed:</span>
                <span>{{ d.claimed }}</span>
              </div>
              <div class="discrepancy-row">
                <span class="discrepancy-label">Actual:</span>
                <span>{{ d.actual }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Section 8: Top Vendors ──────────────────────────── -->
      <section v-if="structuredReport.keyVendors.vendors.length" class="report-section">
        <h2>
          <span class="section-icon">🏢</span>
          Top Vendors and Partners
          <span class="count-badge">{{ structuredReport.keyVendors.vendors.length }}</span>
        </h2>
        <div class="vendor-grid">
          <div
            v-for="vendor in structuredReport.keyVendors.vendors"
            :key="vendor.name"
            class="vendor-card"
          >
            <div class="vendor-header">
              <strong>{{ vendor.name }}</strong>
              <span class="vendor-role">{{ vendor.role }}</span>
            </div>
            <p class="vendor-impact">{{ vendor.privacyImpact }}</p>
          </div>
        </div>
      </section>

      <!-- ── Section 9: Recommendations ──────────────────────── -->
      <section v-if="structuredReport.recommendations.groups.length" class="report-section recommendations-section">
        <h2>
          <span class="section-icon">✅</span>
          Recommendations
        </h2>
        <div
          v-for="(group, i) in structuredReport.recommendations.groups"
          :key="i"
          class="recommendation-group"
        >
          <h3>{{ group.category }}</h3>
          <ul>
            <li v-for="(item, j) in group.items" :key="j">{{ item }}</li>
          </ul>
        </div>
      </section>

    </div>

    <!-- Empty state -->
    <div v-else class="empty-state">
      <p>AI analysis will appear here once the page is fully loaded.</p>
      <p class="hint">
        The AI will analyze cookies, scripts, network requests, and storage to identify tracking
        technologies and assess privacy risks.
      </p>
    </div>
  </div>
</template>

<style scoped>
.analysis-content {
  max-height: 600px;
  padding: 1rem;
}

/* Loading / Error / Empty states */
.analyzing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  text-align: center;
}

.analyzing-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #3d4663;
  border-top-color: #0C67AC;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.analyzing-hint {
  color: #9ca3af;
  font-size: 0.85rem;
}

.analysis-error {
  padding: 2rem;
  text-align: center;
  color: #f87171;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #9ca3af;
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 0.5rem;
}

/* ── Structured report ──────────────────────────────── */

.structured-report {
  color: #e0e7ff;
  line-height: 1.6;
}

/* ── Summary: Score & Findings ──────────────────────── */

.privacy-score-banner {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
  border-radius: 8px;
  background: #2a2f45;
}

.score-heading {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.score-summary {
  font-size: 1rem;
  color: #c5ccdf;
  margin: 0;
  line-height: 1.5;
}

.privacy-score-banner .score-exclamation,
.privacy-score-banner .score-value,
.privacy-score-banner .score-label {
  font-size: 1.25rem;
  font-weight: 700;
}

.privacy-score-banner.score-critical {
  background: linear-gradient(135deg, #450a0a, #7f1d1d);
  border: 1px solid #ef4444;
}

.privacy-score-banner.score-critical .score-exclamation,
.privacy-score-banner.score-critical .score-value,
.privacy-score-banner.score-critical .score-label {
  color: #fca5a5;
}

.privacy-score-banner.score-high {
  background: linear-gradient(135deg, #431407, #7c2d12);
  border: 1px solid #f97316;
}

.privacy-score-banner.score-high .score-exclamation,
.privacy-score-banner.score-high .score-value,
.privacy-score-banner.score-high .score-label {
  color: #fdba74;
}

.privacy-score-banner.score-moderate {
  background: linear-gradient(135deg, #422006, #78350f);
  border: 1px solid #eab308;
}

.privacy-score-banner.score-moderate .score-exclamation,
.privacy-score-banner.score-moderate .score-value,
.privacy-score-banner.score-moderate .score-label {
  color: #fde047;
}

.privacy-score-banner.score-low {
  background: linear-gradient(135deg, #052e16, #14532d);
  border: 1px solid #22c55e;
}

.privacy-score-banner.score-low .score-exclamation,
.privacy-score-banner.score-low .score-value,
.privacy-score-banner.score-low .score-label {
  color: #86efac;
}

.privacy-score-banner.score-safe {
  background: linear-gradient(135deg, #042f2e, #115e59);
  border: 1px solid #10b981;
}

.privacy-score-banner.score-safe .score-exclamation,
.privacy-score-banner.score-safe .score-value,
.privacy-score-banner.score-safe .score-label {
  color: #6ee7b7;
}

/* Section container */
.report-section {
  margin-bottom: 1rem;
  padding: 1.25rem;
  background: #1e2235;
  border-radius: 8px;
  border: 1px solid #2d3350;
}

.report-section h2 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.15rem;
  color: #f0f4ff;
  margin: 0 0 1rem 0;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #0C67AC;
}

.section-icon {
  font-size: 1.2rem;
}

.report-section h3 {
  font-size: 0.95rem;
  color: #7CB8E4;
  margin: 1rem 0 0.5rem 0;
}

.section-summary {
  color: #c5ccdf;
  margin: 0.25rem 0 0.75rem 0;
  font-size: 0.95rem;
}

/* ── Badges ─────────────────────────────────────────── */

.badge, .risk-badge {
  display: inline-block;
  padding: 0.15rem 0.6rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-left: auto;
}

.count-badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: 12px;
  font-size: 0.72rem;
  font-weight: 600;
  background: #2a3555;
  color: #7CB8E4;
  margin-left: auto;
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

/* ── Risk factors ───────────────────────────────────── */

.factor-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.factor-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid #2d3350;
  font-size: 0.95rem;
}

.factor-item:last-child {
  border-bottom: none;
}

.severity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-right: 0.15rem;
}

.severity-dot.badge-critical { background: #ef4444; }
.severity-dot.badge-high { background: #f97316; }
.severity-dot.badge-medium { background: #eab308; }
.severity-dot.badge-low { background: #22c55e; }
.severity-dot.badge-none { background: #64748b; }

.factor-text {
  flex: 1;
  margin-right: 0.25rem;
}

/* ── Tracker cards ──────────────────────────────────── */

.tracker-category {
  margin-top: 0.75rem;
}

.tracker-card {
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

.tracker-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.tracker-header strong {
  color: #f0f4ff;
  font-size: 0.95rem;
}

.tracker-domains {
  color: #7c8ab8;
  font-size: 0.85rem;
  font-family: monospace;
}

.tracker-purpose {
  color: #b0bcd5;
  font-size: 0.95rem;
  margin: 0.3rem 0 0 0;
}

.tracker-details {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.4rem;
}

.detail-tag {
  font-size: 0.82rem;
  color: #9ca3af;
}

/* ── Data collection cards ──────────────────────────── */

.data-card {
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

.data-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.data-card-header strong {
  color: #f0f4ff;
  font-size: 0.95rem;
}

.data-details {
  margin: 0.4rem 0 0 1.25rem;
  padding: 0;
  font-size: 0.95rem;
  color: #b0bcd5;
}

.data-details li {
  margin: 0.2rem 0;
}

/* Sensitive data card highlight */
.data-card-sensitive {
  border-color: #ef4444;
  background: #251a1f;
}

.badge-sensitive {
  background: #450a0a;
  color: #fca5a5;
  border: 1px solid #ef4444;
}

/* Shared-with chips */
.shared-with {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.5rem;
  padding-top: 0.4rem;
  border-top: 1px solid #2d3350;
}

.shared-label {
  font-size: 0.85rem;
  color: #7c8ab8;
  font-weight: 600;
  margin-right: 0.15rem;
}

.shared-chip {
  background: #2a2040;
  color: #c4b5fd;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.82rem;
  border: 1px solid #4c3a7a;
}

/* ── Third-party groups ──────────────────────────────── */

.third-party-group {
  margin-bottom: 0.75rem;
}

.services-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.35rem 0;
}

.service-chip {
  background: #2a3555;
  color: #c5ccdf;
  padding: 0.2rem 0.55rem;
  border-radius: 4px;
  font-size: 0.85rem;
}

.impact-text {
  color: #9ca3af;
  font-size: 0.88rem;
  margin: 0.3rem 0 0 0;
  font-style: italic;
}

/* ── Cookie groups ───────────────────────────────────── */

.cookie-group {
  margin-bottom: 0.75rem;
}

.cookie-group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.cookie-group-header h3 {
  margin: 0;
}

.lifespan-tag {
  font-size: 0.82rem;
  color: #9ca3af;
}

.cookie-names {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.4rem;
}

.cookie-names code {
  background: #2a2f45;
  color: #7CB8E4;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.85rem;
  font-family: monospace;
}

.concerning-section {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid #2d3350;
}

.concerning-section ul {
  margin: 0.25rem 0 0 1.25rem;
  font-size: 0.95rem;
  color: #fdba74;
}

/* ── Storage stats ───────────────────────────────────── */

.storage-stats, .consent-stats {
  display: flex;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.stat-card {
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem 1.25rem;
  text-align: center;
  flex: 1;
}

.stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: 700;
  color: #7CB8E4;
}

.stat-label {
  font-size: 0.85rem;
  color: #9ca3af;
}

.storage-concerns {
  margin-top: 0.5rem;
}

.storage-concerns ul {
  margin: 0.25rem 0 0 1.25rem;
  font-size: 0.95rem;
  color: #b0bcd5;
}

/* ── Consent discrepancies ───────────────────────────── */

.discrepancies {
  margin-top: 0.75rem;
}

.discrepancy-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

.discrepancy-detail {
  flex: 1;
}

.discrepancy-row {
  font-size: 0.95rem;
  margin: 0.15rem 0;
}

.discrepancy-label {
  font-weight: 600;
  color: #7c8ab8;
  margin-right: 0.35rem;
}

/* ── Vendor grid ─────────────────────────────────────── */

.vendor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.5rem;
}

.vendor-card {
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem;
}

.vendor-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.vendor-header strong {
  color: #f0f4ff;
  font-size: 0.95rem;
}

.vendor-role {
  font-size: 0.82rem;
  color: #7CB8E4;
  background: #2a3555;
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
}

.vendor-impact {
  color: #b0bcd5;
  font-size: 0.88rem;
  margin: 0.35rem 0 0 0;
}

/* ── Recommendations ─────────────────────────────────── */

.recommendations-section h3 {
  margin-top: 0.75rem;
}

.recommendation-group ul {
  margin: 0.25rem 0 0.5rem 1.25rem;
  font-size: 0.95rem;
  color: #c5ccdf;
}

.recommendation-group li {
  margin: 0.3rem 0;
}
</style>
