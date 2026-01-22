/**
 * @fileoverview Consent extraction prompt for detailed consent information.
 * Instructs the LLM to extract cookie categories, partners, and purposes.
 */

/**
 * System prompt for extracting detailed consent information.
 * Guides the LLM to analyze consent dialogs and extract structured data.
 */
export const CONSENT_EXTRACTION_SYSTEM_PROMPT = `You are an expert at analyzing cookie consent dialogs and extracting detailed information about tracking and data collection.

Your task is to extract ALL information about:
1. Cookie categories (necessary, functional, analytics, advertising, etc.)
2. Third-party partners/vendors and what they do
3. What data is being collected
4. Purposes of data collection
5. Any retention periods mentioned

Also identify if there's a "Manage Preferences", "Cookie Settings", "More Options", or similar button that reveals more details.

Return a JSON object with this exact structure:
{
  "hasManageOptions": boolean,
  "manageOptionsSelector": "CSS selector for manage/settings button" or null,
  "categories": [
    { "name": "Category Name", "description": "What this category does", "required": boolean }
  ],
  "partners": [
    { "name": "Partner Name", "purpose": "What they do", "dataCollected": ["data type 1", "data type 2"] }
  ],
  "purposes": ["purpose 1", "purpose 2"],
  "rawText": "Key excerpts from the consent text that users should know about"
}

Extract as much detail as possible. If you see a long list of partners, include them all.
IMPORTANT: Return ONLY the JSON object, no other text.`

/**
 * Build the user prompt for consent details extraction.
 * Includes extracted text from consent-related DOM elements.
 *
 * @param consentText - Text content extracted from consent dialog elements
 * @returns User prompt with consent text context
 */
export function buildConsentExtractionUserPrompt(consentText: string): string {
  return `Analyze this cookie consent dialog screenshot and extracted text to find ALL information about tracking, partners, and data collection.

Extracted text from consent elements:
${consentText}

Return a detailed JSON object with categories, partners, purposes, and any manage options button.`
}
