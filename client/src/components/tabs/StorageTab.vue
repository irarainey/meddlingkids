<script setup lang="ts">
import type { StorageItem } from '../../types'
import { truncateValue } from '../../utils'

/**
 * Tab panel displaying localStorage and sessionStorage items.
 */
defineProps<{
  /** localStorage items */
  localStorage: StorageItem[]
  /** sessionStorage items */
  sessionStorage: StorageItem[]
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="localStorage.length === 0 && sessionStorage.length === 0" class="empty-state">
      No storage data detected yet
    </div>
    <div v-else class="domain-groups">
      <div v-if="localStorage.length > 0" class="domain-group">
        <h3 class="domain-header">📦 Local Storage ({{ localStorage.length }})</h3>
        <div v-for="item in localStorage" :key="item.key" class="storage-item">
          <div class="storage-key">{{ item.key }}</div>
          <div class="storage-value" :title="item.value">{{ truncateValue(item.value, 100) }}</div>
        </div>
      </div>
      <div v-if="sessionStorage.length > 0" class="domain-group">
        <h3 class="domain-header">⏱️ Session Storage ({{ sessionStorage.length }})</h3>
        <div v-for="item in sessionStorage" :key="item.key" class="storage-item">
          <div class="storage-key">{{ item.key }}</div>
          <div class="storage-value" :title="item.value">{{ truncateValue(item.value, 100) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.storage-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
  font-size: 0.85rem;
}

.storage-item:last-child {
  border-bottom: none;
}

.storage-key {
  font-weight: 600;
  color: #e0e7ff;
}

.storage-value {
  color: #9ca3af;
  word-break: break-all;
  font-family: monospace;
  font-size: 0.8rem;
  background: #2a2f45;
  padding: 0.25rem;
  border-radius: 4px;
  margin-top: 0.25rem;
}
</style>
