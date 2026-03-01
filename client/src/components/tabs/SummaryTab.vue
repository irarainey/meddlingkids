<script setup lang="ts">
import type { StructuredReport, SummaryFinding, SummaryFindingType } from '../../types'
import { getExclamation, getRiskLevel, getScoreClass, stripMarkdown } from '../../utils'

/**
 * Tab panel displaying a high-level privacy summary.
 *
 * Includes the privacy score, key findings, risk assessment,
 * social media implications, tracking technologies, data
 * collection, third-party services, and recommendations.
 *
 * Cookie analysis, storage analysis, consent analysis, and
 * vendor details are displayed in their respective dedicated tabs.
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

/** Well-known social media platform URLs. */
const PLATFORM_URLS: Record<string, string> = {
  facebook: 'https://www.facebook.com',
  meta: 'https://www.facebook.com',
  instagram: 'https://www.instagram.com',
  twitter: 'https://www.twitter.com',
  'x/twitter': 'https://www.x.com',
  'x (twitter)': 'https://www.x.com',
  x: 'https://www.x.com',
  linkedin: 'https://www.linkedin.com',
  pinterest: 'https://www.pinterest.com',
  tiktok: 'https://www.tiktok.com',
  snapchat: 'https://www.snapchat.com',
  reddit: 'https://www.reddit.com',
  youtube: 'https://www.youtube.com',
  addthis: 'https://www.addthis.com',
  sharethis: 'https://www.sharethis.com',
  addtoany: 'https://www.addtoany.com',
}

