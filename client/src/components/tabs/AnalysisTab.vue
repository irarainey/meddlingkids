<script setup lang="ts">
import { formatMarkdown } from '../../utils'

/**
 * Tab panel displaying AI analysis results.
 */
defineProps<{
  /** Whether analysis is currently in progress */
  isAnalyzing: boolean
  /** Analysis error message if failed */
  analysisError: string
  /** Full AI analysis result (markdown) */
  analysisResult: string
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
  <div class="tab-content analysis-content">
    <div v-if="isAnalyzing" class="analyzing-state">
      <div class="analyzing-spinner"></div>
      <p>Analyzing tracking data with AI...</p>
      <p class="analyzing-hint">This may take a moment</p>
    </div>
    <div v-else-if="analysisError" class="analysis-error">
      <p>⚠️ {{ analysisError }}</p>
    </div>
    <div v-else-if="analysisResult" class="analysis-result">
      <div v-if="privacyScore != null && privacyScore >= 0" class="privacy-score-banner" :class="getScoreClass(privacyScore)">
        <span class="score-exclamation">{{ getExclamation(privacyScore) }}</span>
        <span class="score-value">{{ privacyScore }}</span>
        <span class="score-label">{{ getRiskLevel(privacyScore) }}</span>
      </div>
      <div v-html="formatMarkdown(analysisResult)"></div>
    </div>
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
  to {
    transform: rotate(360deg);
  }
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

.analysis-result {
  line-height: 1.6;
  color: #e0e7ff;
}

.analysis-result :deep(h2) {
  font-size: 1.3rem;
  color: #f0f4ff;
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
  border-bottom: 2px solid #0C67AC;
  padding-bottom: 0.25rem;
}

.analysis-result :deep(h3) {
  font-size: 1.1rem;
  color: #7CB8E4;
  margin-top: 1.25rem;
  margin-bottom: 0.5rem;
}

.analysis-result :deep(h4) {
  font-size: 1rem;
  color: #5BA3D9;
  margin-top: 1rem;
  margin-bottom: 0.5rem;
}

.analysis-result :deep(p) {
  margin: 0.5rem 0;
}

.analysis-result :deep(ul) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.analysis-result :deep(li) {
  margin: 0.25rem 0;
}

.analysis-result :deep(code) {
  background: #2a2f45;
  color: #7CB8E4;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-family: monospace;
  font-size: 0.9em;
}

.analysis-result :deep(pre) {
  background: #2a2f45;
  padding: 1rem;
  border-radius: 6px;
  overflow-x: auto;
}

.analysis-result :deep(strong) {
  color: #f0f4ff;
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
</style>
