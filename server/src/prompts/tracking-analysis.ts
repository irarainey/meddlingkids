/**
 * @fileoverview Tracking analysis prompts for privacy risk assessment.
 * Contains system prompts and user prompt builders for LLM-based analysis.
 */

import type { ConsentDetails, TrackingSummary } from '../types.js'

/**
 * System prompt for comprehensive tracking analysis.
 * Instructs the LLM to analyze tracking data and produce a detailed privacy report.
 */
export const TRACKING_ANALYSIS_SYSTEM_PROMPT = `You are a privacy and web tracking expert analyst. Your task is to analyze tracking data collected from a website and provide comprehensive insights about:

1. **Tracking Technologies Identified**: Identify known tracking services (Google Analytics, Facebook Pixel, advertising networks, etc.) based on cookie names, script URLs, and network requests.

2. **Data Collection Analysis**: What types of data are likely being collected (browsing behavior, user identification, cross-site tracking, etc.)

3. **Third-Party Services**: List each third-party domain found and explain what company/service it belongs to and what they typically track.

4. **Privacy Risk Assessment**: Rate the privacy risk level (Low/Medium/High/Very High) and explain why.

5. **Cookie Analysis**: Analyze cookie purposes - which are functional, which are for tracking, and their persistence.

6. **Storage Analysis**: Analyze localStorage/sessionStorage usage and what data might be persisted.

7. **Consent Dialog Analysis**: If consent information is provided, analyze what the website disclosed about tracking and compare it to what was actually detected. Highlight any discrepancies or concerning practices.

8. **Partner/Vendor Analysis**: If partner information is provided, explain what each partner does, what data they collect, and the privacy implications.

9. **Recommendations**: What users can do to protect their privacy on this site.

Format your response in clear sections with markdown headings. Be specific about which domains and cookies you're referring to. If you recognize specific tracking technologies, name them explicitly.

IMPORTANT: Pay special attention to the consent dialog information if provided - this is what users typically don't read but agree to. Highlight the most concerning aspects.`

/**
 * System prompt for generating high-risks summary.
 * Produces a brief, alarming bullet-point summary of privacy concerns.
 */
export const HIGH_RISKS_SYSTEM_PROMPT = `You are a privacy expert. Create a brief, alarming summary of the highest privacy risks found on a website. 
Be direct and impactful - this is what users need to know immediately.

Format as a SHORT bulleted list (max 5-7 points) with:
- 🚨 for critical risks (cross-site tracking, fingerprinting, data selling)
- ⚠️ for high risks (persistent tracking, third-party data sharing)
- 📊 for concerning findings (analytics, ad tracking)

Keep each point to ONE sentence. Be specific about company names and what they do.
End with an overall privacy risk rating: 🔴 High Risk, 🟠 Medium Risk, or 🟢 Low Risk.`

/**
 * System prompt for generating a privacy risk score.
 * Produces a numerical score and brief summary for the results dialog.
 */
export const PRIVACY_SCORE_SYSTEM_PROMPT = `You are a privacy expert. Based on a tracking analysis, provide a privacy risk score from 0-100 and a one-sentence summary.

Scoring guidelines:
- 80-100: Critical risk - extensive cross-site tracking, fingerprinting, data selling to many partners, deceptive practices
- 60-79: High risk - significant third-party tracking, multiple advertising networks, questionable data sharing
- 40-59: Moderate risk - standard analytics, some third-party trackers, typical advertising
- 20-39: Low risk - minimal tracking, basic analytics only, few third parties
- 0-19: Very low risk - privacy-respecting, minimal or no tracking, first-party only

IMPORTANT: The summary MUST start with the site name (e.g., "BBC.com has...", "Amazon.co.uk uses...").

You MUST respond with ONLY valid JSON in this exact format, no other text:
{"score": <number 0-100>, "summary": "<site name> <one sentence about key findings>"}`

/**
 * Build the consent information section for the analysis prompt.
 * Formats cookie categories, partners, and purposes into readable markdown.
 *
 * @param consentDetails - Extracted consent dialog information
 * @returns Formatted markdown section for inclusion in the analysis prompt
 */
