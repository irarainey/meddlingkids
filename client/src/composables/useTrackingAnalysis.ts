/**
 * @fileoverview Composable for URL tracking analysis.
 * Manages the state and logic for analyzing a URL's tracking behavior.
 */

import { ref, computed, onUnmounted } from 'vue'
import type {
  TrackedCookie,
  TrackedScript,
  StorageItem,
  NetworkRequest,
  ConsentDetails,
  ScreenshotModal,
  TabId,
  SummaryFinding,
  ScriptGroup,
  PageError,
  ErrorDialogState,
  StructuredReport,
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
  /** Selected device/browser type */
  const deviceType = ref('ipad')
  /** Whether analysis is in progress */
  const isLoading = ref(false)
  /** Whether analysis has completed */
  const isComplete = ref(false)

  /** Screenshots captured during analysis */
  const screenshots = ref<string[]>([])
  /** Cookies captured from the page */
  const cookies = ref<TrackedCookie[]>([])
  /** Scripts loaded by the page */
  const scripts = ref<TrackedScript[]>([])
  /** Script groups (e.g., application chunks) */
  const scriptGroups = ref<ScriptGroup[]>([])
  /** localStorage items from the page */
  const localStorage = ref<StorageItem[]>([])
  /** sessionStorage items from the page */
  const sessionStorage = ref<StorageItem[]>([])
  /** Network requests made by the page */
  const networkRequests = ref<NetworkRequest[]>([])

  /** Currently active tab */
  const activeTab = ref<TabId>('analysis')

  /** Full AI analysis result (markdown) */
  const analysisResult = ref('')
  /** Structured analysis report */
  const structuredReport = ref<StructuredReport | null>(null)
  /** Analysis error message if AI failed */
  const analysisError = ref('')
  /** Summary findings from AI */
  const summaryFindings = ref<SummaryFinding[]>([])
  /** Privacy risk score (0-100) */
  const privacyScore = ref<number | null>(null)
  /** One-sentence privacy summary */
  const privacySummary = ref('')
  /** Whether the score dialog is visible */
  const showScoreDialog = ref(false)
  /** Consent details extracted from the page */
  const consentDetails = ref<ConsentDetails | null>(null)
  
  /** Page error information (access denied, server error, etc.) */
  const pageError = ref<PageError | null>(null)
  /** Whether the page error dialog is visible */
  const showPageErrorDialog = ref(false)

  /** Generic error dialog state */
  const errorDialog = ref<ErrorDialogState | null>(null)
  /** Whether the generic error dialog is visible */
  const showErrorDialog = ref(false)

  /** Current status message during analysis */
  const statusMessage = ref('')
  /** Current progress step identifier */
  const progressStep = ref('')
  /** Progress percentage (0-100) */
  const progressPercent = ref(0)

  /** Screenshot modal state */
  const selectedScreenshot = ref<ScreenshotModal | null>(null)

  /** Server debug log lines collected during analysis */
  const debugLog = ref<string[]>([])

  /** Active SSE connection (tracked for cleanup) */
  let activeEventSource: EventSource | null = null

  // Clean up SSE connection when the composable's owner component unmounts
  onUnmounted(() => {
    if (activeEventSource) {
      activeEventSource.close()
      activeEventSource = null
    }
  })

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

  /** Network requests filtered by resource type and deduplicated */
  const filteredNetworkRequests = computed(() => {
    /** File extensions that indicate image or font resources */
    const imageExtensions = /\.(png|jpe?g|gif|svg|ico|webp|avif|bmp|tiff?)(\?|$)/i
    const fontExtensions = /\.(woff2?|ttf|otf|eot)(\?|$)/i

    const filtered = networkRequests.value.filter((r) => {
      // Exclude all image requests
      if (r.resourceType?.toLowerCase() === 'image') return false

      // Exclude GET requests with image file extensions regardless of resourceType
      if (r.method?.toUpperCase() === 'GET' && imageExtensions.test(r.url)) return false

      // Exclude GET requests with font file extensions regardless of resourceType
      if (r.method?.toUpperCase() === 'GET' && fontExtensions.test(r.url)) return false

      // Exclude GET requests for scripts, stylesheets, documents, and fonts
      const type = r.resourceType?.toLowerCase()
      if (
        r.method?.toUpperCase() === 'GET' &&
        (type === 'script' || type === 'stylesheet' || type === 'document' || type === 'font')
      ) {
        return false
      }

      return true
    })

    // Collapse duplicate GET requests to the same URL into one record
    const seen = new Map<string, NetworkRequest>()
    const result: NetworkRequest[] = []
    for (const request of filtered) {
      if (request.method?.toUpperCase() === 'GET') {
        const existing = seen.get(request.url)
        if (existing) {
          existing.duplicateCount = (existing.duplicateCount ?? 1) + 1
          // Preserve pre-consent flag if any duplicate was pre-consent
          if (request.preConsent) existing.preConsent = true
        } else {
          const entry = { ...request, duplicateCount: 1 }
          seen.set(request.url, entry)
          result.push(entry)
        }
      } else {
        result.push(request)
      }
    }
    return result
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

  // ============================================================================
  // Methods
  // ============================================================================

  /**
   * Reset all state to initial values.
   */
  function resetState() {
    isLoading.value = true
    isComplete.value = false
    screenshots.value = []
    cookies.value = []
    scripts.value = []
    scriptGroups.value = []
    localStorage.value = []
    sessionStorage.value = []
    networkRequests.value = []
    analysisResult.value = ''
    structuredReport.value = null
    analysisError.value = ''
    summaryFindings.value = []
    privacyScore.value = null
    privacySummary.value = ''
    showScoreDialog.value = false
    consentDetails.value = null
    pageError.value = null
    showPageErrorDialog.value = false
    errorDialog.value = null
    showErrorDialog.value = false
    statusMessage.value = 'Initializing...'
    progressStep.value = 'init'
    progressPercent.value = 0
    debugLog.value = []
  }

  /**
   * Open the screenshot modal with a specific screenshot.
   *
   * @param src - Base64 data URL of the screenshot
   * @param index - Index of the screenshot in the gallery
   */
  function openScreenshotModal(src: string, index: number) {
    const label = `${index + 1}`
    selectedScreenshot.value = { src, label }
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
      errorDialog.value = {
        title: 'URL Required',
        message: 'You need a URL to investigate!',
      }
      showErrorDialog.value = true
      return
    }

    // Add protocol if missing
    let url = inputValue.value.trim()
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url
    }

    resetState()

    try {
      // Use relative URL in production (same origin), absolute in development
      const apiBase = import.meta.env.VITE_API_URL || ''
      const eventSource = new EventSource(
        `${apiBase}/api/open-browser-stream?url=${encodeURIComponent(url)}&device=${encodeURIComponent(deviceType.value)}`
      )
      activeEventSource = eventSource

      eventSource.addEventListener('progress', (event) => {
        try {
          const data = JSON.parse(event.data)
          statusMessage.value = data.message
          progressStep.value = data.step
          // Only advance — never allow the progress bar to go backward.
          // The server emits progress values from multiple concurrent
          // pipeline stages that may arrive out of order.
          progressPercent.value = Math.max(progressPercent.value, data.progress)
        } catch {
          console.error('[SSE] Failed to parse progress event')
        }
      })

      eventSource.addEventListener('screenshot', (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.screenshot) {
            screenshots.value.push(data.screenshot)
          }
          cookies.value = data.cookies || []
          scripts.value = data.scripts || []
          networkRequests.value = data.networkRequests || []
          localStorage.value = data.localStorage || []
          sessionStorage.value = data.sessionStorage || []
        } catch {
          console.error('[SSE] Failed to parse screenshot event')
        }
      })

      eventSource.addEventListener('screenshotUpdate', (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.screenshot && screenshots.value.length > 0) {
            screenshots.value[screenshots.value.length - 1] = data.screenshot
          }
        } catch {
          console.error('[SSE] Failed to parse screenshotUpdate event')
        }
      })

      eventSource.addEventListener('pageError', (event) => {
        try {
          const data = JSON.parse(event.data)
          pageError.value = {
            type: data.isAccessDenied ? 'access-denied' : data.isOverlayBlocked ? 'overlay-blocked' : 'server-error',
            message: data.message || 'Failed to load page',
            statusCode: data.statusCode,
          }
          showPageErrorDialog.value = true
          isLoading.value = false
          eventSource.close()
          activeEventSource = null
        } catch {
          console.error('[SSE] Failed to parse pageError event')
        }
      })

      eventSource.addEventListener('consentDetails', (event) => {
        try {
          const data = JSON.parse(event.data) as ConsentDetails
          consentDetails.value = data
        } catch {
          console.error('[SSE] Failed to parse consentDetails event')
        }
      })

      eventSource.addEventListener('complete', (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.summaryFindings) {
            summaryFindings.value = data.summaryFindings
          }
          if (data.privacyScore !== null && data.privacyScore !== undefined) {
            privacyScore.value = data.privacyScore
            privacySummary.value = data.privacySummary || ''
          }
          if (data.analysis) {
            analysisResult.value = data.analysis
          }
          if (data.structuredReport) {
            structuredReport.value = data.structuredReport
          }
          if (data.analysisError) {
            analysisError.value = data.analysisError
          }
          if (data.consentDetails) {
            consentDetails.value = data.consentDetails
          }
          // Update scripts with analyzed descriptions if available
          if (data.scripts) {
            scripts.value = data.scripts
          }
          // Update script groups if available
          if (data.scriptGroups) {
            scriptGroups.value = data.scriptGroups
          }
          if (data.debugLog) {
            debugLog.value = data.debugLog
          }

          activeTab.value = 'analysis'
          statusMessage.value = data.message
          progressPercent.value = 100
          isComplete.value = true
          
          // Wait for the van animation to complete (500ms CSS transition + buffer)
          // before hiding progress and showing score dialog
          setTimeout(() => {
            isLoading.value = false
            if (data.privacyScore !== null && data.privacyScore !== undefined) {
              showScoreDialog.value = true
            }
          }, 700)
          eventSource.close()
          activeEventSource = null
        } catch {
          console.error('[SSE] Failed to parse complete event')
        }
      })

      eventSource.addEventListener('error', (event) => {
        if (event instanceof MessageEvent) {
          try {
            const data = JSON.parse(event.data)
            const error = data.error || 'An error occurred'
            
            // Check if this is a configuration error
            if (error.includes('OpenAI is not configured') || error.includes('not configured')) {
              errorDialog.value = {
                title: 'Configuration Error',
                message: error,
              }
            } else {
              errorDialog.value = {
                title: 'Error',
                message: error,
              }
            }
            showErrorDialog.value = true
          } catch {
            errorDialog.value = {
              title: 'Error',
              message: 'Received an invalid error response from the server.',
            }
            showErrorDialog.value = true
          }
        } else {
          errorDialog.value = {
            title: 'Connection Error',
            message: 'Failed to connect to the server. Please check that the server is running.',
          }
          showErrorDialog.value = true
        }
        isLoading.value = false
        eventSource.close()
        activeEventSource = null
      })

      eventSource.onerror = () => {
        // After a successful 'complete' event the handler calls
        // eventSource.close(), which sets readyState to CLOSED.
        // In that case the error is just the browser noticing the
        // connection went away — nothing to report.
        if (isComplete.value) {
          return
        }
        errorDialog.value = {
          title: 'Connection Lost',
          message: 'Connection to server lost. Please try again.',
        }
        showErrorDialog.value = true
        isLoading.value = false
        eventSource.close()
        activeEventSource = null
      }
    } catch (error) {
      errorDialog.value = {
        title: 'Error',
        message: error instanceof Error ? error.message : 'An error occurred',
      }
      showErrorDialog.value = true
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
    screenshots,
    cookies,
    scripts,
    scriptGroups,
    localStorage,
    sessionStorage,
    activeTab,
    analysisResult,
    structuredReport,
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
    debugLog,

    // Computed
    scriptsByDomain,
    cookiesByDomain,
    filteredNetworkRequests,
    networkByDomain,

    // Methods
    openScreenshotModal,
    closeScreenshotModal,
    closeScoreDialog: () => { showScoreDialog.value = false },
    closePageErrorDialog: () => { showPageErrorDialog.value = false },
    closeErrorDialog: () => { showErrorDialog.value = false },
    analyzeUrl,
  }
}
