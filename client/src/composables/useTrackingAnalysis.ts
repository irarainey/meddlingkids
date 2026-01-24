/**
 * @fileoverview Composable for URL tracking analysis.
 * Manages the state and logic for analyzing a URL's tracking behavior.
 */

import { ref, computed } from 'vue'
import type {
  TrackedCookie,
  TrackedScript,
  StorageItem,
  NetworkRequest,
  ConsentDetails,
  ScreenshotModal,
  TabId,
} from '../types'

/**
 * Composable that provides all state and methods for tracking analysis.
 * Handles SSE connection, data collection, and computed groupings.
 */
export function useTrackingAnalysis() {
  // ============================================================================
  // State
  // ============================================================================

  /** URL input field value */
  const inputValue = ref('')
  /** Currently analyzed URL */
  const currentUrl = ref('')
  /** Selected device/browser type */
  const deviceType = ref('ipad')
  /** Whether analysis is in progress */
  const isLoading = ref(false)
  /** Whether analysis has completed */
  const isComplete = ref(false)
  /** Error message to display */
  const errorMessage = ref('')

  /** Screenshots captured during analysis */
  const screenshots = ref<string[]>([])
  /** Cookies captured from the page */
  const cookies = ref<TrackedCookie[]>([])
  /** Scripts loaded by the page */
  const scripts = ref<TrackedScript[]>([])
  /** localStorage items from the page */
  const localStorage = ref<StorageItem[]>([])
  /** sessionStorage items from the page */
  const sessionStorage = ref<StorageItem[]>([])
  /** Network requests made by the page */
  const networkRequests = ref<NetworkRequest[]>([])

  /** Currently active tab */
  const activeTab = ref<TabId>('risks')
  /** Whether to filter to third-party requests only */
  const showOnlyThirdParty = ref(true)

  /** Full AI analysis result (markdown) */
  const analysisResult = ref('')
  /** Analysis error message if AI failed */
  const analysisError = ref('')
  /** High risks summary from AI */
  const highRisks = ref('')
  /** Privacy risk score (0-100) */
  const privacyScore = ref<number | null>(null)
  /** One-sentence privacy summary */
  const privacySummary = ref('')
  /** Whether the score dialog is visible */
  const showScoreDialog = ref(false)
  /** Consent details extracted from the page */
  const consentDetails = ref<ConsentDetails | null>(null)
  
  /** Page error information (access denied, server error, etc.) */
  const pageError = ref<{
    type: 'access-denied' | 'server-error' | null
    message: string
    statusCode: number | null
  } | null>(null)
  /** Whether the page error dialog is visible */
  const showPageErrorDialog = ref(false)

  /** Current status message during analysis */
  const statusMessage = ref('')
  /** Current progress step identifier */
  const progressStep = ref('')
  /** Progress percentage (0-100) */
  const progressPercent = ref(0)

  /** Screenshot modal state */
  const selectedScreenshot = ref<ScreenshotModal | null>(null)

  // ============================================================================
  // Computed Properties
  // ============================================================================

  /** Scripts grouped by domain */
  const scriptsByDomain = computed(() => {
    const grouped: Record<string, TrackedScript[]> = {}
    for (const script of scripts.value) {
      const domain = script.domain
      if (!(domain in grouped)) {
        grouped[domain] = []
      }
      grouped[domain]!.push(script)
    }
    return grouped
  })

  /** Cookies grouped by domain */
  const cookiesByDomain = computed(() => {
    const grouped: Record<string, TrackedCookie[]> = {}
    for (const cookie of cookies.value) {
      const domain = cookie.domain
      if (!(domain in grouped)) {
        grouped[domain] = []
      }
      grouped[domain]!.push(cookie)
    }
    return grouped
  })

  /** Network requests filtered by third-party setting */
  const filteredNetworkRequests = computed(() => {
    if (showOnlyThirdParty.value) {
      return networkRequests.value.filter((r) => r.isThirdParty)
    }
    return networkRequests.value
  })

  /** Filtered network requests grouped by domain, sorted by request count */
  const networkByDomain = computed(() => {
    const grouped: Record<string, NetworkRequest[]> = {}
    for (const request of filteredNetworkRequests.value) {
      const domain = request.domain
      if (!(domain in grouped)) {
        grouped[domain] = []
      }
      grouped[domain]!.push(request)
    }
    // Sort by number of requests (most active domains first)
    return Object.fromEntries(Object.entries(grouped).sort((a, b) => b[1].length - a[1].length))
  })

  /** Count of unique third-party domains */
  const thirdPartyDomainCount = computed(() => {
    const domains = new Set(networkRequests.value.filter((r) => r.isThirdParty).map((r) => r.domain))
    return domains.size
  })

  // ============================================================================
  // Methods
  // ============================================================================

  /**
   * Reset all state to initial values.
   */
  function resetState() {
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
    privacyScore.value = null
    privacySummary.value = ''
    showScoreDialog.value = false
    consentDetails.value = null
    pageError.value = null
    showPageErrorDialog.value = false
    statusMessage.value = 'Starting...'
    progressStep.value = 'init'
    progressPercent.value = 0
  }

  /**
   * Open the screenshot modal with a specific screenshot.
   *
   * @param src - Base64 data URL of the screenshot
   * @param index - Index of the screenshot (0=Initial, 1=After Consent, 2=Final)
   */
  function openScreenshotModal(src: string, index: number) {
    const labels = ['Initial', 'After Consent', 'Final']
    selectedScreenshot.value = { src, label: labels[index] || `Stage ${index + 1}` }
  }

  /**
   * Close the screenshot modal.
   */
  function closeScreenshotModal() {
    selectedScreenshot.value = null
  }

  /**
   * Analyze tracking on a URL using the server's SSE endpoint.
   * Connects to the server and processes streaming events.
   */
  async function analyzeUrl() {
    if (!inputValue.value.trim()) {
      errorMessage.value = 'You need a URL to investigate!'
      return
    }

    // Add protocol if missing
    let url = inputValue.value.trim()
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url
    }

    resetState()
    currentUrl.value = url

    try {
      // Use relative URL in production (same origin), absolute in development
      const apiBase = import.meta.env.VITE_API_URL || ''
      const eventSource = new EventSource(
        `${apiBase}/api/open-browser-stream?url=${encodeURIComponent(url)}&device=${encodeURIComponent(deviceType.value)}`
      )

      eventSource.addEventListener('progress', (event) => {
        const data = JSON.parse(event.data)
        statusMessage.value = data.message
        progressStep.value = data.step
        progressPercent.value = data.progress
      })

      eventSource.addEventListener('screenshot', (event) => {
        const data = JSON.parse(event.data)
        if (data.screenshot) {
          screenshots.value.push(data.screenshot)
        }
        cookies.value = data.cookies || []
        scripts.value = data.scripts || []
        networkRequests.value = data.networkRequests || []
        localStorage.value = data.localStorage || []
        sessionStorage.value = data.sessionStorage || []
      })

      eventSource.addEventListener('pageError', (event) => {
        const data = JSON.parse(event.data)
        pageError.value = {
          type: data.isAccessDenied ? 'access-denied' : 'server-error',
          message: data.message || 'Failed to load page',
          statusCode: data.statusCode,
        }
        showPageErrorDialog.value = true
        isLoading.value = false
        eventSource.close()
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
        if (data.privacyScore !== null && data.privacyScore !== undefined) {
          privacyScore.value = data.privacyScore
          privacySummary.value = data.privacySummary || ''
        }
        if (data.analysisError) {
          analysisError.value = data.analysisError
        }
        if (data.consentDetails) {
          consentDetails.value = data.consentDetails
        }

        activeTab.value = data.highRisks ? 'risks' : 'analysis'
        statusMessage.value = data.message
        progressPercent.value = 100
        isComplete.value = true
        
        // Wait for the van animation to complete (500ms transition) before hiding progress and showing score dialog
        setTimeout(() => {
          isLoading.value = false
          if (data.privacyScore !== null && data.privacyScore !== undefined) {
            showScoreDialog.value = true
          }
        }, 700)
        eventSource.close()
      })

      eventSource.addEventListener('error', (event) => {
        if (event instanceof MessageEvent) {
          const data = JSON.parse(event.data)
          errorMessage.value = data.error || 'An error occurred'
        } else {
          errorMessage.value = 'Connection error'
        }
        isLoading.value = false
        eventSource.close()
      })

      eventSource.onerror = () => {
        if (eventSource.readyState === EventSource.CLOSED) {
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

  // ============================================================================
  // Return Public API
  // ============================================================================

  return {
    // State
    inputValue,
    deviceType,
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
    privacyScore,
    privacySummary,
    showScoreDialog,
    consentDetails,
    pageError,
    showPageErrorDialog,
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
    closeScoreDialog: () => { showScoreDialog.value = false },
    closePageErrorDialog: () => { showPageErrorDialog.value = false },
    analyzeUrl,
  }
}
