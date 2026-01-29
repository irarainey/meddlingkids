// Prompt exports

export { CONSENT_DETECTION_SYSTEM_PROMPT, buildConsentDetectionUserPrompt } from './consent-detection.js'
export { CONSENT_EXTRACTION_SYSTEM_PROMPT, buildConsentExtractionUserPrompt } from './consent-extraction.js'
export {
  TRACKING_ANALYSIS_SYSTEM_PROMPT,
  SUMMARY_FINDINGS_SYSTEM_PROMPT,
  buildTrackingAnalysisUserPrompt,
  buildSummaryFindingsUserPrompt,
} from './tracking-analysis.js'
// Note: script-analysis.ts exports are not re-exported here as the script analysis
// service uses its own inline batch prompts for efficiency
