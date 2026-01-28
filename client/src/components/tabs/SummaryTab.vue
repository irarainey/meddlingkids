<script setup lang="ts">
import { formatMarkdown } from '../../utils'

/**
 * Tab panel displaying privacy summary with score and key risks.
 */
defineProps<{
  /** Summary content from AI analysis */
  summaryContent: string
  /** Privacy score (0-100) */
  privacyScore: number | null
}>()

/**
 * Get the themed exclamation based on score.
 */
function getExclamation(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'Zoinks!'
  if (s >= 60) return 'Jeepers!'
  if (s >= 40) return 'Ruh-Roh!'
  if (s >= 20) return 'Jinkies!'
  return 'Scoob-tastic!'
}

/**
 * Get the risk level label based on score.
 */
function getRiskLevel(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'Critical Risk'
  if (s >= 60) return 'High Risk'
  if (s >= 40) return 'Moderate Risk'
  if (s >= 20) return 'Low Risk'
  return 'Very Low Risk'
}

/**
 * Get the CSS class for score styling based on risk level.
 */
function getScoreClass(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'score-critical'
  if (s >= 60) return 'score-high'
  if (s >= 40) return 'score-moderate'
  if (s >= 20) return 'score-low'
  return 'score-safe'
}
</script>

<template>
  <div class="tab-content risks-content">
    <div v-if="privacyScore != null && privacyScore >= 0" class="privacy-score-banner" :class="getScoreClass(privacyScore)">
      <span class="score-exclamation">{{ getExclamation(privacyScore) }}</span>
      <span class="score-value">{{ privacyScore }}</span>
      <span class="score-label">{{ getRiskLevel(privacyScore) }}</span>
    </div>
    <div v-if="summaryContent" class="summary-result" v-html="formatMarkdown(summaryContent)"></div>
    <div v-else class="empty-state">
      <p>Summary will appear here once analysis is complete.</p>
    </div>
  </div>
</template>

<style scoped>
.risks-content {
  max-height: 600px;
  padding: 1.5rem;
}

/* Privacy Score Banner */
.privacy-score-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
  border-radius: 8px;
  background: #2a2f45;
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

.privacy-score-banner.score-critical .score-exclamation {
  color: #ef4444;
}

.privacy-score-banner.score-critical .score-value,
.privacy-score-banner.score-critical .score-label {
  color: #fca5a5;
}

.privacy-score-banner.score-high {
  background: linear-gradient(135deg, #431407, #7c2d12);
  border: 1px solid #f97316;
}

.privacy-score-banner.score-high .score-exclamation {
  color: #f97316;
}

.privacy-score-banner.score-high .score-value,
.privacy-score-banner.score-high .score-label {
  color: #fdba74;
}

.privacy-score-banner.score-moderate {
  background: linear-gradient(135deg, #422006, #78350f);
  border: 1px solid #eab308;
}

.privacy-score-banner.score-moderate .score-exclamation {
  color: #eab308;
}

.privacy-score-banner.score-moderate .score-value,
.privacy-score-banner.score-moderate .score-label {
  color: #fde047;
}

.privacy-score-banner.score-low {
  background: linear-gradient(135deg, #052e16, #14532d);
  border: 1px solid #22c55e;
}

.privacy-score-banner.score-low .score-exclamation {
  color: #22c55e;
}

.privacy-score-banner.score-low .score-value,
.privacy-score-banner.score-low .score-label {
  color: #86efac;
}

.privacy-score-banner.score-safe {
  background: linear-gradient(135deg, #042f2e, #115e59);
  border: 1px solid #10b981;
}

.privacy-score-banner.score-safe .score-exclamation {
  color: #10b981;
}

.privacy-score-banner.score-safe .score-value,
.privacy-score-banner.score-safe .score-label {
  color: #6ee7b7;
}

.summary-result {
  font-size: 1.05rem;
  line-height: 1.8;
  color: #e0e7ff;
}

.summary-result :deep(p) {
  margin: 0;
}

.summary-result :deep(ul) {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0;
}

.summary-result :deep(li) {
  padding: 0.25rem 0;
  margin: 0;
  color: #e0e7ff;
}

.summary-result :deep(br) {
  display: none;
}

.summary-result :deep(ul + br),
.summary-result :deep(br + ul) {
  display: none;
}
</style>
