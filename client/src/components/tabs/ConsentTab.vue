<script setup lang="ts">
import type { ConsentDetails } from '../../types'

/**
 * Tab panel displaying consent dialog details.
 */
defineProps<{
  /** Consent details extracted from the page */
  consentDetails: ConsentDetails | null
}>()

/**
 * Check if consent details have any content.
 */
function hasContent(details: ConsentDetails | null): boolean {
  if (!details) return false
  return details.partners.length > 0 || details.categories.length > 0
}
</script>

<template>
  <div class="tab-content consent-content">
    <div v-if="!hasContent(consentDetails)" class="empty-state">
      <p>No consent dialog details extracted yet.</p>
      <p class="hint">This information is extracted from the cookie consent dialog before accepting.</p>
    </div>
    <div v-else class="consent-details">
      <div v-if="consentDetails!.categories.length > 0" class="consent-section">
        <h3 class="consent-section-header">
          📂 Cookie Categories ({{ consentDetails!.categories.length }})
        </h3>
        <div
          v-for="category in consentDetails!.categories"
          :key="category.name"
          class="consent-category"
        >
          <div class="category-header">
            <span class="category-name">{{ category.name }}</span>
            <span :class="['category-badge', category.required ? 'required' : 'optional']">
              {{ category.required ? 'Required' : 'Optional' }}
            </span>
          </div>
          <p class="category-description">{{ category.description }}</p>
        </div>
      </div>

      <div v-if="consentDetails!.purposes.length > 0" class="consent-section">
        <h3 class="consent-section-header">
          🎯 Stated Purposes ({{ consentDetails!.purposes.length }})
        </h3>
        <ul class="purposes-list">
          <li v-for="purpose in consentDetails!.purposes" :key="purpose">{{ purpose }}</li>
        </ul>
      </div>

      <div v-if="consentDetails!.partners.length > 0" class="consent-section">
        <h3 class="consent-section-header">
          🤝 Partners & Vendors ({{ consentDetails!.partners.length }})
        </h3>
        <p class="section-hint">
          These are the third parties that will receive your data when you click "Accept All"
        </p>
        <div class="partners-grid">
          <div
            v-for="partner in consentDetails!.partners"
            :key="partner.name"
            class="partner-card"
          >
            <div class="partner-name">{{ partner.name }}</div>
            <div class="partner-purpose">{{ partner.purpose }}</div>
            <div
              v-if="partner.dataCollected && partner.dataCollected.length > 0"
              class="partner-data"
            >
              <span class="data-label">Data collected:</span>
              <span class="data-types">{{ partner.dataCollected.join(', ') }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="consentDetails!.expanded" class="expanded-notice">
        ✅ Expanded consent preferences to gather more details
      </div>
    </div>
  </div>
</template>

<style scoped>
.consent-content {
  padding: 1rem;
  max-height: 600px;
  overflow-y: auto;
}

.consent-details {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.consent-section {
  background: #2a2f45;
  border-radius: 8px;
  padding: 1rem;
}

.consent-section-header {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: #e0e7ff;
  border-bottom: 1px solid #3d4663;
  padding-bottom: 0.5rem;
}

.section-hint {
  font-size: 0.85rem;
  color: #9ca3af;
  margin: -0.5rem 0 1rem;
}

.consent-category {
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 6px;
  padding: 0.75rem;
  margin-bottom: 0.5rem;
}

.category-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.category-name {
  font-weight: 600;
  color: #e0e7ff;
}

.category-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
  font-weight: 500;
}

.category-badge.required {
  background: #78350f;
  color: #fef3c7;
}

.category-badge.optional {
  background: #1e3a5f;
  color: #93c5fd;
}

.category-description {
  margin: 0;
  font-size: 0.85rem;
  color: #9ca3af;
}

.purposes-list {
  margin: 0;
  padding-left: 1.5rem;
}

.purposes-list li {
  margin-bottom: 0.25rem;
  font-size: 0.9rem;
  color: #c7d2fe;
}

.partners-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
}

.partner-card {
  background: #1e2235;
  border: 1px solid #3d4663;
  border-radius: 6px;
  padding: 0.75rem;
}

.partner-name {
  font-weight: 600;
  color: #e0e7ff;
  margin-bottom: 0.25rem;
}

.partner-purpose {
  font-size: 0.85rem;
  color: #9ca3af;
  margin-bottom: 0.5rem;
}

.partner-data {
  font-size: 0.75rem;
  background: #2a2f45;
  padding: 0.5rem;
  border-radius: 4px;
}

.data-label {
  color: #9ca3af;
}

.data-types {
  color: #f87171;
}

.expanded-notice {
  background: #064e3b;
  color: #a7f3d0;
  padding: 0.75rem;
  border-radius: 6px;
  font-size: 0.85rem;
  text-align: center;
}
</style>
