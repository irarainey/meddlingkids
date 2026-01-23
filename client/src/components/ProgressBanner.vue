<script setup lang="ts">
/**
 * Progress banner component displaying analysis status and progress bar.
 */
defineProps<{
  /** Current status message to display */
  statusMessage: string
  /** Progress percentage (0-100) */
  progressPercent: number
}>()
</script>

<template>
  <div class="status-banner loading">
    <div class="status-content">
      <span class="status-icon spinning">⏳</span>
      <span class="status-text">{{ statusMessage || 'Loading...' }}</span>
    </div>
    <div class="progress-container">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <span class="progress-percent">{{ progressPercent }}%</span>
    </div>
  </div>
</template>

<style scoped>
.status-banner {
  background: linear-gradient(135deg, #d1fae5, #a7f3d0);
  border: 1px solid #10b981;
  border-radius: 12px;
  padding: 1rem 1.5rem;
  margin: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.status-banner.loading {
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border-color: #f59e0b;
}

.status-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-weight: 500;
}

.status-icon {
  font-size: 1.25rem;
}

.status-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.progress-container {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #10b981;
  border-radius: 4px;
  transition: width 0.3s ease-out;
}

.progress-percent {
  font-size: 0.85rem;
  font-weight: 600;
  min-width: 3rem;
  text-align: right;
}
</style>
