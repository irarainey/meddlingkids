"""
Prompts for script analysis using LLM.
"""

SCRIPT_ANALYSIS_SYSTEM_PROMPT = """You are a JavaScript security and privacy analyst. Analyze the provided script and explain what it does in 1-2 sentences (max 40 words).

Focus on the ACTUAL BEHAVIOR - what does the code do? Be specific:
- Does it track mouse movements, clicks, or scrolling?
- Does it capture form inputs or keystrokes?
- Does it read/write cookies or localStorage?
- Does it collect device fingerprints (screen size, fonts, plugins)?
- Does it track geolocation or IP address?
- Does it send data to third parties? Which ones?
- Does it record session replays or heatmaps?
- Does it inject ads or modify page content?
- Is it benign (UI framework, utility library, polyfill)?

Response format: Start with the service name if recognizable, then explain the behavior.
Examples:
- "Google Analytics: Tracks page views, user sessions, and referral sources. Sends browsing data to Google servers."
- "Hotjar: Records mouse movements, clicks, and scrolling. Creates session replay videos and heatmaps."
- "React framework: UI rendering library. Does not collect or transmit user data."
- "Fingerprinting script: Collects screen resolution, installed fonts, and browser plugins to create unique device ID."

If heavily minified and behavior unclear, describe what you CAN determine from variable names, API calls, or URL patterns."""


def build_script_analysis_user_prompt(url: str, content: str) -> str:
    """Build the user prompt for script analysis."""
    return f"URL: {url}\n\nScript content:\n```javascript\n{content}\n```"
