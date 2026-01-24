<script setup lang="ts">
import type { TrackedCookie } from '../../types'
import { formatExpiry, truncateValue } from '../../utils'

/**
 * Tab panel displaying cookies grouped by domain.
 */
defineProps<{
  /** Cookies grouped by domain */
  cookiesByDomain: Record<string, TrackedCookie[]>
  /** Total number of cookies */
  cookieCount: number
}>()
</script>

<template>
  <div class="tab-content">
    <div v-if="cookieCount === 0" class="empty-state">No cookies detected yet</div>
    <div v-else class="domain-groups">
      <div v-for="(domainCookies, domain) in cookiesByDomain" :key="domain" class="domain-group">
        <h3 class="domain-header">{{ domain }} ({{ domainCookies.length }})</h3>
        <div
          v-for="cookie in domainCookies"
          :key="`${cookie.domain}-${cookie.name}`"
          class="cookie-item"
        >
          <div class="cookie-name">{{ cookie.name }}</div>
          <div class="cookie-details">
            <span class="cookie-value" :title="cookie.value">{{ truncateValue(cookie.value) }}</span>
            <div class="cookie-meta">
              <span v-if="cookie.httpOnly" class="badge">HttpOnly</span>
              <span v-if="cookie.secure" class="badge">Secure</span>
              <span class="badge">{{ cookie.sameSite }}</span>
              <span class="expiry">Expires: {{ formatExpiry(cookie.expires) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cookie-item {
  padding: 0.5rem;
  border-bottom: 1px solid #3d4663;
  font-size: 0.85rem;
}

.cookie-item:last-child {
  border-bottom: none;
}

.cookie-name {
  font-weight: 600;
  color: #e0e7ff;
}

.cookie-value {
  color: #9ca3af;
  word-break: break-all;
}

.cookie-meta {
  margin-top: 0.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.expiry {
  font-size: 0.75rem;
  color: #9ca3af;
}
</style>
