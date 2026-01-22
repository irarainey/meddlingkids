<script setup lang="ts">
import { ref, computed } from 'vue'
import logo from './assets/logo.svg'

interface TrackedCookie {
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite: string
  timestamp: string
}

interface TrackedScript {
  url: string
  domain: string
  timestamp: string
}

interface StorageItem {
  key: string
  value: string
  timestamp: string
}

interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
}

interface ConsentCategory {
  name: string
  description: string
  required: boolean
}

interface ConsentPartner {
  name: string
  purpose: string
  dataCollected: string[]
}

interface ConsentDetails {
  categories: ConsentCategory[]
  partners: ConsentPartner[]
  purposes: string[]
  hasManageOptions?: boolean
  expanded?: boolean
}

const inputValue = ref('')
const currentUrl = ref('')
const isLoading = ref(false)
const isComplete = ref(false)
const errorMessage = ref('')
const screenshots = ref<string[]>([])
const cookies = ref<TrackedCookie[]>([])
const scripts = ref<TrackedScript[]>([])
const localStorage = ref<StorageItem[]>([])
const sessionStorage = ref<StorageItem[]>([])
const networkRequests = ref<NetworkRequest[]>([])
const activeTab = ref<'cookies' | 'storage' | 'network' | 'scripts' | 'analysis' | 'consent' | 'risks'>('risks')
const showOnlyThirdParty = ref(true)
const analysisResult = ref('')
const analysisError = ref('')
const highRisks = ref('')
const consentDetails = ref<ConsentDetails | null>(null)
const statusMessage = ref('')
const progressStep = ref('')
const progressPercent = ref(0)

// Screenshot modal state
const selectedScreenshot = ref<{ src: string; label: string } | null>(null)

function openScreenshotModal(src: string, index: number) {
  const labels = ['Initial', 'After Consent', 'Final']
  selectedScreenshot.value = { src, label: labels[index] || `Stage ${index + 1}` }
}

function closeScreenshotModal() {
  selectedScreenshot.value = null
}

// Group scripts by domain
const scriptsByDomain = computed(() => {
  const grouped: Record<string, TrackedScript[]> = {}
  for (const script of scripts.value) {
    if (!grouped[script.domain]) {
      grouped[script.domain] = []
    }
    grouped[script.domain].push(script)
  }
  return grouped
})

// Group cookies by domain
const cookiesByDomain = computed(() => {
  const grouped: Record<string, TrackedCookie[]> = {}
  for (const cookie of cookies.value) {
    if (!grouped[cookie.domain]) {
      grouped[cookie.domain] = []
    }
    grouped[cookie.domain].push(cookie)
  }
  return grouped
})

// Filter and group network requests
const filteredNetworkRequests = computed(() => {
  if (showOnlyThirdParty.value) {
    return networkRequests.value.filter(r => r.isThirdParty)
  }
  return networkRequests.value
})

const networkByDomain = computed(() => {
  const grouped: Record<string, NetworkRequest[]> = {}
  for (const request of filteredNetworkRequests.value) {
    if (!grouped[request.domain]) {
      grouped[request.domain] = []
    }
    grouped[request.domain].push(request)
  }
  // Sort by number of requests (most active domains first)
  return Object.fromEntries(
    Object.entries(grouped).sort((a, b) => b[1].length - a[1].length)
  )
})

const thirdPartyDomainCount = computed(() => {
  const domains = new Set(networkRequests.value.filter(r => r.isThirdParty).map(r => r.domain))
  return domains.size
})

const hasTrackingData = computed(() => {
  return cookies.value.length > 0 || 
         scripts.value.length > 0 || 
         networkRequests.value.length > 0 ||
         localStorage.value.length > 0 ||
         sessionStorage.value.length > 0
})