/** Resolve a platform name to its website URL. */
function platformUrl(name: string): string {
  return PLATFORM_URLS[name.toLowerCase().trim()] ?? '#'
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
          Overview
        </h2>
        <ul class="factor-list">
          <li
            v-for="(finding, index) in summaryFindings"
            :key="index"
            class="factor-item"
          >
            <span class="severity-dot" :class="findingSeverityClass(finding.type)"></span>
            <span class="factor-text">{{ stripMarkdown(finding.text) }}</span>
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
          {{ stripMarkdown(structuredReport.privacyRisk.summary) }}
        </p>
        <ul v-if="structuredReport.privacyRisk.factors.length" class="factor-list">
          <li
            v-for="(factor, i) in structuredReport.privacyRisk.factors"
            :key="i"
            class="factor-item"
          >
            <span class="severity-dot" :class="severityClass(factor.severity)"></span>
            <span class="factor-text">{{ stripMarkdown(factor.description) }}</span>
            <span class="badge" :class="severityClass(factor.severity)">{{ riskLabel(factor.severity) }}</span>
          </li>
        </ul>
      </section>

      <!-- ── Section 2: Social Media Implications ────────────── -->
      <section v-if="structuredReport.socialMediaImplications.platformsDetected.length > 0" class="report-section">
        <h2>
          <span class="section-icon">📱</span>
          Social Media Implications
          <span
            class="risk-badge"
            :class="severityClass(structuredReport.socialMediaImplications.identityLinkingRisk)"
          >{{ riskLabel(structuredReport.socialMediaImplications.identityLinkingRisk) }}</span>
        </h2>
        <div class="social-platforms">
          <a
            v-for="platform in structuredReport.socialMediaImplications.platformsDetected"
            :key="platform"
            :href="platformUrl(platform)"
            target="_blank"
            rel="noopener noreferrer"
            class="platform-tag"
          >{{ platform }}</a>
        </div>
        <p v-if="structuredReport.socialMediaImplications.summary" class="section-summary">
          {{ stripMarkdown(structuredReport.socialMediaImplications.summary) }}
        </p>
        <ul v-if="structuredReport.socialMediaImplications.risks.length" class="factor-list">
          <li
            v-for="(r, i) in structuredReport.socialMediaImplications.risks"
            :key="i"
            class="factor-item"
          >
            <span class="severity-dot" :class="severityClass(r.severity)"></span>
            <span class="factor-text"><strong>{{ r.platform }}:</strong> {{ stripMarkdown(r.risk) }}</span>
            <span class="badge" :class="severityClass(r.severity)">{{ riskLabel(r.severity) }}</span>
          </li>
        </ul>
      </section>

      <!-- ── Section 4: Data Collection ──────────────────────── -->
      <section v-if="structuredReport.dataCollection.items.length > 0" class="report-section">
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
            <li v-for="(detail, j) in item.details" :key="j">{{ stripMarkdown(detail) }}</li>
          </ul>
          <div v-if="item.sharedWith.length" class="shared-with">
            <span class="shared-label">Shared with:</span>
            <template v-for="entity in item.sharedWith" :key="entity.name">
              <a v-if="entity.url" :href="entity.url" target="_blank" rel="noopener noreferrer" class="shared-chip shared-chip-link">{{ entity.name }}</a>
              <span v-else class="shared-chip">{{ entity.name }}</span>
            </template>
          </div>
        </div>
      </section>

      <!-- ── Section 5: Third-Party Services ─────────────────── -->
      <section v-if="structuredReport.thirdPartyServices.groups.length > 0" class="report-section">
        <h2>
          <span class="section-icon">🌐</span>
          Third-Party Services
          <span class="count-badge">{{ structuredReport.thirdPartyServices.totalDomains }} domains</span>
        </h2>
        <p v-if="structuredReport.thirdPartyServices.summary" class="section-summary">
          {{ stripMarkdown(structuredReport.thirdPartyServices.summary) }}
        </p>
        <div
          v-for="(group, i) in structuredReport.thirdPartyServices.groups"
          :key="i"
          class="third-party-group"
        >
          <h3>{{ group.category }}</h3>
          <div class="services-list">
            <template v-for="entity in group.services" :key="entity.name">
              <a v-if="entity.url" :href="entity.url" target="_blank" rel="noopener noreferrer" class="service-chip service-chip-link">{{ entity.name }}</a>
              <span v-else class="service-chip">{{ entity.name }}</span>
            </template>
          </div>
          <p class="impact-text">{{ stripMarkdown(group.privacyImpact) }}</p>
        </div>
      </section>

      <!-- ── Section 6: Recommendations ──────────────────────── -->
      <section v-if="structuredReport.recommendations.groups.length > 0" class="report-section recommendations-section">
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
            <li v-for="(item, j) in group.items" :key="j">{{ stripMarkdown(item) }}</li>
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
/* :deep() is required because these elements are rendered
   inside the child TrackerCategorySection component and
   scoped styles do not penetrate child boundaries. */

:deep(.tracker-category) {
  margin-top: 0.75rem;
}

:deep(.tracker-card) {
  background: #252a40;
  border: 1px solid #2d3350;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

:deep(.tracker-header) {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
}

:deep(.tracker-header strong) {
  color: #f0f4ff;
  font-size: 0.95rem;
}

:deep(.tracker-link) {
  color: #7CB8E4;
  font-size: 0.95rem;
  font-weight: 600;
  text-decoration: none;
}

:deep(.tracker-link:hover) {
  text-decoration: underline;
  color: #a0d0ff;
}

:deep(.tracker-domains) {
  color: #7c8ab8;
  font-size: 0.85rem;
  font-family: monospace;
}

:deep(.tracker-purpose) {
  color: #b0bcd5;
  font-size: 0.95rem;
  margin: 0.3rem 0 0 0;
}

:deep(.tracker-details) {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.4rem;
}

:deep(.detail-tag) {
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

.shared-chip-link {
  text-decoration: none;
  cursor: pointer;
}

.shared-chip-link:hover {
  background: #3a2d5a;
  text-decoration: underline;
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
  text-decoration: none;
}

.service-chip-link {
  cursor: pointer;
}

.service-chip-link:hover {
  background: #3a4565;
  text-decoration: underline;
}

.impact-text {
  color: #9ca3af;
  font-size: 0.88rem;
  margin: 0.3rem 0 0 0;
  font-style: italic;
}

/* ── Social Media Implications ────────────────────────── */

.social-platforms {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 0.75rem;
}

.platform-tag {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  font-size: 0.82rem;
  font-weight: 600;
  background: #1e3a5f;
  color: #7CB8E4;
  border: 1px solid #2a4a6f;
  text-decoration: none;
}

.platform-tag:hover {
  background: #264a73;
  color: #a0d0ff;
  text-decoration: underline;
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
