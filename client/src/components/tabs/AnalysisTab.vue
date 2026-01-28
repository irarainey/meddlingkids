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
}>()
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
</style>