async function openBrowser() {
  if (!inputValue.value.trim()) {
    errorMessage.value = 'You need a URL to investigate!'
    return
  }

  // Add protocol if missing
  let url = inputValue.value.trim()
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    url = 'https://' + url
  }

  // Reset state
  isLoading.value = true
  isComplete.value = false
  errorMessage.value = ''
  screenshots.value = []
  cookies.value = []
  scripts.value = []
  localStorage.value = []
  sessionStorage.value = []
  networkRequests.value = []
  analysisResult.value = ''
  analysisError.value = ''
  highRisks.value = ''
  consentDetails.value = null
  statusMessage.value = 'Starting...'
  progressStep.value = 'init'
  progressPercent.value = 0
  currentUrl.value = url

  try {
    // Use EventSource for Server-Sent Events
    const eventSource = new EventSource(
      `http://localhost:3001/api/open-browser-stream?url=${encodeURIComponent(url)}`
    )

    eventSource.addEventListener('progress', (event) => {
      const data = JSON.parse(event.data)
      statusMessage.value = data.message
      progressStep.value = data.step
      progressPercent.value = data.progress
    })

    eventSource.addEventListener('screenshot', (event) => {
      const data = JSON.parse(event.data)
      // Add screenshot to the sequence
      if (data.screenshot) {
        screenshots.value.push(data.screenshot)
      }
      cookies.value = data.cookies || []
      scripts.value = data.scripts || []
      networkRequests.value = data.networkRequests || []
      localStorage.value = data.localStorage || []
      sessionStorage.value = data.sessionStorage || []
    })

    eventSource.addEventListener('consentDetails', (event) => {
      const data = JSON.parse(event.data) as ConsentDetails
      consentDetails.value = data
    })

    eventSource.addEventListener('complete', (event) => {
      const data = JSON.parse(event.data)
      
      if (data.analysis) {
        analysisResult.value = data.analysis
      }
      if (data.highRisks) {
        highRisks.value = data.highRisks
      }
      if (data.analysisError) {
        analysisError.value = data.analysisError
      }
      if (data.consentDetails) {
        consentDetails.value = data.consentDetails
      }
      
      // Set tab to risks if we have high risks, otherwise analysis
      activeTab.value = data.highRisks ? 'risks' : 'analysis'
      
      statusMessage.value = data.message
      progressPercent.value = 100
      isLoading.value = false
      isComplete.value = true
      eventSource.close()
    })

    eventSource.addEventListener('error', (event) => {
      // Check if it's an SSE event with data
      if (event instanceof MessageEvent) {
        const data = JSON.parse(event.data)
        errorMessage.value = data.error || 'An error occurred'
      } else {
        errorMessage.value = 'Connection error'
      }
      isLoading.value = false
      eventSource.close()
    })

    // Handle connection errors
    eventSource.onerror = () => {
      if (eventSource.readyState === EventSource.CLOSED) {
        // Stream ended normally
        return
      }
      errorMessage.value = 'Connection to server lost'
      isLoading.value = false
      eventSource.close()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'An error occurred'
    isLoading.value = false
  }
}

function formatExpiry(expires: number): string {
  if (expires === -1) return 'Session'
  const date = new Date(expires * 1000)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
}

function truncateValue(value: string, maxLength = 50): string {
  if (value.length <= maxLength) return value
  return value.substring(0, maxLength) + '...'
}

function getResourceTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    script: '📜',
    xhr: '🔄',
    fetch: '🔄',
    image: '🖼️',
    stylesheet: '🎨',
    font: '🔤',
    document: '📄',
    other: '📦',
  }
  return icons[type] || '📦'
}

function formatMarkdown(text: string): string {
  // Simple markdown to HTML conversion
  let html = text
    // Escape HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Headers
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Code blocks
    .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
    // Line breaks
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
  
  return `<p>${html}</p>`
}
</script>

