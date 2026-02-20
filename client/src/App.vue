<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import logo from './assets/logo.svg'
import { useTrackingAnalysis } from './composables'
import {
  ProgressBanner,
  ScreenshotGallery,
  ScoreDialog,
  PageErrorDialog,
  ErrorDialog,
  AnalysisTab,
  ConsentTab,
  CookiesTab,
  DebugLogTab,
  NetworkTab,
  ScriptsTab,
  StorageTab,
  TrackerGraphTab,
} from './components'

// All state, computed properties, and methods from the composable
const {
  // State
  inputValue,
  deviceType,
  isLoading,
  isComplete,
  screenshots,
  cookies,
  scripts,
  scriptGroups,
  localStorage,
  sessionStorage,
  networkRequests,
  activeTab,
  consentDetails,
  structuredReport,
  analysisError,
  summaryFindings,
  privacyScore,
  privacySummary,
  showScoreDialog,
  pageError,
  showPageErrorDialog,
  errorDialog,
  showErrorDialog,
  statusMessage,
  progressStep,
  progressPercent,
  selectedScreenshot,
  debugLog,

  // Computed
  scriptsByDomain,
  cookiesByDomain,
  filteredNetworkRequests,
  networkByDomain,
  graphConnectionCount,

  // Methods
  openScreenshotModal,
  closeScreenshotModal,
  closeScoreDialog,
  closePageErrorDialog,
  closeErrorDialog,
  analyzeUrl,
} = useTrackingAnalysis()

const tabsRef = ref<HTMLElement | null>(null)
const galleryRef = ref<HTMLElement | null>(null)

const appVersion = __APP_VERSION__
const serverVersion = ref('')

onMounted(async () => {
  const apiBase = import.meta.env.VITE_API_URL || ''
  const maxAttempts = 5
  const delayMs = 3000

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(`${apiBase}/api/version`)
      if (res.ok) {
        const data = await res.json()
        serverVersion.value = data.version
        return
      }
    } catch {
      // Server not ready yet — retry after a short delay
    }
    if (attempt < maxAttempts) {
      await new Promise(r => setTimeout(r, delayMs))
    }
  }
})

/** Show the Debug Log tab only when ?debug=true is in the URL. */
const debugMode = new URLSearchParams(window.location.search).get('debug') === 'true'

/** Scroll to the screenshot gallery when the first screenshot arrives. */
watch(
  () => screenshots.value.length,
  (len, oldLen) => {
    if (len === 1 && (oldLen === 0 || oldLen === undefined)) {
      nextTick(() => {
        galleryRef.value?.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        })
      })
    }
  },
)

/** Close the score dialog and scroll to the report tabs. */
function handleViewReport(): void {
  closeScoreDialog()
  tabsRef.value?.scrollIntoView({ behavior: 'smooth' })
}

/** Select all text in the URL input on focus, preventing mouseup deselection. */
let selectOnNextMouseUp = false
function onUrlFocus(event: Event): void {
  const input = event.target as HTMLInputElement
  input.select()
  selectOnNextMouseUp = true
}
function onUrlMouseUp(event: Event): void {
  if (selectOnNextMouseUp) {
    event.preventDefault()
    selectOnNextMouseUp = false
  }
}
</script>

