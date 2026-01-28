<script setup lang="ts">
import type { ScreenshotModal } from '../types'

/**
 * Screenshot gallery with thumbnails and fullscreen modal.
 */
defineProps<{
  /** Array of base64 screenshot data URLs */
  screenshots: string[]
  /** Currently selected screenshot for modal display */
  selectedScreenshot: ScreenshotModal | null
}>()

const emit = defineEmits<{
  /** Emitted when a thumbnail is clicked */
  openModal: [src: string, index: number]
  /** Emitted when the modal should close */
  closeModal: []
}>()

/**
 * Get label for screenshot by index.
 */
function getLabel(index: number): string {
  return String(index + 1)
}
</script>

<template>
  <!-- Screenshot thumbnails row -->
  <div v-if="screenshots.length > 0" class="screenshots-row">
    <div
      v-for="(shot, index) in screenshots"
      :key="index"
      class="screenshot-thumb"
      @click="emit('openModal', shot, index)"
    >
      <img :src="shot" :alt="'Stage ' + (index + 1)" />
      <span class="screenshot-label">{{ getLabel(index) }}</span>
    </div>
  </div>

  <!-- Screenshot Modal Overlay -->
  <Teleport to="body">
    <div v-if="selectedScreenshot" class="modal-overlay" @click.self="emit('closeModal')">
      <div class="modal-content">
        <button class="modal-close" @click="emit('closeModal')">&times;</button>
        <h3 class="modal-title">{{ selectedScreenshot.label }}</h3>
        <div class="modal-image-container">
          <img :src="selectedScreenshot.src" :alt="selectedScreenshot.label" class="modal-image" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.screenshots-row {
  display: flex;
  gap: 1rem;
  margin: 0 0 2rem 0;
  padding: 1rem;
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 12px;
  overflow-x: auto;
  /* Use auto margins on children for centering instead of justify-content */
  /* This allows proper scrolling when content overflows */
}

.screenshots-row::before,
.screenshots-row::after {
  content: '';
  margin: auto;
}

.screenshot-thumb {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.screenshot-thumb img {
  width: 300px;
  height: auto;
  border: 2px solid #3d4663;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  transition:
    transform 0.2s,
    border-color 0.2s;
}

.screenshot-thumb img:hover {
  transform: scale(1.05);
  border-color: #42b883;
}

.screenshot-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #7CB8E4;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Modal Styles */
.modal-overlay {
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

.modal-content {
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 12px;
  max-width: 95vw;
  max-height: 95vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 40px;
  height: 40px;
  border: none;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  font-size: 1.5rem;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  z-index: 1001;
}

.modal-close:hover {
  background: rgba(0, 0, 0, 0.9);
}

.modal-title {
  margin: 0;
  padding: 1rem 1.5rem;
  font-size: 1.1rem;
  border-bottom: 1px solid #3d4663;
  background: #2a2f45;
  color: #e0e7ff;
}

.modal-image-container {
  overflow: auto;
  max-height: calc(95vh - 60px);
}

.modal-image {
  display: block;
  max-width: 100%;
  height: auto;
}
</style>