<template>
  <div class="app-container">
    <header class="header">
      <img :src="logo" alt="Meddling Kids" class="logo" />
    </header>

    <div class="url-bar">
      <input
        v-model="inputValue"
        type="text"
        class="text-input"
        placeholder="Enter a suspicious URL to investigate..."
        @keyup.enter="openBrowser"
      />
      <button class="go-button" :disabled="isLoading" @click="openBrowser">
        {{ isLoading ? 'Sleuthing...' : 'Unmask' }}
      </button>
    </div>

    <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

    <!-- Loading Banner with Progress -->
    <div v-if="isLoading" class="status-banner loading">
      <div class="status-content">
        <span class="status-icon spinning">⏳</span>
        <span class="status-text">{{ statusMessage || 'Loading...' }}</span>
      </div>
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <span class="progress-percent">{{ progressPercent }}%</span>
      </div>
    </div>

    <!-- Screenshot sequence display -->
    <div v-if="screenshots.length > 0" class="screenshots-row">
      <div 
        v-for="(shot, index) in screenshots" 
        :key="index" 
        class="screenshot-thumb"
        @click="openScreenshotModal(shot, index)"
      >
        <img :src="shot" :alt="'Stage ' + (index + 1)" />
        <span class="screenshot-label">{{ index === 0 ? 'Initial' : index === 1 ? 'After Consent' : 'Final' }}</span>
      </div>
    </div>

    <!-- Screenshot Modal Overlay -->
    <Teleport to="body">
      <div v-if="selectedScreenshot" class="modal-overlay" @click.self="closeScreenshotModal">
        <div class="modal-content">
          <button class="modal-close" @click="closeScreenshotModal">&times;</button>
          <h3 class="modal-title">{{ selectedScreenshot.label }}</h3>
          <div class="modal-image-container">
            <img :src="selectedScreenshot.src" :alt="selectedScreenshot.label" class="modal-image" />
          </div>
        </div>
      </div>
    </Teleport>

    <div v-if="isComplete" class="main-content">
      <div class="tracking-panel full-width">
        <div class="tabs">
          <button 
            class="tab risk-tab" 
            :class="{ active: activeTab === 'risks', highlight: highRisks }"
            @click="activeTab = 'risks'"
          >
            🚨 High Risks
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'analysis', highlight: analysisResult }"
            @click="activeTab = 'analysis'"
          >
            🤖 Full Analysis
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'cookies' }"
            @click="activeTab = 'cookies'"
          >
            🍪 Cookies ({{ cookies.length }})
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'storage' }"
            @click="activeTab = 'storage'"
          >
            💾 Storage ({{ localStorage.length + sessionStorage.length }})
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'network' }"
            @click="activeTab = 'network'"
          >
            🌐 Network ({{ thirdPartyDomainCount }} 3rd party)
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'scripts' }"
            @click="activeTab = 'scripts'"
          >
            📜 Scripts ({{ scripts.length }})
          </button>
          <button 
            class="tab" 
            :class="{ active: activeTab === 'consent', highlight: consentDetails && (consentDetails.partners.length > 0 || consentDetails.categories.length > 0) }"
            @click="activeTab = 'consent'"
          >
            📋 Consent ({{ consentDetails?.partners.length || 0 }} partners)
          </button>
        </div>

        <div v-if="activeTab === 'cookies'" class="tab-content">
          <div v-if="cookies.length === 0" class="empty-state">
            No cookies detected yet
          </div>
          <div v-else class="domain-groups">
            <div v-for="(domainCookies, domain) in cookiesByDomain" :key="domain" class="domain-group">
              <h3 class="domain-header">{{ domain }} ({{ domainCookies.length }})</h3>
              <div v-for="cookie in domainCookies" :key="`${cookie.domain}-${cookie.name}`" class="cookie-item">
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

        <div v-if="activeTab === 'storage'" class="tab-content">
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

        <div v-if="activeTab === 'network'" class="tab-content">
          <div class="filter-bar">
            <label class="filter-checkbox">
              <input v-model="showOnlyThirdParty" type="checkbox" />
              Show only third-party requests ({{ thirdPartyDomainCount }} domains)
            </label>
          </div>
          <div v-if="filteredNetworkRequests.length === 0" class="empty-state">
            No network requests detected yet
          </div>
          <div v-else class="domain-groups">
            <div v-for="(domainRequests, domain) in networkByDomain" :key="domain" class="domain-group">
              <h3 class="domain-header">
                <span class="third-party-badge" v-if="domainRequests[0]?.isThirdParty">3rd Party</span>
                {{ domain }} ({{ domainRequests.length }})
              </h3>
              <div v-for="request in domainRequests" :key="request.url" class="network-item">
                <span class="resource-type">{{ getResourceTypeIcon(request.resourceType) }} {{ request.resourceType }}</span>
                <span class="request-method">{{ request.method }}</span>
                <a :href="request.url" target="_blank" class="request-url">{{ request.url }}</a>
              </div>
            </div>
          </div>
        </div>

        <div v-if="activeTab === 'scripts'" class="tab-content">
          <div v-if="scripts.length === 0" class="empty-state">
            No scripts detected yet
          </div>
          <div v-else class="domain-groups">
            <div v-for="(domainScripts, domain) in scriptsByDomain" :key="domain" class="domain-group">
              <h3 class="domain-header">{{ domain }} ({{ domainScripts.length }})</h3>
              <div v-for="script in domainScripts" :key="script.url" class="script-item">
                <a :href="script.url" target="_blank" class="script-url">{{ script.url }}</a>
              </div>
            </div>
          </div>
        </div>

        <div v-if="activeTab === 'consent'" class="tab-content consent-content">
          <div v-if="!consentDetails || (consentDetails.partners.length === 0 && consentDetails.categories.length === 0)" class="empty-state">
            <p>No consent dialog details extracted yet.</p>
            <p class="hint">This information is extracted from the cookie consent dialog before accepting.</p>
          </div>
          <div v-else class="consent-details">
            <div v-if="consentDetails.categories.length > 0" class="consent-section">
              <h3 class="consent-section-header">📂 Cookie Categories ({{ consentDetails.categories.length }})</h3>
              <div v-for="category in consentDetails.categories" :key="category.name" class="consent-category">
                <div class="category-header">
                  <span class="category-name">{{ category.name }}</span>
                  <span :class="['category-badge', category.required ? 'required' : 'optional']">
                    {{ category.required ? 'Required' : 'Optional' }}
                  </span>
                </div>
                <p class="category-description">{{ category.description }}</p>
              </div>
            </div>

            <div v-if="consentDetails.purposes.length > 0" class="consent-section">
              <h3 class="consent-section-header">🎯 Stated Purposes ({{ consentDetails.purposes.length }})</h3>
              <ul class="purposes-list">
                <li v-for="purpose in consentDetails.purposes" :key="purpose">{{ purpose }}</li>
              </ul>
            </div>

            <div v-if="consentDetails.partners.length > 0" class="consent-section">
              <h3 class="consent-section-header">🤝 Partners & Vendors ({{ consentDetails.partners.length }})</h3>
              <p class="section-hint">These are the third parties that will receive your data when you click "Accept All"</p>
              <div class="partners-grid">
                <div v-for="partner in consentDetails.partners" :key="partner.name" class="partner-card">
                  <div class="partner-name">{{ partner.name }}</div>
                  <div class="partner-purpose">{{ partner.purpose }}</div>
                  <div v-if="partner.dataCollected && partner.dataCollected.length > 0" class="partner-data">
                    <span class="data-label">Data collected:</span>
                    <span class="data-types">{{ partner.dataCollected.join(', ') }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="consentDetails.expanded" class="expanded-notice">
              ✅ Expanded consent preferences to gather more details
            </div>
          </div>
        </div>

        <div v-if="activeTab === 'risks'" class="tab-content risks-content">
          <div v-if="highRisks" class="risks-result" v-html="formatMarkdown(highRisks)">
          </div>
          <div v-else class="empty-state">
            <p>High risks summary will appear here once analysis is complete.</p>
          </div>
        </div>

        <div v-if="activeTab === 'analysis'" class="tab-content analysis-content">
          <div v-if="isLoading && progressStep === 'analysis'" class="analyzing-state">
            <div class="analyzing-spinner"></div>
            <p>Analyzing tracking data with AI...</p>
            <p class="analyzing-hint">This may take a moment</p>
          </div>
          <div v-else-if="analysisError" class="analysis-error">
            <p>⚠️ {{ analysisError }}</p>
          </div>
          <div v-else-if="analysisResult" class="analysis-result" v-html="formatMarkdown(analysisResult)">
          </div>
          <div v-else class="empty-state">
            <p>AI analysis will appear here once the page is fully loaded.</p>
            <p class="hint">The AI will analyze cookies, scripts, network requests, and storage to identify tracking technologies and assess privacy risks.</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-container {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1rem;
}

.header {
  text-align: center;
  margin-bottom: 1.5rem;
}

.logo {
  max-width: 320px;
  height: auto;
  margin-bottom: 1rem;
  filter: drop-shadow(3px 3px 4px rgba(0, 0, 0, 0.3));
}

.header h1 {
  margin: 0;
  font-size: 2rem;
}

.subtitle {
  color: #666;
  margin: 0.5rem 0 0;
}

.url-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  justify-content: center;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.text-input {
  padding: 0.75rem 1rem;
  font-size: 1rem;
  border: 1px solid #ccc;
  border-radius: 8px;
  width: 400px;
  font-family: inherit;
}

.text-input:focus {
  outline: none;
  border-color: #42b883;
}

.go-button {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: white;
  background-color: #0C67AC;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.go-button:hover {
  background-color: #21436E;
}

.go-button:disabled {
  background-color: #a0a0a0;
  cursor: not-allowed;
}

.analyze-button {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: white;
  background-color: #8b5cf6;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.analyze-button:hover {
  background-color: #7c3aed;
}

.analyze-button:disabled {
  background-color: #a0a0a0;
  cursor: not-allowed;
}

.error {
  color: #e74c3c;
  text-align: center;
  margin: 1rem 0;
}

.status-banner {
  background: linear-gradient(135deg, #d1fae5, #a7f3d0);
  border: 1px solid #10b981;
  border-radius: 12px;
  padding: 1rem 1.5rem;
  margin: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.status-banner.loading {
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  border-color: #f59e0b;
}

.status-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-weight: 500;
}

.status-icon {
  font-size: 1.25rem;
}

.status-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-container {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 0.5rem;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #10b981;
  border-radius: 4px;
  transition: width 0.3s ease-out;
}

.progress-percent {
  font-size: 0.85rem;
  font-weight: 600;
  min-width: 3rem;
  text-align: right;
}

.progress-steps {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.5rem;
  font-size: 0.75rem;
}

.step {
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.05);
  color: #888;
  transition: all 0.2s;
}

.step.active {
  background: #f59e0b;
  color: white;
  font-weight: 600;
}

.step.done {
  background: #10b981;
  color: white;
}

.consent-info {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.consent-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.85rem;
  font-weight: 500;
}

.consent-badge.success {
  background: #dcfce7;
  color: #166534;
}

.consent-badge.warning {
  background: #fef3c7;
  color: #92400e;
}

.consent-badge.info {
  background: #e0e7ff;
  color: #3730a3;
}

.consent-detail {
  color: #666;
  font-size: 0.85rem;
}

.main-content {
  margin-top: 1rem;
}

.tracking-panel {
  width: 100%;
}

.tracking-panel.full-width {
  width: 100%;
}

.tracking-panel h2 {
  margin: 0 0 1rem;
  font-size: 1.1rem;
}

/* Screenshot thumbnails row */
.screenshots-row {
  display: flex;
  gap: 1rem;
  margin: 1rem 0;
  padding: 1rem;
  background: #f8f9fa;
  border-radius: 12px;
  overflow-x: auto;
}

.screenshot-thumb {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.screenshot-thumb img {
  width: 200px;
  height: auto;
  border: 2px solid #ddd;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transition: transform 0.2s, border-color 0.2s;
}

.screenshot-thumb img:hover {
  transform: scale(1.05);
  border-color: #42b883;
}

.screenshot-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Screenshot Modal */
.modal-overlay {
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

.modal-content {
  background: white;
  border-radius: 12px;
  max-width: 95vw;
  max-height: 95vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.modal-close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 40px;
  height: 40px;
  border: none;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  font-size: 1.5rem;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
  z-index: 1001;
}

.modal-close:hover {
  background: rgba(0, 0, 0, 0.9);
}

.modal-title {
  margin: 0;
  padding: 1rem 1.5rem;
  font-size: 1.1rem;
  border-bottom: 1px solid #eee;
  background: #f8f9fa;
}

.modal-image-container {
  overflow: auto;
  max-height: calc(95vh - 60px);
}

.modal-image {
  display: block;
  max-width: 100%;
  height: auto;
}

.hint {
  font-weight: normal;
  color: #888;
  font-size: 0.85rem;
}

.screenshot-container {
  position: relative;
  border: 1px solid #ccc;
  border-radius: 8px;
  overflow: hidden;
}

.screenshot-container.loading {
  opacity: 0.7;
}

.screenshot {
  width: 100%;
  display: block;
  cursor: pointer;
}

.loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.2rem;
}

.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-bottom: 1rem;
}

.tab {
  flex: 1;
  min-width: fit-content;
  padding: 0.5rem 0.75rem;
  border: 1px solid #ccc;
  background: #f5f5f5;
  border-radius: 8px 8px 0 0;
  cursor: pointer;
  font-size: 0.8rem;
  transition: all 0.2s;
  white-space: nowrap;
}

.tab:hover {
  background: #e8e8e8;
}

.tab.active {
  background: white;
  border-bottom-color: white;
  font-weight: 600;
}

.tab.highlight {
  background: #f3e8ff;
  border-color: #8b5cf6;
}

.tab.highlight.active {
  background: white;
}

.tab.risk-tab {
  background: #fef2f2;
  border-color: #ef4444;
  color: #dc2626;
}

.tab.risk-tab:hover {
  background: #fee2e2;
}

.tab.risk-tab.active {
  background: white;
  font-weight: 600;
}

.tab.highlight {
  background: #f3e8ff;
  border-color: #8b5cf6;
}

.tab.highlight.active {
  background: white;
}

.tab-content {
  border: 1px solid #ccc;
  border-radius: 0 0 8px 8px;
  margin-top: -1px;
  max-height: 500px;
  overflow-y: auto;
  background: white;
}

.analysis-content {
  max-height: 600px;
  padding: 1rem;
}

.risks-content {
  max-height: 600px;
  padding: 1.5rem;
  background: linear-gradient(135deg, #fef2f2, #fff);
}

.risks-result {
  font-size: 1.05rem;
  line-height: 1.8;
}

.risks-result ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.risks-result li {
  padding: 0.75rem 1rem;
  margin: 0.5rem 0;
  background: white;
  border-radius: 8px;
  border-left: 4px solid #ef4444;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.analyzing-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem;
  text-align: center;
}

.analyzing-spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #e0e0e0;
  border-top-color: #8b5cf6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.analyzing-hint {
  color: #888;
  font-size: 0.85rem;
}

.analysis-error {
  padding: 2rem;
  text-align: center;
  color: #e74c3c;
}

.retry-button {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: #8b5cf6;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.retry-button:hover {
  background: #7c3aed;
}

.analysis-result {
  line-height: 1.6;
  color: #333;
}

.analysis-result :deep(h2) {
  font-size: 1.3rem;
  color: #1a1a1a;
  margin-top: 1.5rem;
  margin-bottom: 0.75rem;
  border-bottom: 2px solid #8b5cf6;
  padding-bottom: 0.25rem;
}

.analysis-result :deep(h3) {
  font-size: 1.1rem;
  color: #333;
  margin-top: 1.25rem;
  margin-bottom: 0.5rem;
}

.analysis-result :deep(h4) {
  font-size: 1rem;
  color: #444;
  margin-top: 1rem;
  margin-bottom: 0.5rem;
}

.analysis-result :deep(p) {
  margin: 0.5rem 0;
}

.analysis-result :deep(ul) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.analysis-result :deep(li) {
  margin: 0.25rem 0;
}

.analysis-result :deep(code) {
  background: #f0f0f0;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-family: monospace;
  font-size: 0.9em;
}

.analysis-result :deep(pre) {
  background: #f5f5f5;
  padding: 1rem;
  border-radius: 6px;
  overflow-x: auto;
}

.analysis-result :deep(strong) {
  color: #1a1a1a;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #888;
}

.domain-groups {
  padding: 0.5rem;
}

.domain-group {
  margin-bottom: 1rem;
}

.domain-header {
  font-size: 0.9rem;
  background: #f0f0f0;
  padding: 0.5rem;
  margin: 0;
  border-radius: 4px;
  position: sticky;
  top: 0;
}

.cookie-item,
.script-item,
.storage-item,
.network-item {
  padding: 0.5rem;
  border-bottom: 1px solid #eee;
  font-size: 0.85rem;
}

.cookie-item:last-child,
.script-item:last-child,
.storage-item:last-child,
.network-item:last-child {
  border-bottom: none;
}

.cookie-name {
  font-weight: 600;
  color: #333;
}

.cookie-value {
  color: #666;
  word-break: break-all;
}

.cookie-meta {
  margin-top: 0.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}

.badge {
  background: #e0e0e0;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
}

.expiry {
  font-size: 0.75rem;
  color: #888;
}

.script-url {
  color: #2563eb;
  word-break: break-all;
  text-decoration: none;
}

.script-url:hover {
  text-decoration: underline;
}

.storage-key {
  font-weight: 600;
  color: #333;
}

.storage-value {
  color: #666;
  word-break: break-all;
  font-family: monospace;
  font-size: 0.8rem;
  background: #f5f5f5;
  padding: 0.25rem;
  border-radius: 4px;
  margin-top: 0.25rem;
}

.filter-bar {
  padding: 0.5rem;
  background: #f5f5f5;
  border-bottom: 1px solid #ddd;
}

.filter-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.filter-checkbox input {
  cursor: pointer;
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  margin-right: 0.5rem;
}

.network-item {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
}

.resource-type {
  font-size: 0.75rem;
  color: #666;
  min-width: 80px;
}

.request-method {
  font-size: 0.7rem;
  font-weight: 600;
  background: #e0e0e0;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
}

.request-url {
  color: #2563eb;
  word-break: break-all;
  text-decoration: none;
  font-size: 0.8rem;
}

.request-url:hover {
  text-decoration: underline;
}

/* Consent Tab Styles */
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
  background: #f9fafb;
  border-radius: 8px;
  padding: 1rem;
}