<template>
  <header class="header">
      <img :src="logo" alt="Meddling Kids" class="logo" />
      <p class="tagline">
        Feed any news site URL to these meddling kids and watch them unmask sneaky trackers, 
        cookies, scripts, and shady consent dialogs lurking underneath!
      </p>
    </header>

    <div class="url-bar">
      <input
        v-model="inputValue"
        type="text"
        class="text-input"
        placeholder="Enter a suspicious URL to investigate..."
        :disabled="isLoading"
        @keyup.enter="analyzeUrl"
        @focus="onUrlFocus"
        @mouseup="onUrlMouseUp"
      />
      <select v-model="deviceType" class="device-select" :disabled="isLoading">
        <option value="iphone">iPhone</option>
        <option value="ipad">iPad</option>
        <option value="android-phone">Android Phone</option>
        <option value="android-tablet">Android Tablet</option>
        <option value="windows-chrome">Windows Chrome</option>
        <option value="macos-safari">macOS Safari</option>
      </select>
      <button class="go-button" :disabled="isLoading" @click="analyzeUrl">
        {{ isLoading ? 'Investigating...' : 'Unmask' }}
      </button>
    </div>

    <!-- Loading Banner with Progress -->
    <ProgressBanner
      v-if="isLoading"
      :status-message="statusMessage"
      :progress-percent="progressPercent"
    />

    <!-- Privacy Score Dialog -->
    <ScoreDialog
      :is-open="showScoreDialog"
      :score="privacyScore ?? 0"
      :summary="privacySummary"
      @close="closeScoreDialog"
      @view-report="handleViewReport"
    />

    <!-- Page Error Dialog -->
    <PageErrorDialog
      :is-open="showPageErrorDialog"
      :error-type="pageError?.type ?? null"
      :message="pageError?.message ?? ''"
      :status-code="pageError?.statusCode ?? null"
      @close="closePageErrorDialog"
    />

    <!-- Generic Error Dialog -->
    <ErrorDialog
      :is-open="showErrorDialog"
      :title="errorDialog?.title ?? 'Error'"
      :message="errorDialog?.message ?? ''"
      @close="closeErrorDialog"
    />

    <!-- Screenshot Gallery -->
    <div ref="galleryRef">
    <ScreenshotGallery
      :screenshots="screenshots"
      :selected-screenshot="selectedScreenshot"
      @open-modal="openScreenshotModal"
      @close-modal="closeScreenshotModal"
    />
    </div>

    <div v-if="isComplete" class="main-content">
      <!-- Tab Navigation -->
      <div ref="tabsRef" class="tabs">
          <button
            class="tab"
            :class="{ active: activeTab === 'analysis', highlight: structuredReport || summaryFindings.length > 0 }"
            @click="activeTab = 'analysis'"
          >
            📋 Analysis
          </button>
          <button v-if="consentDetails" class="tab" :class="{ active: activeTab === 'consent' }" @click="activeTab = 'consent'">
            🎯 Consent
          </button>
          <button class="tab" :class="{ active: activeTab === 'cookies' }" @click="activeTab = 'cookies'">
            🍪 Cookies ({{ cookies.length }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'storage' }" @click="activeTab = 'storage'">
            💾 Storage ({{ localStorage.length + sessionStorage.length }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'network' }" @click="activeTab = 'network'">
            🌐 Network ({{ filteredNetworkRequests.length }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'tracker-graph' }" @click="activeTab = 'tracker-graph'">
            🕸️ Graph ({{ graphConnectionCount }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'scripts' }" @click="activeTab = 'scripts'">
            📜 Scripts ({{ scripts.length }})
          </button>
          <button v-if="debugMode" class="tab" :class="{ active: activeTab === 'debug-log' }" @click="activeTab = 'debug-log'">
            🪵 Debug Log
          </button>
        </div>

        <!-- Tab Content Panels -->
        <AnalysisTab
          v-if="activeTab === 'analysis'"
          :is-analyzing="isLoading && progressStep === 'analysis'"
          :analysis-error="analysisError"
          :structured-report="structuredReport"
          :summary-findings="summaryFindings"
          :privacy-score="privacyScore"
          :privacy-summary="privacySummary"
        />

        <CookiesTab
          v-if="activeTab === 'cookies'"
          :cookies-by-domain="cookiesByDomain"
          :cookie-count="cookies.length"
        />

        <ConsentTab
          v-show="activeTab === 'consent'"
          :consent-details="consentDetails"
        />

        <StorageTab
          v-if="activeTab === 'storage'"
          :local-storage="localStorage"
          :session-storage="sessionStorage"
        />

        <NetworkTab
          v-if="activeTab === 'network'"
          :network-by-domain="networkByDomain"
          :filtered-network-requests="filteredNetworkRequests"
        />

        <TrackerGraphTab
          v-if="activeTab === 'tracker-graph'"
          :network-requests="networkRequests"
          :structured-report="structuredReport"
          :analyzed-url="inputValue"
        />

        <ScriptsTab
          v-if="activeTab === 'scripts'"
          :scripts-by-domain="scriptsByDomain"
          :script-count="scripts.length"
          :script-groups="scriptGroups"
        />

        <DebugLogTab
          v-if="activeTab === 'debug-log'"
          :log-lines="debugLog"
        />
    </div>

    <footer class="app-footer">
      Results are AI-generated and may be incorrect. All information should be considered informational and verified independently. Client {{ appVersion }}<span v-if="serverVersion"> : Server {{ serverVersion }}</span>
    </footer>
</template>

<style scoped>
.header {
  text-align: center;
  margin-bottom: 1.5rem;
}

.logo {
  max-width: 272px;
  height: auto;
  margin-bottom: 0.75rem;
  filter: drop-shadow(3px 3px 4px rgba(0, 0, 0, 0.3));
}

.tagline {
  max-width: 650px;
  margin: 0 auto 0.75rem;
  font-size: 0.95rem;
  line-height: 1.5;
  color: #9ca3af;
  padding: 0 1rem;
}

.url-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  justify-content: center;
  margin-bottom: 1.6rem;
  flex-wrap: wrap;
}

.text-input {
  padding: 0.75rem 1rem;
  font-size: 1rem;
  border: 1px solid #3d4663;
  border-radius: 8px;
  width: 400px;
  font-family: inherit;
  background: #1e2235;
  color: #e0e7ff;
}

.text-input:focus {
  outline: none;
  border-color: #0C67AC;
}

.text-input::placeholder {
  color: #9ca3af;
}

.text-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.device-select {
  padding: 0.75rem 1rem;
  font-size: 0.9rem;
  border: 1px solid #3d4663;
  border-radius: 8px;
  font-family: inherit;
  background: #1e2235;
  color: #e0e7ff;
  cursor: pointer;
  min-width: 150px;
}

.device-select:focus {
  outline: none;
  border-color: #0C67AC;
}

.device-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.go-button {
  padding: 0.75rem 1.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: white;
  background-color: #0c67ac;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.go-button:hover {
  background-color: #21436e;
}

.go-button:disabled {
  background-color: #4a5568;
  cursor: not-allowed;
}

.error {
  color: #f87171;
  text-align: center;
  margin: 1rem 0;
}

.main-content {
  margin-top: 1rem;
}

/* Tab Navigation */
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}

.tab {
  flex: 1;
  min-width: fit-content;
  padding: 0.5rem 0.75rem;
  border: 1px solid #3d4663;
  background: #151825;
  color: #9ca3af;
  border-radius: 8px 8px 0 0;
  cursor: pointer;
  font-size: 1.0rem;
  transition: all 0.2s;
  white-space: nowrap;
}

.tab:hover {
  background: #1a1e2e;
}

.tab.active {
  background: #1e2235;
  border-bottom-color: #1e2235;
  font-weight: 600;
  color: #e0e7ff;
  border-bottom: 1px solid #1e2235;
}

.app-footer {
  margin-top: auto;
  text-align: center;
  color: #4b5563;
  font-size: 0.7rem;
  padding: 1.5rem 1rem 0.5rem;
  user-select: none;
  pointer-events: none;
  line-height: 1.4;
}

.app-footer .version {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.6rem;
}

@media (max-width: 900px) {
  .text-input {
    width: 250px;
  }
}
</style>
