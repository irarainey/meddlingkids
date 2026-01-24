<script setup lang="ts">
import { formatMarkdown } from '../../utils'

/**
 * Tab panel displaying high-risk privacy concerns.
 */
defineProps<{
  /** High risks summary from AI analysis */
  highRisks: string
}>()
</script>

<template>
  <div class="tab-content risks-content">
    <div v-if="highRisks" class="risks-result" v-html="formatMarkdown(highRisks)"></div>
    <div v-else class="empty-state">
      <p>High risks summary will appear here once analysis is complete.</p>
    </div>
  </div>
</template>

<style scoped>
.risks-content {
  max-height: 600px;
  padding: 1.5rem;
  background: linear-gradient(135deg, #2a1f1f, #1e2235);
}

.risks-result {
  font-size: 1.05rem;
  line-height: 1.8;
  color: #e0e7ff;
}

.risks-result :deep(ul) {
  list-style: none;
  padding: 0;
  margin: 0;
}

.risks-result :deep(li) {
  padding: 0.75rem 1rem;
  margin: 0.5rem 0;
  background: #2a2f45;
  border-radius: 8px;
  border-left: 4px solid #ef4444;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  color: #fecaca;
}
</style>
