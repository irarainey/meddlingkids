<script setup lang="ts">
/**
 * Tab panel displaying the server debug log from the analysis run.
 */
defineProps<{
  /** Log lines collected during analysis */
  logLines: string[]
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="logLines.length === 0" class="empty-state">
      No debug log available
    </div>
    <pre v-else class="debug-log">{{ logLines.join('\n') }}</pre>
  </div>
</template>

<style scoped>
.debug-log {
  background: #0d0f1a;
  color: #c8d0e0;
  font-family: 'Fira Code', 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 0.78rem;
  line-height: 1.55;
  padding: 1rem;
  border-radius: 6px;
  overflow-x: auto;
  white-space: pre;
  margin: 0;
  max-height: 80vh;
  overflow-y: auto;
}
</style>
