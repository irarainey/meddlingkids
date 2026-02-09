"""
Consent extraction prompt for detailed consent information.
Instructs the LLM to extract cookie categories, partners, and purposes.
"""

CONSENT_EXTRACTION_SYSTEM_PROMPT = """You are an expert at analyzing cookie consent dialogs and extracting detailed information about tracking and data collection.

Your task is to extract ALL information about:
1. Cookie categories (necessary, functional, analytics, advertising, etc.)
2. Third-party partners/vendors and what they do - EXTRACT ALL PARTNERS, even if there are hundreds
3. What data is being collected
4. Purposes of data collection
5. Any retention periods mentioned

IMPORTANT INSTRUCTIONS FOR PARTNERS:
- Look for "View Partners", "Show Vendors", "IAB Vendors", or similar expandable sections
- Many consent dialogs hide the full partner list behind a button - look for this in the HTML
- TCF (Transparency & Consent Framework) dialogs often have 100+ partners - include them ALL
- If you see text like "We and our 842 partners" or similar, there is a partner list somewhere
- Partner lists may be in tables, lists, or accordion/expandable sections
- Include EVERY partner name you can find, even if the list is very long

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

Extract as much detail as possible. If you see a long list of partners, include them all - this is critical for privacy analysis.
IMPORTANT: Return ONLY the JSON object, no other text."""


def build_consent_extraction_user_prompt(consent_text: str) -> str:
    """
    Build the user prompt for consent details extraction.
    Includes extracted text from consent-related DOM elements.
    """
    return (
        "Analyze this cookie consent dialog screenshot and extracted text to find ALL "
        "information about tracking, partners, and data collection.\n\n"
        f"Extracted text from consent elements:\n{consent_text}\n\n"
        "Return a detailed JSON object with categories, partners, purposes, and any manage options button."
    )
