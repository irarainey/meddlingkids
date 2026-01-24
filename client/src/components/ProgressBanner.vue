<script setup lang="ts">
/**
 * Progress banner component displaying analysis status with Mystery Machine animation.
 */
import mysteryMachine from '../assets/mystery_machine.png'

defineProps<{
  /** Current status message to display */
  statusMessage: string
  /** Progress percentage (0-100) */
  progressPercent: number
}>()
</script>

<template>
  <div class="progress-banner">
    <div class="progress-track">
      <div class="track-line"></div>
      <div 
        class="mystery-machine-container" 
          :style="{ left: `calc(${progressPercent}% - ${progressPercent}px)` }"      >
        <img 
          :src="mysteryMachine" 
          alt="Mystery Machine" 
          class="mystery-machine"
        />
      </div>
    </div>
    <div class="status-text">{{ statusMessage || 'Investigating...' }}</div>
  </div>
</template>

<style scoped>
.progress-banner {
  background: linear-gradient(135deg, #1a1a2e, #16213e);
  border: 2px solid #0C67AC;
  border-radius: 16px;
  padding: 1.5rem 2rem;
  margin: 1.5rem 0;
  box-shadow: 0 4px 20px rgba(12, 103, 172, 0.3);
}

.progress-track {
  position: relative;
  height: 60px;
  margin-bottom: 1rem;
}

.track-line {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #0C67AC, #3B8FD4, #0C67AC);
  border-radius: 2px;
  transform: translateY(-50%);
}

.track-line::before {
  content: '';
  position: absolute;
  top: -3px;
  left: 0;
  right: 0;
  height: 10px;
  background: repeating-linear-gradient(
    90deg,
    transparent,
    transparent 20px,
    rgba(255, 255, 255, 0.1) 20px,
    rgba(255, 255, 255, 0.1) 22px
  );
}

.mystery-machine-container {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  transition: left 0.5s ease-out;
  z-index: 1;
}

.mystery-machine {
  width: 100px;
  height: auto;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.4));
  animation: bounce 0.5s ease-in-out infinite;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-4px);
  }
}

.status-text {
  text-align: center;
  font-size: 1.1rem;
  font-weight: 600;
  color: #e0e7ff;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
  letter-spacing: 0.5px;
}
</style>