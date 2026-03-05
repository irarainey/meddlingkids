<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import logo from './assets/logo.svg'
import { useTrackingAnalysis } from './composables'
import {
  ProgressBanner,
  ScreenshotGallery,
  ScoreDialog,
  PageErrorDialog,
  ErrorDialog,
  SummaryTab,
  ConsentTab,
  CookiesTab,
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
  decodedCookies,
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

/** Back-to-top button — visible once the user scrolls past 300px. */
const showBackToTop = ref(false)

function onScroll(): void {
  showBackToTop.value = window.scrollY > 300
}

function scrollToTop(): void {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

window.addEventListener('scroll', onScroll, { passive: true })
onUnmounted(() => window.removeEventListener('scroll', onScroll))

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
        Feed any URL to these meddling kids and watch them unmask sneaky trackers, 
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
            :class="{ active: activeTab === 'summary', highlight: structuredReport || summaryFindings.length > 0 }"
            @click="activeTab = 'summary'"
          >
            📋 Summary
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
        </div>

        <!-- Tab Content Panels -->
        <SummaryTab
          v-if="activeTab === 'summary'"
          :is-analyzing="isLoading && progressStep === 'analysis'"
          :analysis-error="analysisError"
          :structured-report="structuredReport"
          :summary-findings="summaryFindings"
          :privacy-score="privacyScore"
          :privacy-summary="privacySummary"
        />

        <CookiesTab
          v-show="activeTab === 'cookies'"
          :cookies-by-domain="cookiesByDomain"
          :cookie-count="cookies.length"
          :analyzed-url="inputValue"
          :decoded-cookies="decodedCookies"
          :structured-report="structuredReport"
        />

        <ConsentTab
          v-show="activeTab === 'consent'"
          :consent-details="consentDetails"
          :structured-report="structuredReport"
        />

        <StorageTab
          v-show="activeTab === 'storage'"
          :local-storage="localStorage"
          :session-storage="sessionStorage"
          :structured-report="structuredReport"
        />

        <NetworkTab
          v-show="activeTab === 'network'"
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
          v-show="activeTab === 'scripts'"
          :scripts-by-domain="scriptsByDomain"
          :script-count="scripts.length"
          :script-groups="scriptGroups"
        />
    </div>

    <footer class="app-footer">
      Results are AI-generated and may be incorrect. All information should be considered informational and verified independently. Licensed under <a href="https://github.com/irarainey/meddlingkids/blob/main/LICENSE" target="_blank" rel="noopener">AGPL v3+</a>. Version {{ appVersion }}
      <br>Scooby-Doo and related imagery are trademarks of and &copy; Warner Bros. Entertainment Inc. Not affiliated with or endorsed by Warner Bros.
    </footer>

    <Transition name="fade">
      <button v-if="showBackToTop" class="back-to-top" title="Back to top" @click="scrollToTop">
        <span class="chevron-up"></span>
      </button>
    </Transition>
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
  width: 500px;
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
  line-height: 1.4;
}

.app-footer a {
  color: #6b7280;
  text-decoration: none;
  font-weight: normal;
  pointer-events: auto;
}

.app-footer a:hover {
  color: #7CB8E4;
  text-decoration: underline;
}

.app-footer .version {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.6rem;
}

.back-to-top {
  position: fixed;
  bottom: 1.5rem;
  right: 1.5rem;
  width: 2.75rem;
  height: 2.75rem;
  padding: 0;
  box-sizing: border-box;
  border-radius: 6px;
  border: 1px solid #3d4663;
  background: rgba(42, 47, 69, 0.7);
  color: #e0e7ff;
  font-size: 1.2rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(6px);
  transition: background 0.2s, border-color 0.2s;
  z-index: 100;
}

.back-to-top .chevron-up {
  display: block;
  width: 10px;
  height: 10px;
  border-left: 2.5px solid currentColor;
  border-top: 2.5px solid currentColor;
  transform: rotate(45deg);
  margin-top: 3px;
}

.back-to-top:hover {
  background: rgba(42, 47, 69, 0.95);
  border-color: #7CB8E4;
  color: #7CB8E4;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 900px) {
  .text-input {
    width: 250px;
  }
}
</style>
