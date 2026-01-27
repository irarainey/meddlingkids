<script setup lang="ts">
/**
 * Generic error dialog for displaying error messages
 */
defineProps<{
  /** Whether the dialog is visible */
  isOpen: boolean
  /** Error title */
  title?: string
  /** Error message */
  message: string
}>()

const emit = defineEmits<{
  /** Emitted when the dialog should close */
  close: []
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="dialog-overlay" @click.self="emit('close')">
      <div class="dialog-content">
        <button class="dialog-close" @click="emit('close')">&times;</button>
        
        <div class="error-icon">
          <span>⚠️</span>
        </div>
        
        <h2 class="error-title">{{ title || 'Error' }}</h2>
        
        <p class="error-message">{{ message }}</p>
        
        <button class="dialog-button" @click="emit('close')">Close</button>
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
  max-width: 500px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
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

.error-icon {
  font-size: 3rem;
  text-align: center;
  margin-bottom: 1rem;
}

.error-title {
  text-align: center;
  margin: 0 0 1.5rem;
  color: #e0e7ff;
  font-size: 1.5rem;
  font-weight: 600;
}

.error-message {
  background: #2a2f45;
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.95rem;
  white-space: pre-wrap;
  margin-bottom: 1.5rem;
  border-left: 4px solid #ef4444;
  line-height: 1.6;
  color: #c7d2fe;
  text-align: left;
}

.dialog-button {
  display: block;
  width: 100%;
  padding: 0.75rem 1.5rem;
  background: #0C67AC;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.dialog-button:hover {
  background: #0A5690;
  transform: translateY(-2px);
}
</style>
