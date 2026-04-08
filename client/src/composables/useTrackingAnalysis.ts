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
  DecodedCookies,
  ScreenshotModal,
  TabId,
  SummaryFinding,
  ScriptGroup,
  PageError,
  ErrorDialogState,
  StructuredReport,
} from '../types'
import { API_BASE } from '../utils/api'
import { useSSEConnection } from './useSSEConnection'

/**
 * Composable that provides all state and methods for tracking analysis.
 * Handles SSE connection, data collection, and computed groupings.
 */
export function useTrackingAnalysis() {
  // ============================================================================
  // Constants
  // ============================================================================

  /**
   * Contextual messages cycled during the AI analysis phase (76–95%)
   * to keep the UI feeling responsive while concurrent LLM calls
   * are in flight.
   */
  const ANALYSIS_MESSAGES = [
    'Analyzing tracking patterns...',
    'Examining cookie behavior...',
    'Reviewing network activity...',
    'Inspecting third-party scripts...',
    'Evaluating privacy practices...',
    'Cross-referencing tracker databases...',
    'Assessing data collection scope...',
    'Building privacy risk profile...',
    'Correlating tracker behaviors...',
    'Reviewing consent mechanisms...',
  ] as const

  /** Interval between rotating analysis messages (ms). */
  const ANALYSIS_ROTATE_INTERVAL_MS = 3500

  // ============================================================================
  // State
  // ============================================================================

  /** URL input field value */
  const inputValue = ref('')
  /** Selected device/browser type */
  const deviceType = ref('ipad')
  /** Whether to clear all server caches before analysis (read from ?clear-cache=true in the page URL) */
  const clearCache = new URLSearchParams(window.location.search).get('clear-cache') === 'true'

  // Immediately clear server caches when the page loads with ?clear-cache=true
  if (clearCache) {
    fetch(`${API_BASE}/api/clear-cache`, { method: 'POST' })
      .then(res => res.json())
      .then(data => console.warn('[CacheClear] Server caches cleared:', data))
      .catch(err => console.warn('[CacheClear] Failed to clear caches:', err))
  }

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
  const activeTab = ref<TabId>('summary')

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
  /** Decoded privacy cookies (USP, GPP, GA, Facebook, etc.) */
  const decodedCookies = ref<DecodedCookies | null>(null)
  
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

  /** Timer handle for the rotating analysis-phase messages. */
  let analysisRotateTimer: ReturnType<typeof setTimeout> | null = null
  /** Index into ANALYSIS_MESSAGES for the next rotation. */
  let analysisMessageIndex = 0

  /**
   * Schedule the next rotating message after ANALYSIS_ROTATE_INTERVAL_MS.
   * Only fires while progress is in the analysis phase (76–94%).
   */
  function scheduleAnalysisRotation(): void {
    analysisRotateTimer = setTimeout(() => {
      if (progressPercent.value >= 76 && progressPercent.value < 95) {
        statusMessage.value =
          ANALYSIS_MESSAGES[analysisMessageIndex % ANALYSIS_MESSAGES.length] ?? 'Analyzing...'
        analysisMessageIndex++
        scheduleAnalysisRotation()
      }
    }, ANALYSIS_ROTATE_INTERVAL_MS)
  }

  /** Cancel any pending rotation timer. */
  function clearAnalysisRotation(): void {
    if (analysisRotateTimer !== null) {
      clearTimeout(analysisRotateTimer)
      analysisRotateTimer = null
    }
  }

  // Clean up rotation timers when the composable's owner component unmounts.
  // The SSE connection cleanup is handled by useSSEConnection's own onUnmounted.
  onUnmounted(() => {
    clearAnalysisRotation()
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

  /**
   * Count of unique domain-to-domain connections for the Graph tab badge.
   * Mirrors the edge-building logic in TrackerGraphTab so the badge is zero
   * when the graph has nothing to display.
   */
  const graphConnectionCount = computed(() => {
    let origin: string
    try {
      origin = new URL(inputValue.value).hostname
    } catch {
      origin = 'origin'
    }
    const edges = new Set<string>()
    for (const req of networkRequests.value) {
      const target = req.domain
      if (!target || target === 'unknown') continue
      const source = req.initiatorDomain && req.initiatorDomain !== 'unknown'
        ? req.initiatorDomain
        : origin
      if (source === target) continue
      edges.add(`${source}>>>${target}`)
    }
    return edges.size
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
    structuredReport.value = null
    analysisError.value = ''
    summaryFindings.value = []
    privacyScore.value = null
    privacySummary.value = ''
    showScoreDialog.value = false
    consentDetails.value = null
    decodedCookies.value = null
    pageError.value = null
    showPageErrorDialog.value = false
    errorDialog.value = null
    showErrorDialog.value = false
    statusMessage.value = 'Initializing...'
    progressStep.value = 'init'
    progressPercent.value = 0
    clearAnalysisRotation()
    analysisMessageIndex = 0
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

    // Validate URL format
    try {
      const parsed = new URL(url)
      if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !/\./.test(parsed.hostname)) {
        throw new Error('invalid')
      }
    } catch {
      errorDialog.value = {
        title: 'Invalid URL',
        message: 'Please enter a valid URL, e.g. example.com or https://example.com',
      }
      showErrorDialog.value = true
      return
    }

    resetState()

    try {
      // Use relative URL — Vite proxies /api to the Python server in
      // development; production serves both client and API on the same
      // origin.  VITE_API_URL is only needed for manual overrides.
      const sseUrl =
        `${API_BASE}/api/open-browser-stream?url=${encodeURIComponent(url)}&device=${encodeURIComponent(deviceType.value)}${clearCache ? '&clear-cache=true' : ''}`

      // Safety-net timeout — if the server never sends the first
      // event (e.g. it isn't running, or a proxy is buffering the
      // SSE stream), surface an error instead of waiting forever.
      let connectionTimeout: ReturnType<typeof setTimeout> | null = setTimeout(() => {
        if (!statusMessage.value && isLoading.value) {
          errorDialog.value = {
            title: 'Connection Timeout',
            message: 'No response from the server. Check that the Python server is running on port 3001.',
          }
          showErrorDialog.value = true
          isLoading.value = false
          sseConnection.close()
        }
      }, 15_000)

      // Safety-net timeout — if the server sends the progress
      // "complete" event (100%) but the subsequent 'complete' SSE
      // event never arrives (e.g. payload too large, proxy drop),
      // surface an error instead of leaving the UI stuck.
      let completionTimeout: ReturnType<typeof setTimeout> | null = null

      // Tracks whether the server already sent a specific error
      // via the SSE 'error' event.  When it did, the native
      // onerror (which fires when the stream subsequently closes)
      // must not overwrite the more specific message.
      let hasServerError = false

      // Tracks whether the 'complete' event has been received.
      // isComplete is set inside a setTimeout, so this local flag
      // guards the onerror handler during the animation delay.
      let hasCompleted = false

      const sseConnection = useSSEConnection(sseUrl, {
        progress(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (connectionTimeout) {
            clearTimeout(connectionTimeout)
            connectionTimeout = null
          }
          // Only advance — never allow the progress bar or status
          // message to go backward.  The server emits progress
          // values from multiple concurrent pipeline stages that
          // may arrive out of order (e.g. script analysis at 84%
          // interleaved with report generation at 91%).
          if ((data.progress as number) >= progressPercent.value) {
            statusMessage.value = data.message as string
            progressStep.value = data.step as string
            progressPercent.value = data.progress as number
          }

          // During the analysis phase (76–94%), schedule rotating
          // contextual messages so the UI stays dynamic while
          // concurrent LLM calls are in flight.
          if ((data.progress as number) >= 76 && (data.progress as number) < 95) {
            clearAnalysisRotation()
            scheduleAnalysisRotation()
          } else if ((data.progress as number) >= 95) {
            clearAnalysisRotation()
          }

          // When the server signals 100% progress, start a timer.
          // The actual 'complete' event (with the full payload)
          // should arrive within seconds.  If it doesn't, the
          // payload was likely too large or got dropped.
          if ((data.progress as number) >= 100 && !completionTimeout) {
            completionTimeout = setTimeout(() => {
              if (!hasCompleted && !isComplete.value) {
                console.error('[SSE] Completion timeout — complete event not received')
                errorDialog.value = {
                  title: 'Results Not Received',
                  message: 'The analysis completed on the server but the results could not be delivered. '
                    + 'This can happen on sites with very large amounts of tracking data. '
                    + 'Please try again.',
                }
                showErrorDialog.value = true
                isLoading.value = false
                sseConnection.close()
              }
            }, 15_000)
          }
        },

        screenshot(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (data.screenshot) {
            screenshots.value.push(data.screenshot as string)
          }
          cookies.value = (data.cookies as TrackedCookie[]) || []
          scripts.value = (data.scripts as TrackedScript[]) || []
          networkRequests.value = (data.networkRequests as NetworkRequest[]) || []
          localStorage.value = (data.localStorage as StorageItem[]) || []
          sessionStorage.value = (data.sessionStorage as StorageItem[]) || []
        },

        screenshotUpdate(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (data.screenshot && screenshots.value.length > 0) {
            screenshots.value[screenshots.value.length - 1] = data.screenshot as string
          }
        },

        pageError(_data: unknown) {
          const data = _data as Record<string, unknown>
          pageError.value = {
            type: data.isAccessDenied ? 'access-denied' : data.isOverlayBlocked ? 'overlay-blocked' : 'server-error',
            message: (data.message as string) || 'Failed to load page',
            statusCode: (data.statusCode as number | undefined) ?? null,
          }
          showPageErrorDialog.value = true
          isLoading.value = false
          sseConnection.close()
        },

        consentDetails(_data: unknown) {
          consentDetails.value = _data as ConsentDetails
        },

        decodedCookies(_data: unknown) {
          decodedCookies.value = _data as DecodedCookies
        },

        // ── Multi-part completion events ──────────────────────
        // The server splits the final payload across several SSE
        // events to keep each well under browser/proxy size limits.
        completeTracking(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (data.cookies) {
            cookies.value = data.cookies as TrackedCookie[]
          }
          if (data.networkRequests) {
            networkRequests.value = data.networkRequests as NetworkRequest[]
          }
          if (data.localStorage) {
            localStorage.value = data.localStorage as StorageItem[]
          }
          if (data.sessionStorage) {
            sessionStorage.value = data.sessionStorage as StorageItem[]
          }
        },

        completeScripts(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (data.scripts) {
            scripts.value = data.scripts as TrackedScript[]
          }
          if (data.scriptGroups) {
            scriptGroups.value = data.scriptGroups as ScriptGroup[]
          }
        },

        complete(_data: unknown) {
          const data = _data as Record<string, unknown>
          if (connectionTimeout) {
            clearTimeout(connectionTimeout)
            connectionTimeout = null
          }
          if (completionTimeout) {
            clearTimeout(completionTimeout)
            completionTimeout = null
          }

          if (data.summaryFindings) {
            summaryFindings.value = data.summaryFindings as SummaryFinding[]
          }
          if (data.privacyScore !== null && data.privacyScore !== undefined) {
            privacyScore.value = data.privacyScore as number
            privacySummary.value = (data.privacySummary as string) || ''
          }
          if (data.structuredReport) {
            structuredReport.value = data.structuredReport as StructuredReport
          }
          if (data.analysisError) {
            analysisError.value = data.analysisError as string
          }
          if (data.consentDetails) {
            consentDetails.value = data.consentDetails as ConsentDetails
          }
          if (data.decodedCookies) {
            decodedCookies.value = data.decodedCookies as DecodedCookies
          }

          activeTab.value = 'summary'
          statusMessage.value = data.message as string
          progressPercent.value = 100
          hasCompleted = true
          clearAnalysisRotation()
          
          // Wait for the van animation to complete (500ms CSS transition + buffer)
          // before hiding progress, showing tabs, and opening the score dialog.
          setTimeout(() => {
            isLoading.value = false
            isComplete.value = true
            if (data.privacyScore !== null && data.privacyScore !== undefined) {
              showScoreDialog.value = true
            }
          }, 700)
          sseConnection.close()
        },

        error(_data: unknown) {
          if (connectionTimeout) {
            clearTimeout(connectionTimeout)
            connectionTimeout = null
          }
          if (completionTimeout) {
            clearTimeout(completionTimeout)
            completionTimeout = null
          }
          hasServerError = true

          // The SSE 'error' event may carry a MessageEvent with JSON
          // data from the server, or a plain Event on connection loss.
          // useSSEConnection tries JSON.parse first; if that fails for
          // the 'error' event type it forwards the raw MessageEvent.
          if (_data instanceof MessageEvent) {
            try {
              const data = JSON.parse(_data.data)
              const error = data.error || 'An error occurred'

              let title = 'Error'
              if (error.includes('OpenAI is not configured') || error.includes('not configured')) {
                title = 'Configuration Error'
              } else if (error.includes('timed out')) {
                title = 'Analysis Timed Out'
              } else if (error.includes('failed to start') || error.includes('display server')) {
                title = 'Browser Error'
              }

              errorDialog.value = { title, message: error }
              showErrorDialog.value = true
            } catch {
              errorDialog.value = {
                title: 'Error',
                message: 'Received an invalid error response from the server.',
              }
              showErrorDialog.value = true
            }
          } else if (typeof _data === 'object' && _data !== null && 'error' in (_data as Record<string, unknown>)) {
            const data = _data as Record<string, unknown>
            const error = (data.error as string) || 'An error occurred'

            let title = 'Error'
            if (error.includes('OpenAI is not configured') || error.includes('not configured')) {
              title = 'Configuration Error'
            } else if (error.includes('timed out')) {
              title = 'Analysis Timed Out'
            } else if (error.includes('failed to start') || error.includes('display server')) {
              title = 'Browser Error'
            }

            errorDialog.value = { title, message: error }
            showErrorDialog.value = true
          } else {
            errorDialog.value = {
              title: 'Connection Error',
              message: 'Failed to connect to the server. Please check that the server is running.',
            }
            showErrorDialog.value = true
          }
          isLoading.value = false
          sseConnection.close()
        },

        __onerror() {
          if (connectionTimeout) {
            clearTimeout(connectionTimeout)
            connectionTimeout = null
          }
          clearAnalysisRotation()
          if (completionTimeout) {
            clearTimeout(completionTimeout)
            completionTimeout = null
          }
          // After a successful 'complete' event the handler calls
          // sseConnection.close(), which sets readyState to CLOSED.
          if (isComplete.value || hasCompleted) {
            return
          }

          // If the server already sent a specific error message via
          // the SSE 'error' event, the stream closing is expected.
          if (hasServerError) {
            return
          }

          // Build a contextual message based on how far analysis
          // progressed before the connection dropped.
          const step = progressStep.value
          let message: string
          if (!step || step === 'init') {
            message = 'The server connection was lost before analysis could begin. '
              + 'Please check the server is running and try again.'
          } else if (step === 'browser' || step === 'navigate') {
            message = 'The connection was lost while launching the browser. '
              + 'The browser process may have crashed — please try again.'
          } else if (step === 'wait-network' || step === 'wait-content') {
            message = 'The connection was lost while loading the page. '
              + 'The target site may be unresponsive — please try again.'
          } else if (step === 'overlay-detect' || step === 'overlay-dismiss') {
            message = 'The connection was lost while handling cookie consent. '
              + 'Please try again.'
          } else if (step === 'analysis-start') {
            message = 'The connection was lost during AI analysis. '
              + 'This may indicate a timeout — please try again.'
          } else {
            message = 'The server connection was lost unexpectedly. '
              + 'Please try again.'
          }

          errorDialog.value = {
            title: 'Connection Lost',
            message,
          }
          showErrorDialog.value = true
          isLoading.value = false
          sseConnection.close()
        },
      })

      sseConnection.connect()
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
    networkRequests,
    activeTab,
    structuredReport,
    analysisError,
    summaryFindings,
    privacyScore,
    privacySummary,
    showScoreDialog,
    consentDetails,
    decodedCookies,
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
    closeScoreDialog: () => { showScoreDialog.value = false },
    closePageErrorDialog: () => { showPageErrorDialog.value = false },
    closeErrorDialog: () => { showErrorDialog.value = false },
    analyzeUrl,
  }
}
