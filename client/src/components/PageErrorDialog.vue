<script setup lang="ts">
/**
 * Dialog showing page load errors (access denied, server errors, etc.)
 */
defineProps<{
  /** Whether the dialog is visible */
  isOpen: boolean
  /** Error type */
  errorType: 'access-denied' | 'server-error' | null
  /** Error message */
  message: string
  /** HTTP status code if available */
  statusCode: number | null
}>()

const emit = defineEmits<{
  /** Emitted when the dialog should close */
  close: []
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" class="dialog-overlay" role="dialog" aria-modal="true" aria-labelledby="page-error-title" @click.self="emit('close')" @keydown.escape="emit('close')">
      <div class="dialog-content">
        <button class="dialog-close" aria-label="Close dialog" @click="emit('close')">&times;</button>
        
        <div class="error-icon" :class="errorType">
          <span v-if="errorType === 'access-denied'">🚫</span>
          <span v-else>⚠️</span>
        </div>
        
        <h2 id="page-error-title" class="error-title">
          {{ errorType === 'access-denied' ? 'Access Denied' : 'Page Load Error' }}
        </h2>
        
        <p class="error-message">{{ message }}</p>
        
        <div v-if="statusCode" class="status-code">
          HTTP Status: {{ statusCode }}
        </div>
        
        <div class="error-explanation">
          <template v-if="errorType === 'access-denied'">
            <p>This website has <strong>bot protection</strong> that detected our automated browser.</p>
            <p>Common causes:</p>
            <ul>
              <li>Cloudflare or similar security services</li>
              <li>Rate limiting or IP blocking</li>
              <li>CAPTCHA requirements</li>
              <li>Geo-restrictions</li>
            </ul>
            <p class="tip">💡 <strong>Tip:</strong> Try a different device type from the dropdown, or try again later.</p>
          </template>
          <template v-else>
            <p>The server returned an error when trying to load this page.</p>
            <p>This could be due to:</p>
            <ul>
              <li>The page doesn't exist (404)</li>
              <li>Server is temporarily unavailable</li>
              <li>Network connectivity issues</li>
            </ul>
          </template>
        </div>
        
        <button class="close-btn" @click="emit('close')">
          Close
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
  max-width: 500px;
  width: 100%;
  position: relative;
  text-align: center;
}

.dialog-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: none;
  border: none;
  color: #9ca3af;
  font-size: 1.5rem;
  cursor: pointer;
  line-height: 1;
  padding: 0.25rem;
}

.dialog-close:hover {
  color: #e0e7ff;
}

.error-icon {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
}

.error-icon.access-denied {
  animation: shake 0.5s ease-in-out;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-5px); }
  75% { transform: translateX(5px); }
}

.error-title {
  color: #f87171;
  font-size: 1.25rem;
  margin: 0 0 0.75rem 0;
}

.error-message {
  color: #e0e7ff;
  font-size: 1rem;
  margin-bottom: 0.5rem;
}

.status-code {
  color: #9ca3af;
  font-size: 0.875rem;
  margin-bottom: 1.5rem;
  font-family: monospace;
  background: #2a2f45;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  display: inline-block;
}

.error-explanation {
  text-align: left;
  color: #c4c9de;
  font-size: 0.9rem;
  margin: 1.5rem 0;
  padding: 1rem;
  background: #2a2f45;
  border-radius: 8px;
}

.error-explanation p {
  margin: 0.5rem 0;
}

.error-explanation ul {
  margin: 0.5rem 0 0.5rem 1.5rem;
  padding: 0;
}

.error-explanation li {
  margin: 0.25rem 0;
}

.error-explanation .tip {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid #3d4663;
  color: #7CB8E4;
}

.close-btn {
  padding: 0.75rem 2rem;
  font-size: 1rem;
  font-weight: 600;
  color: white;
  background-color: #0c67ac;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.close-btn:hover {
  background-color: #21436e;
}
</style>
