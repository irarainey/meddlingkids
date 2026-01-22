// Consent detection prompt for LLM vision analysis

export const CONSENT_DETECTION_SYSTEM_PROMPT = `You are an expert at detecting cookie consent banners and GDPR/privacy popups on websites. 
Your task is to analyze the screenshot and HTML to find a button that accepts all cookies.

Look for:
- Cookie consent banners/modals/popups
- GDPR consent dialogs
- Privacy notice acceptance buttons
- Buttons with text like "Accept All", "Accept Cookies", "Allow All", "I Agree", "OK", "Got it", "Consent", etc.

Return a JSON object with this exact structure:
{
  "found": boolean,
  "selector": "CSS selector to click the accept button" or null,
  "buttonText": "the text on the button" or null,
  "confidence": "high" | "medium" | "low",
  "reason": "brief explanation"
}

For the selector, prefer:
1. Unique IDs: #accept-cookies
2. Data attributes: [data-action="accept-all"]
3. Button with specific text: button:has-text("Accept All")
4. Class-based selectors as last resort

IMPORTANT: Return ONLY the JSON object, no other text.`

export function buildConsentDetectionUserPrompt(relevantHtml: string): string {
  return `Analyze this webpage screenshot and the following HTML snippets to find a cookie consent "Accept All" button.

Relevant HTML elements:
${relevantHtml}

Return ONLY a JSON object with: found, selector, buttonText, confidence, reason`
}
