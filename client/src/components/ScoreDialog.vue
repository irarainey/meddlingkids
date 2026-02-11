<script setup lang="ts">
import { getExclamation, getRiskLevel, getScoreClass } from '../utils'

/**
 * Score dialog showing privacy risk assessment with themed exclamation.
 */
defineProps<{
  /** Whether the dialog is visible */
  isOpen: boolean
  /** Privacy risk score (0-100) */
  score: number
  /** One-sentence summary of findings */
  summary: string
}>()

const emit = defineEmits<{
  /** Emitted when the dialog should close */
  close: []
  /** Emitted when the user clicks "View Full Report" */
  viewReport: []
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="dialog-overlay" role="dialog" aria-modal="true" aria-labelledby="score-dialog-title" @click.self="emit('close')" @keydown.escape="emit('close')">
      <div class="dialog-content">
        <button class="dialog-close" aria-label="Close dialog" @click="emit('close')">&times;</button>
        
        <div id="score-dialog-title" class="exclamation" :class="getScoreClass(score)">
          {{ getExclamation(score) }}
        </div>
        
        <div class="score-container">
          <div class="score-ring" :class="getScoreClass(score)">
            <span class="score-value">{{ score }}</span>
          </div>
          <div class="risk-level" :class="getScoreClass(score)">
            {{ getRiskLevel(score) }}
          </div>
        </div>
        
        <p class="summary">{{ summary }}</p>
        
        <button class="view-details-btn" @click="emit('viewReport')">
          View Full Report
        </button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 2rem;
}

.dialog-content {
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 16px;
  padding: 2rem;
  max-width: 400px;
  width: 100%;
  text-align: center;
  position: relative;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.dialog-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 32px;
  height: 32px;
  border: none;
  background: #2a2f45;
  color: #9ca3af;
  font-size: 1.25rem;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.dialog-close:hover {
  background: #3d4663;
  color: #e0e7ff;
}

.exclamation {
  font-size: 2.5rem;
  font-weight: 800;
  margin-bottom: 1.5rem;
  text-transform: uppercase;
  letter-spacing: 2px;
}

.exclamation.score-critical {
  color: #ef4444;
  text-shadow: 0 0 20px rgba(239, 68, 68, 0.5);
}

.exclamation.score-high {
  color: #f97316;
  text-shadow: 0 0 20px rgba(249, 115, 22, 0.5);
}

.exclamation.score-moderate {
  color: #eab308;
  text-shadow: 0 0 20px rgba(234, 179, 8, 0.5);
}

.exclamation.score-low {
  color: #22c55e;
  text-shadow: 0 0 20px rgba(34, 197, 94, 0.5);
}

.exclamation.score-safe {
  color: #10b981;
  text-shadow: 0 0 20px rgba(16, 185, 129, 0.5);
}

.score-container {
  margin-bottom: 1.5rem;
}

.score-ring {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  border: 6px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1rem;
  transition: all 0.3s;
}

.score-ring.score-critical {
  border-color: #ef4444;
  box-shadow: 0 0 30px rgba(239, 68, 68, 0.4);
}

.score-ring.score-high {
  border-color: #f97316;
  box-shadow: 0 0 30px rgba(249, 115, 22, 0.4);
}

.score-ring.score-moderate {
  border-color: #eab308;
  box-shadow: 0 0 30px rgba(234, 179, 8, 0.4);
}

.score-ring.score-low {
  border-color: #22c55e;
  box-shadow: 0 0 30px rgba(34, 197, 94, 0.4);
}

.score-ring.score-safe {
  border-color: #10b981;
  box-shadow: 0 0 30px rgba(16, 185, 129, 0.4);
}

.score-value {
  font-size: 2.5rem;
  font-weight: 700;
  color: #e0e7ff;
}

.risk-level {
  font-size: 1.1rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.risk-level.score-critical {
  color: #fca5a5;
}

.risk-level.score-high {
  color: #fdba74;
}

.risk-level.score-moderate {
  color: #fde047;
}

.risk-level.score-low {
  color: #86efac;
}

.risk-level.score-safe {
  color: #6ee7b7;
}

.summary {
  color: #c7d2fe;
  font-size: 1rem;
  line-height: 1.6;
  margin-bottom: 1.5rem;
  padding: 0 1rem;
}

.view-details-btn {
  background: #0C67AC;
  color: white;
  border: none;
  padding: 0.75rem 2rem;
  font-size: 1rem;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.view-details-btn:hover {
  background: #0A5690;
  transform: translateY(-2px);
}
</style>
