<script setup lang="ts">
import logo from './assets/logo.svg'
import { useTrackingAnalysis } from './composables'
import {
  ProgressBanner,
  ScreenshotGallery,
  AnalysisTab,
  ConsentTab,
  CookiesTab,
  NetworkTab,
  RisksTab,
  ScriptsTab,
  StorageTab,
} from './components'

// All state, computed properties, and methods from the composable
const {
  // State
  inputValue,
  isLoading,
  isComplete,
  errorMessage,
  screenshots,
  cookies,
  scripts,
  localStorage,
  sessionStorage,
  activeTab,
  showOnlyThirdParty,
  analysisResult,
  analysisError,
  highRisks,
  consentDetails,
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
  analyzeUrl,
} = useTrackingAnalysis()
</script>

<template>
  <div>
    <header class="header">
      <img :src="logo" alt="Meddling Kids" class="logo" />
    </header>

    <div class="url-bar">
      <input
        v-model="inputValue"
        type="text"
        class="text-input"
        placeholder="Enter a suspicious URL to investigate..."
        @keyup.enter="analyzeUrl"
      />
      <button class="go-button" :disabled="isLoading" @click="analyzeUrl">
        {{ isLoading ? 'Sleuthing...' : 'Unmask' }}
      </button>
    </div>

    <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

    <!-- Loading Banner with Progress -->
    <ProgressBanner
      v-if="isLoading"
      :status-message="statusMessage"
      :progress-percent="progressPercent"
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
            📋 Consent ({{ consentDetails?.partners.length || 0 }} partners)
          </button>
        </div>

        <!-- Tab Content Panels -->
        <RisksTab v-if="activeTab === 'risks'" :high-risks="highRisks" />

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
  max-width: 320px;
  height: auto;
  margin-bottom: 1rem;
  filter: drop-shadow(3px 3px 4px rgba(0, 0, 0, 0.3));
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
  background-color: #a0a0a0;
  cursor: not-allowed;
}

.error {
  color: #e74c3c;
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

@media (max-width: 900px) {
  .text-input {
    width: 250px;
  }
}
</style>
