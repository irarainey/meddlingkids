// Service layer exports

export { getOpenAIClient, getDeploymentName } from './openai.js'
export { detectCookieConsent } from './consent-detection.js'
export { extractConsentDetails } from './consent-extraction.js'
export { tryClickConsentButton } from './consent-click.js'
export { runTrackingAnalysis } from './analysis.js'
export {
  getBrowser,
  getContext,
  getPage,
  getPageUrl,
  getTrackedCookies,
  getTrackedScripts,
  getTrackedNetworkRequests,
  clearTrackingData,
  setPageUrl,
  launchBrowser,
  navigateTo,
  closeBrowser,
  captureCurrentCookies,
  captureStorage,
  takeScreenshot,
  getPageContent,
  waitForTimeout,
  waitForLoadState,
  clickAt,
  clickSelector,
  fillText,
} from './browser.js'
