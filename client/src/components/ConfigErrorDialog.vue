<script setup lang="ts">
/**
 * Dialog showing configuration errors (e.g., missing OpenAI API keys)
 */
defineProps<{
  /** Whether the dialog is visible */
  isOpen: boolean
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
        
        <div class="error-icon config-error">
          <span>⚙️</span>
        </div>
        
        <h2 class="error-title">Configuration Error</h2>
        
        <p class="error-message">{{ message }}</p>
        
        <div class="error-explanation">
          <p>The server is not properly configured to run analysis.</p>
          <p>Please ensure one of the following is configured:</p>
          
          <div class="config-section">
            <h4>Azure OpenAI</h4>
            <ul>
              <li><code>AZURE_OPENAI_ENDPOINT</code></li>
              <li><code>AZURE_OPENAI_API_KEY</code></li>
              <li><code>AZURE_OPENAI_DEPLOYMENT</code></li>
            </ul>
          </div>
          
          <div class="config-section">
            <h4>Standard OpenAI</h4>
            <ul>
              <li><code>OPENAI_API_KEY</code></li>
              <li><code>OPENAI_MODEL</code> (optional)</li>
              <li><code>OPENAI_BASE_URL</code> (optional)</li>
            </ul>
          </div>
          
          <p class="tip">💡 <strong>Tip:</strong> Check your <code>.env</code> file or environment variables and restart the server.</p>
        </div>
        
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

.error-icon.config-error {
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
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
  font-family: monospace;
  font-size: 0.85rem;
  white-space: pre-wrap;
  margin-bottom: 1.5rem;
  border-left: 4px solid var(--color-warning, #f0ad4e);
}

.error-explanation {
  color: var(--color-text);
  line-height: 1.6;
}

.error-explanation p {
  margin: 0.5rem 0;
}

.config-section {
  background: var(--color-background-soft);
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin: 1rem 0;
}

.config-section h4 {
  margin: 0 0 0.5rem;
  color: var(--color-heading);
  font-size: 0.9rem;
}

.config-section ul {
  margin: 0;
  padding-left: 1.5rem;
}

.config-section li {
  margin: 0.25rem 0;
}

.config-section code {
  background: var(--color-background-mute);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.85rem;
}

.tip {
  margin-top: 1rem;
  padding: 0.75rem;
  background: var(--color-background-soft);
  border-radius: 8px;
  font-size: 0.9rem;
}

.tip code {
  background: var(--color-background-mute);
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.dialog-button {
  display: block;
  width: 100%;
  margin-top: 1.5rem;
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
