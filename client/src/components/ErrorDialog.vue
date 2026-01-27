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
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.dialog-content {
  background: var(--color-background);
  border-radius: 12px;
  padding: 2rem;
  max-width: 500px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  position: relative;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.dialog-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--color-text);
  opacity: 0.6;
  transition: opacity 0.2s;
}

.dialog-close:hover {
  opacity: 1;
}

.error-icon {
  font-size: 3rem;
  text-align: center;
  margin-bottom: 1rem;
}

.error-title {
  text-align: center;
  margin: 0 0 1rem;
  color: var(--color-heading);
}

.error-message {
  background: var(--color-background-soft);
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.95rem;
  white-space: pre-wrap;
  margin-bottom: 1.5rem;
  border-left: 4px solid var(--color-error, #dc3545);
  line-height: 1.5;
}

.dialog-button {
  display: block;
  width: 100%;
  padding: 0.75rem 1.5rem;
  background: var(--color-primary, #646cff);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.dialog-button:hover {
  background: var(--color-primary-hover, #535bf2);
}
</style>
