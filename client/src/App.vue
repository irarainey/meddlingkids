<script setup lang="ts">
import { ref } from 'vue'
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
  NetworkTab,
  SummaryTab,
  ScriptsTab,
  StorageTab,
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
  activeTab,
  showOnlyThirdParty,
  analysisResult,
  analysisError,
  summaryFindings,
  privacyScore,
  privacySummary,
  showScoreDialog,
  consentDetails,
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
  thirdPartyDomainCount,

  // Methods
  openScreenshotModal,
  closeScreenshotModal,
  closeScoreDialog,
  closePageErrorDialog,
  closeErrorDialog,
  analyzeUrl,
} = useTrackingAnalysis()

const tabsRef = ref<HTMLElement | null>(null)

/** Close the score dialog and scroll to the report tabs. */
function handleViewReport(): void {
  closeScoreDialog()
  tabsRef.value?.scrollIntoView({ behavior: 'smooth' })
}
</script>

<template>
  <div>
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
    <ScreenshotGallery
      :screenshots="screenshots"
      :selected-screenshot="selectedScreenshot"
      @open-modal="openScreenshotModal"
      @close-modal="closeScreenshotModal"
    />

    <div v-if="isComplete" class="main-content">
      <!-- Tab Navigation -->
      <div ref="tabsRef" class="tabs">
          <button
            class="tab summary-tab"
            :class="{ active: activeTab === 'summary', highlight: summaryFindings.length > 0 }"
            @click="activeTab = 'summary'"
          >
            🛡️ Summary
          </button>
          <button
            class="tab"
            :class="{ active: activeTab === 'analysis', highlight: analysisResult }"
            @click="activeTab = 'analysis'"
          >
            📋 Full Analysis
          </button>
          <button class="tab" :class="{ active: activeTab === 'cookies' }" @click="activeTab = 'cookies'">
            🍪 Cookies ({{ cookies.length }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'storage' }" @click="activeTab = 'storage'">
            💾 Storage ({{ localStorage.length + sessionStorage.length }})
          </button>
          <button class="tab" :class="{ active: activeTab === 'network' }" @click="activeTab = 'network'">
            🌐 Network ({{ thirdPartyDomainCount }} 3rd party)
          </button>
          <button class="tab" :class="{ active: activeTab === 'scripts' }" @click="activeTab = 'scripts'">
            📜 Scripts ({{ scripts.length }})
          </button>
          <button
            class="tab"
            :class="{
              active: activeTab === 'consent',
              highlight: consentDetails && (consentDetails.partners.length > 0 || consentDetails.categories.length > 0),
            }"
            @click="activeTab = 'consent'"
          >
            🎯 Consent ({{ consentDetails?.partners.length || 0 }} partners)
          </button>
        </div>

        <!-- Tab Content Panels -->
        <SummaryTab v-if="activeTab === 'summary'" :summary-findings="summaryFindings" :privacy-score="privacyScore" />

        <AnalysisTab
          v-if="activeTab === 'analysis'"
          :is-analyzing="isLoading && progressStep === 'analysis'"
          :analysis-error="analysisError"
          :analysis-result="analysisResult"
        />

        <CookiesTab
          v-if="activeTab === 'cookies'"
          :cookies-by-domain="cookiesByDomain"
          :cookie-count="cookies.length"
        />

        <StorageTab
          v-if="activeTab === 'storage'"
          :local-storage="localStorage"
          :session-storage="sessionStorage"
        />

        <NetworkTab
          v-if="activeTab === 'network'"
          v-model:show-only-third-party="showOnlyThirdParty"
          :network-by-domain="networkByDomain"
          :filtered-network-requests="filteredNetworkRequests"
          :third-party-domain-count="thirdPartyDomainCount"
        />

        <ScriptsTab
          v-if="activeTab === 'scripts'"
          :scripts-by-domain="scriptsByDomain"
          :script-count="scripts.length"
          :script-groups="scriptGroups"
        />

        <ConsentTab v-if="activeTab === 'consent'" :consent-details="consentDetails" />
    </div>
  </div>
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
  font-size: 0.8rem;
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

@media (max-width: 900px) {
  .text-input {
    width: 250px;
  }
}
</style>