.consent-section-header {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 0.5rem;
}

.section-hint {
  font-size: 0.85rem;
  color: #666;
  margin: -0.5rem 0 1rem;
}

.consent-category {
  background: white;
  border: 1px solid #e5e7eb;
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
  color: #1f2937;
}

.category-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.5rem;
  border-radius: 9999px;
  font-weight: 500;
}

.category-badge.required {
  background: #fef3c7;
  color: #92400e;
}

.category-badge.optional {
  background: #dbeafe;
  color: #1e40af;
}

.category-description {
  margin: 0;
  font-size: 0.85rem;
  color: #4b5563;
}

.purposes-list {
  margin: 0;
  padding-left: 1.5rem;
}

.purposes-list li {
  margin-bottom: 0.25rem;
  font-size: 0.9rem;
  color: #374151;
}

.partners-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
}

.partner-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 0.75rem;
}

.partner-name {
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.25rem;
}

.partner-purpose {
  font-size: 0.85rem;
  color: #4b5563;
  margin-bottom: 0.5rem;
}

.partner-data {
  font-size: 0.75rem;
  background: #f3f4f6;
  padding: 0.5rem;
  border-radius: 4px;
}

.data-label {
  color: #6b7280;
}

.data-types {
  color: #dc2626;
}

.expanded-notice {
  background: #d1fae5;
  color: #065f46;
  padding: 0.75rem;
  border-radius: 6px;
  font-size: 0.85rem;
  text-align: center;
}

@media (max-width: 900px) {
  .main-content {
    grid-template-columns: 1fr;
  }
  
  .text-input {
    width: 250px;
  }
}
</style>
