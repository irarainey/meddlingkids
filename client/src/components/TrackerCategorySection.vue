<script setup lang="ts">
import type { TrackerEntry } from '../types'
import { stripMarkdown } from '../utils'

/**
 * Reusable tracker category section (analytics, advertising, etc.).
 *
 * Renders a list of tracker cards within a category, each showing
 * the tracker name, domains, purpose, and cookie/storage counts.
 */
defineProps<{
  /** Section title including emoji prefix (e.g. "📊 Analytics & Measurement") */
  title: string
  /** Tracker entries for this category */
  trackers: TrackerEntry[]
}>()
</script>

<template>
  <div v-if="trackers.length" class="tracker-category">
    <h3>{{ title }}</h3>
    <div
      v-for="tracker in trackers"
      :key="tracker.name"
      class="tracker-card"
    >
      <div class="tracker-header">
        <a v-if="tracker.url" :href="tracker.url" target="_blank" rel="noopener noreferrer" class="tracker-link">{{ tracker.name }}</a>
        <strong v-else>{{ tracker.name }}</strong>
        <span class="tracker-domains">{{ tracker.domains.join(', ') }}</span>
      </div>
      <p class="tracker-purpose">{{ stripMarkdown(tracker.purpose) }}</p>
      <div v-if="tracker.cookies.length || tracker.storageKeys.length" class="tracker-details">
        <span v-if="tracker.cookies.length" class="detail-tag">🍪 {{ tracker.cookies.length }} cookies</span>
        <span v-if="tracker.storageKeys.length" class="detail-tag">💾 {{ tracker.storageKeys.length }} storage keys</span>
      </div>
    </div>
  </div>
</template>