function buildConsentSection(consentDetails: ConsentDetails): string {
  return `

## Cookie Consent Dialog Information (What Users Agreed To)

### Cookie Categories Disclosed
${
  consentDetails.categories.length > 0
    ? consentDetails.categories
        .map((c) => `- **${c.name}** (${c.required ? 'Required' : 'Optional'}): ${c.description}`)
        .join('\n')
    : 'No categories found'
}

### Partners/Vendors Listed (${consentDetails.partners.length} found)
${
  consentDetails.partners.length > 0
    ? consentDetails.partners
        .map(
          (p) =>
            `- **${p.name}**: ${p.purpose}${p.dataCollected.length > 0 ? ` | Data: ${p.dataCollected.join(', ')}` : ''}`
        )
        .join('\n')
    : 'No partners listed'
}

### Stated Purposes
${consentDetails.purposes.length > 0 ? consentDetails.purposes.map((p) => `- ${p}`).join('\n') : 'No specific purposes listed'}

### Raw Consent Text Excerpts
${consentDetails.rawText.substring(0, 3000)}
`
}

/**
 * Build the user prompt for tracking analysis.
 * Combines tracking summary data with optional consent details.
 *
 * @param trackingSummary - Aggregated tracking data from the page
 * @param consentDetails - Optional consent dialog information
 * @returns Complete user prompt for the LLM
 */
export function buildTrackingAnalysisUserPrompt(
  trackingSummary: TrackingSummary,
  consentDetails?: ConsentDetails | null
): string {
  const consentSection =
    consentDetails && (consentDetails.categories.length > 0 || consentDetails.partners.length > 0)
      ? buildConsentSection(consentDetails)
      : ''

  return `Analyze the following tracking data collected from: ${trackingSummary.analyzedUrl}

## Summary
- Total Cookies: ${trackingSummary.totalCookies}
- Total Scripts: ${trackingSummary.totalScripts}
- Total Network Requests: ${trackingSummary.totalNetworkRequests}
- LocalStorage Items: ${trackingSummary.localStorageItems}
- SessionStorage Items: ${trackingSummary.sessionStorageItems}
- Third-Party Domains: ${trackingSummary.thirdPartyDomains.length}

## Third-Party Domains Detected
${trackingSummary.thirdPartyDomains.join('\n')}

## Domain Breakdown
${JSON.stringify(trackingSummary.domainBreakdown, null, 2)}

## LocalStorage Data
${JSON.stringify(trackingSummary.localStorage, null, 2)}

## SessionStorage Data
${JSON.stringify(trackingSummary.sessionStorage, null, 2)}
${consentSection}

Please provide a comprehensive privacy analysis of this tracking data. If consent dialog information is provided, compare what was disclosed to users vs what is actually happening, and highlight any concerning discrepancies.`
}

/**
 * Build the user prompt for high-risks summary generation.
 * Takes the full analysis and requests a condensed summary.
 *
 * @param analysis - The full analysis text from the main LLM call
 * @returns User prompt asking for high-risks summary
 */
export function buildHighRisksUserPrompt(analysis: string): string {
  return `Based on this full analysis, create a brief high-risks summary:\n\n${analysis}`
}

/**
 * Build the user prompt for privacy score generation.
 * Takes the full analysis and requests a numerical score with summary.
 *
 * @param analysis - The full analysis text from the main LLM call
 * @param siteUrl - The URL of the analyzed site (for including in summary)
 * @returns User prompt asking for privacy score
 */
export function buildPrivacyScoreUserPrompt(analysis: string, siteUrl: string): string {
  let siteName: string
  try {
    siteName = new URL(siteUrl).hostname.replace(/^www\./, '').toLowerCase()
  } catch {
    siteName = siteUrl.toLowerCase()
  }
  return `Site analyzed: ${siteName}\n\nBased on this tracking analysis, provide a privacy risk score (0-100) and one-sentence summary that starts with the site name. Respond with JSON only:\n\n${analysis}`
}
