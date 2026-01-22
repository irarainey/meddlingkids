import express from 'express'
import cors from 'cors'
import { chromium, type Browser, type Page, type BrowserContext } from 'playwright'
import { AzureOpenAI } from 'openai'
import 'dotenv/config'

const app = express()
const PORT = 3001

app.use(cors())
app.use(express.json({ limit: '50mb' }))

// Azure OpenAI client
let openaiClient: AzureOpenAI | null = null

function getOpenAIClient(): AzureOpenAI | null {
  if (openaiClient) return openaiClient
  
  const endpoint = process.env.AZURE_OPENAI_ENDPOINT
  const apiKey = process.env.AZURE_OPENAI_API_KEY
  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT
  
  if (!endpoint || !apiKey || !deployment) {
    console.warn('Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT in .env')
    return null
  }
  
  openaiClient = new AzureOpenAI({
    endpoint,
    apiKey,
    apiVersion: process.env.OPENAI_API_VERSION || '2024-12-01-preview',
    deployment,
  })
  
  return openaiClient
}

let browser: Browser | null = null
let context: BrowserContext | null = null
let page: Page | null = null
let pageUrl: string = ''

// Track cookies and JS sources
interface TrackedCookie {
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite: string
  timestamp: string
}

interface TrackedScript {
  url: string
  domain: string
  timestamp: string
}

interface StorageItem {
  key: string
  value: string
  timestamp: string
}

interface NetworkRequest {
  url: string
  domain: string
  method: string
  resourceType: string
  isThirdParty: boolean
  timestamp: string
}

const trackedCookies: TrackedCookie[] = []
const trackedScripts: TrackedScript[] = []
const trackedNetworkRequests: NetworkRequest[] = []

function extractDomain(url: string): string {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname
  } catch {
    return 'unknown'
  }
}

function isThirdParty(requestUrl: string, pageUrl: string): boolean {
  try {
    const requestDomain = extractDomain(requestUrl)
    const pageDomain = extractDomain(pageUrl)
    
    // Get base domain (e.g., bbc.co.uk from www.bbc.co.uk)
    const getBaseDomain = (domain: string) => {
      const parts = domain.split('.')
      // Handle common TLDs like co.uk, com.au, etc.
      if (parts.length > 2 && parts[parts.length - 2].length <= 3) {
        return parts.slice(-3).join('.')
      }
      return parts.slice(-2).join('.')
    }
    
    return getBaseDomain(requestDomain) !== getBaseDomain(pageDomain)
  } catch {
    return true
  }
}

// Cookie consent detection response interface
interface CookieConsentDetection {
  found: boolean
  selector: string | null
  buttonText: string | null
  confidence: 'high' | 'medium' | 'low'
  reason: string
}

// Detailed consent information extracted from cookie dialogs
interface ConsentDetails {
  hasManageOptions: boolean
  manageOptionsSelector: string | null
  categories: {
    name: string
    description: string
    required: boolean
  }[]
  partners: {
    name: string
    purpose: string
    dataCollected: string[]
  }[]
  purposes: string[]
  rawText: string
}

// Extract detailed consent information from a cookie preferences panel
async function extractConsentDetails(
  page: Page,
  screenshot: Buffer
): Promise<ConsentDetails> {
  const client = getOpenAIClient()
  if (!client) {
    return {
      hasManageOptions: false,
      manageOptionsSelector: null,
      categories: [],
      partners: [],
      purposes: [],
      rawText: '',
    }
  }

  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT!

  // Get all visible text from the page related to cookies/consent
  const consentText = await page.evaluate(() => {
    const selectors = [
      '[class*="cookie"]',
      '[class*="consent"]',
      '[class*="privacy"]',
      '[class*="gdpr"]',
      '[id*="cookie"]',
      '[id*="consent"]',
      '[role="dialog"]',
      '[class*="modal"]',
      '[class*="banner"]',
      '[class*="overlay"]',
    ]
    
    const elements: string[] = []
    for (const selector of selectors) {
      document.querySelectorAll(selector).forEach(el => {
        const text = (el as HTMLElement).innerText?.trim()
        if (text && text.length > 10 && text.length < 10000) {
          elements.push(text)
        }
      })
    }
    
    // Also get any tables that might list partners
    document.querySelectorAll('table').forEach(table => {
      const text = table.innerText?.trim()
      if (text && (text.toLowerCase().includes('partner') || 
                   text.toLowerCase().includes('vendor') ||
                   text.toLowerCase().includes('cookie') ||
                   text.toLowerCase().includes('purpose'))) {
        elements.push(text)
      }
    })
    
    return [...new Set(elements)].join('\n\n---\n\n').substring(0, 30000)
  })

  try {
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        {
          role: 'system',
          content: `You are an expert at analyzing cookie consent dialogs and extracting detailed information about tracking and data collection.

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
IMPORTANT: Return ONLY the JSON object, no other text.`,
        },
        {
          role: 'user',
          content: [
            {
              type: 'image_url',
              image_url: {
                url: `data:image/png;base64,${screenshot.toString('base64')}`,
              },
            },
            {
              type: 'text',
              text: `Analyze this cookie consent dialog screenshot and extracted text to find ALL information about tracking, partners, and data collection.

Extracted text from consent elements:
${consentText}

Return a detailed JSON object with categories, partners, purposes, and any manage options button.`,
            },
          ],
        },
      ],
      max_completion_tokens: 2000,
    })

    const content = response.choices[0]?.message?.content || '{}'
    
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }
    
    const result = JSON.parse(jsonStr) as ConsentDetails
    result.rawText = consentText.substring(0, 5000) // Keep raw text for analysis
    console.log('Extracted consent details:', {
      categories: result.categories.length,
      partners: result.partners.length,
      purposes: result.purposes.length,
    })
    return result
  } catch (error) {
    console.error('Consent details extraction error:', error)
    return {
      hasManageOptions: false,
      manageOptionsSelector: null,
      categories: [],
      partners: [],
      purposes: [],
      rawText: consentText.substring(0, 5000),
    }
  }
}

// Detect cookie consent banner using LLM vision
async function detectCookieConsent(
  screenshot: Buffer,
  html: string
): Promise<CookieConsentDetection> {
  const client = getOpenAIClient()
  if (!client) {
    return {
      found: false,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: 'Azure OpenAI not configured',
    }
  }

  const deployment = process.env.AZURE_OPENAI_DEPLOYMENT!
  
  // Extract only relevant HTML for cookie consent (much smaller payload)
  // Focus on buttons, dialogs, and consent-related elements
  const extractRelevantHtml = (fullHtml: string): string => {
    // Look for common cookie consent patterns in the HTML
    const patterns = [
      /<div[^>]*(?:cookie|consent|gdpr|privacy|banner|modal|popup|overlay)[^>]*>[\s\S]*?<\/div>/gi,
      /<button[^>]*>[\s\S]*?<\/button>/gi,
      /<a[^>]*(?:accept|agree|consent|allow)[^>]*>[\s\S]*?<\/a>/gi,
    ]
    
    const matches: string[] = []
    for (const pattern of patterns) {
      const found = fullHtml.match(pattern) || []
      matches.push(...found.slice(0, 10)) // Limit matches per pattern
    }
    
    const relevant = matches.join('\n').substring(0, 15000)
    return relevant || fullHtml.substring(0, 10000)
  }
  
  const relevantHtml = extractRelevantHtml(html)

  try {
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        {
          role: 'system',
          content: `You are an expert at detecting cookie consent banners and GDPR/privacy popups on websites. 
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

IMPORTANT: Return ONLY the JSON object, no other text.`,
        },
        {
          role: 'user',
          content: [
            {
              type: 'image_url',
              image_url: {
                url: `data:image/png;base64,${screenshot.toString('base64')}`,
              },
            },
            {
              type: 'text',
              text: `Analyze this webpage screenshot and the following HTML snippets to find a cookie consent "Accept All" button.

Relevant HTML elements:
${relevantHtml}

Return ONLY a JSON object with: found, selector, buttonText, confidence, reason`,
            },
          ],
        },
      ],
      max_completion_tokens: 500,
    })

    const content = response.choices[0]?.message?.content || '{}'
    
    // Parse JSON from response, handling potential markdown code blocks
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }
    
    const result = JSON.parse(jsonStr) as CookieConsentDetection
    console.log('Cookie consent detection result:', result)
    return result
  } catch (error) {
    console.error('Cookie consent detection error:', error)
    return {
      found: false,
      selector: null,
      buttonText: null,
      confidence: 'low',
      reason: `Detection failed: ${error instanceof Error ? error.message : 'Unknown error'}`,
    }
  }
}

// Helper function to try multiple click strategies for consent buttons
async function tryClickConsentButton(
  page: Page,
  selector: string | null,
  buttonText: string | null
): Promise<boolean> {
  const strategies: Array<{ name: string; fn: () => Promise<void> }> = []

  // Strategy 1: Direct selector click
  if (selector) {
    // Convert jQuery-style :contains() to Playwright text selector
    const containsMatch = selector.match(/:contains\(["'](.+?)["']\)/)
    if (containsMatch) {
      const text = containsMatch[1]
      strategies.push({
        name: `text selector "${text}"`,
        fn: () => page.getByText(text, { exact: false }).first().click({ timeout: 3000 }),
      })
    } else {
      strategies.push({
        name: `CSS selector "${selector}"`,
        fn: () => page.click(selector, { timeout: 3000 }),
      })
    }
  }

  // Strategy 2: Button role with text
  if (buttonText) {
    strategies.push({
      name: `button role "${buttonText}"`,
      fn: () => page.getByRole('button', { name: buttonText }).click({ timeout: 3000 }),
    })
    // Also try with exact: false for partial matches
    strategies.push({
      name: `button role partial "${buttonText}"`,
      fn: () => page.getByRole('button', { name: new RegExp(buttonText, 'i') }).first().click({ timeout: 3000 }),
    })
  }

  // Strategy 3: Common accept button patterns
  const commonPatterns = [
    'Accept All', 'Accept all', 'Accept Cookies', 'Accept cookies',
    'Allow All', 'Allow all', 'I Accept', 'I agree', 'Agree',
    'OK', 'Got it', 'Continue', 'Consent', 'Yes', 'Allow',
  ]
  for (const pattern of commonPatterns) {
    strategies.push({
      name: `common pattern "${pattern}"`,
      fn: () => page.getByRole('button', { name: pattern }).click({ timeout: 2000 }),
    })
  }

  // Strategy 4: Check iframes for consent banners
  strategies.push({
    name: 'iframe consent',
    fn: async () => {
      const frames = page.frames()
      for (const frame of frames) {
        if (frame === page.mainFrame()) continue
        const frameUrl = frame.url().toLowerCase()
        // Common consent iframe patterns
        if (frameUrl.includes('consent') || frameUrl.includes('cookie') || 
            frameUrl.includes('privacy') || frameUrl.includes('gdpr') ||
            frameUrl.includes('onetrust') || frameUrl.includes('cookiebot') ||
            frameUrl.includes('trustarc') || frameUrl.includes('quantcast')) {
          // Try clicking accept buttons in this frame
          for (const pattern of ['Accept All', 'Accept', 'Allow All', 'I Accept', 'Agree', 'OK']) {
            try {
              await frame.getByRole('button', { name: pattern }).click({ timeout: 2000 })
              return // Success
            } catch {
              // Try next pattern
            }
          }
        }
      }
      throw new Error('No consent iframe found')
    },
  })

  // Try each strategy in order
  for (const strategy of strategies) {
    try {
      console.log(`Trying consent click strategy: ${strategy.name}`)
      await strategy.fn()
      console.log(`Success with strategy: ${strategy.name}`)
      return true
    } catch (error) {
      console.log(`Strategy "${strategy.name}" failed:`, error instanceof Error ? error.message : error)
    }
  }

  return false
}

// Run the full tracking analysis
async function runTrackingAnalysis(
  cookies: TrackedCookie[],
  localStorage: StorageItem[],
  sessionStorage: StorageItem[],
  networkRequests: NetworkRequest[],
  scripts: TrackedScript[],
  analyzedUrl: string,
  consentDetails?: ConsentDetails | null
): Promise<{ success: boolean; analysis?: string; highRisks?: string; summary?: object; error?: string }> {
  const client = getOpenAIClient()
  if (!client) {
    return { success: false, error: 'Azure OpenAI not configured' }
  }

  try {
    // Group data by domain for analysis
    const domainData: Record<string, {
      cookies: TrackedCookie[],
      scripts: TrackedScript[],
      networkRequests: NetworkRequest[],
    }> = {}

    for (const cookie of cookies || []) {
      if (!domainData[cookie.domain]) {
        domainData[cookie.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[cookie.domain].cookies.push(cookie)
    }

    for (const script of scripts || []) {
      if (!domainData[script.domain]) {
        domainData[script.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[script.domain].scripts.push(script)
    }

    for (const request of networkRequests || []) {
      if (!domainData[request.domain]) {
        domainData[request.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[request.domain].networkRequests.push(request)
    }

    const trackingSummary = {
      analyzedUrl,
      totalCookies: cookies?.length || 0,
      totalScripts: scripts?.length || 0,
      totalNetworkRequests: networkRequests?.length || 0,
      localStorageItems: localStorage?.length || 0,
      sessionStorageItems: sessionStorage?.length || 0,
      thirdPartyDomains: Object.keys(domainData).filter(domain => {
        try {
          const pageBaseDomain = new URL(analyzedUrl).hostname.split('.').slice(-2).join('.')
          const domainBase = domain.split('.').slice(-2).join('.')
          return pageBaseDomain !== domainBase
        } catch {
          return true
        }
      }),
      domainBreakdown: Object.entries(domainData).map(([domain, data]) => ({
        domain,
        cookieCount: data.cookies.length,
        cookieNames: data.cookies.map(c => c.name),
        scriptCount: data.scripts.length,
        requestCount: data.networkRequests.length,
        requestTypes: [...new Set(data.networkRequests.map(r => r.resourceType))],
      })),
      localStorage: localStorage?.map((item: StorageItem) => ({ key: item.key, valuePreview: item.value.substring(0, 100) })) || [],
      sessionStorage: sessionStorage?.map((item: StorageItem) => ({ key: item.key, valuePreview: item.value.substring(0, 100) })) || [],
    }

    const systemPrompt = `You are a privacy and web tracking expert analyst. Your task is to analyze tracking data collected from a website and provide comprehensive insights about:

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

    // Build consent details section if available
    let consentSection = ''
    if (consentDetails && (consentDetails.categories.length > 0 || consentDetails.partners.length > 0)) {
      consentSection = `

## Cookie Consent Dialog Information (What Users Agreed To)

### Cookie Categories Disclosed
${consentDetails.categories.length > 0 
  ? consentDetails.categories.map(c => `- **${c.name}** (${c.required ? 'Required' : 'Optional'}): ${c.description}`).join('\n')
  : 'No categories found'}

### Partners/Vendors Listed (${consentDetails.partners.length} found)
${consentDetails.partners.length > 0 
  ? consentDetails.partners.map(p => `- **${p.name}**: ${p.purpose}${p.dataCollected.length > 0 ? ` | Data: ${p.dataCollected.join(', ')}` : ''}`).join('\n')
  : 'No partners listed'}

### Stated Purposes
${consentDetails.purposes.length > 0 
  ? consentDetails.purposes.map(p => `- ${p}`).join('\n')
  : 'No specific purposes listed'}

### Raw Consent Text Excerpts
${consentDetails.rawText.substring(0, 3000)}
`
    }

    const userPrompt = `Analyze the following tracking data collected from: ${analyzedUrl}

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

    const deployment = process.env.AZURE_OPENAI_DEPLOYMENT!
    
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt }
      ],
      max_completion_tokens: 3000,
    })

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'
    console.log('Analysis generated, length:', analysis.length)

    // Generate a concise high risks summary
    let highRisks = ''
    try {
      const highRisksResponse = await client.chat.completions.create({
        model: deployment,
        messages: [
          { 
            role: 'system', 
            content: `You are a privacy expert. Create a brief, alarming summary of the highest privacy risks found on a website. 
Be direct and impactful - this is what users need to know immediately.

Format as a SHORT bulleted list (max 5-7 points) with:
- 🚨 for critical risks (cross-site tracking, fingerprinting, data selling)
- ⚠️ for high risks (persistent tracking, third-party data sharing)
- 📊 for concerning findings (analytics, ad tracking)

Keep each point to ONE sentence. Be specific about company names and what they do.
End with an overall privacy risk rating: 🔴 High Risk, 🟠 Medium Risk, or 🟢 Low Risk.`
          },
          { 
            role: 'user', 
            content: `Based on this full analysis, create a brief high-risks summary:\n\n${analysis}`
          }
        ],
        max_completion_tokens: 500,
      })
      highRisks = highRisksResponse.choices[0]?.message?.content || ''
      console.log('High risks summary generated')
    } catch (highRisksError) {
      console.error('Failed to generate high risks summary:', highRisksError)
    }

    return {
      success: true,
      analysis,
      highRisks,
      summary: trackingSummary,
    }
  } catch (error) {
    console.error('Analysis error:', error)
    return { success: false, error: error instanceof Error ? error.message : 'Unknown error' }
  }
}

// Streaming endpoint for browser operations with progress updates
app.get('/api/open-browser-stream', async (req, res) => {
  const url = req.query.url as string

  if (!url) {
    res.status(400).json({ error: 'URL is required' })
    return
  }

  // Set up SSE headers
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.setHeader('Access-Control-Allow-Origin', '*')

  // Helper to send SSE events
  const sendEvent = (type: string, data: object) => {
    res.write(`event: ${type}\n`)
    res.write(`data: ${JSON.stringify(data)}\n\n`)
  }

  const sendProgress = (step: string, message: string, progress: number) => {
    sendEvent('progress', { step, message, progress })
  }

  try {
    sendProgress('init', '🚀 Starting browser...', 5)

    // Close existing browser if open
    if (browser) {
      await browser.close()
    }

    // Clear tracked data
    trackedCookies.length = 0
    trackedScripts.length = 0
    trackedNetworkRequests.length = 0
    pageUrl = url

    sendProgress('browser', '🌐 Launching headless browser...', 10)

    // Launch browser in headless mode
    browser = await chromium.launch({
      headless: true,
    })

    context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
    })

    page = await context.newPage()

    // Track all network requests
    page.on('request', (request) => {
      const resourceType = request.resourceType()
      const requestUrl = request.url()
      const domain = extractDomain(requestUrl)
      
      if (resourceType === 'script') {
        if (!trackedScripts.some(s => s.url === requestUrl)) {
          trackedScripts.push({
            url: requestUrl,
            domain,
            timestamp: new Date().toISOString(),
          })
        }
      }
      
      const networkRequest: NetworkRequest = {
        url: requestUrl,
        domain,
        method: request.method(),
        resourceType,
        isThirdParty: isThirdParty(requestUrl, pageUrl),
        timestamp: new Date().toISOString(),
      }
      
      if (!trackedNetworkRequests.some(r => r.url === requestUrl)) {
        trackedNetworkRequests.push(networkRequest)
      }
    })

    sendProgress('navigate', `📄 Loading ${new URL(url).hostname}...`, 20)

    await page.goto(url, { waitUntil: 'networkidle' })

    // Wait additional time for dynamic content (ads, trackers) to load
    sendProgress('wait-content', '⏳ Waiting for dynamic content to load...', 30)
    await page.waitForTimeout(3000)

    sendProgress('cookies', '🍪 Capturing initial cookies...', 35)

    await captureCurrentCookies()
    let storage = await captureStorage()

    sendProgress('screenshot', '📸 Taking initial screenshot...', 40)

    let screenshot = await page.screenshot({ type: 'png', fullPage: false })
    let base64Screenshot = screenshot.toString('base64')

    // Send initial screenshot (stage 1)
    sendEvent('screenshot', { 
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })

    sendProgress('consent-detect', '🔍 Analyzing page for cookie consent banner...', 45)

    const html = await page.content()
    const consentDetection = await detectCookieConsent(screenshot, html)

    let cookieConsentClicked = false
    let cookieConsentInfo: CookieConsentDetection | null = null
    let consentDetails: ConsentDetails | null = null

    if (consentDetection.found && consentDetection.selector) {
      sendProgress('consent-found', `✅ Cookie consent found: "${consentDetection.buttonText || 'Accept'}"`, 50)
      cookieConsentInfo = consentDetection

      // Extract detailed consent information BEFORE accepting
      sendProgress('consent-extract', '📋 Extracting partner and tracking details from consent dialog...', 55)
      consentDetails = await extractConsentDetails(page, screenshot)
      
      // Send consent details event
      sendEvent('consentDetails', {
        categories: consentDetails.categories,
        partners: consentDetails.partners,
        purposes: consentDetails.purposes,
        hasManageOptions: consentDetails.hasManageOptions,
      })

      // If there's a manage options button, try clicking it to get more details
      if (consentDetails.hasManageOptions && consentDetails.manageOptionsSelector) {
        sendProgress('consent-expand', '🔎 Expanding cookie preferences to find more details...', 58)
        try {
          // Convert jQuery-style :contains() selectors to Playwright text selectors
          let selector = consentDetails.manageOptionsSelector
          const containsMatch = selector.match(/:contains\(["'](.+?)["']\)/)
          
          if (containsMatch) {
            // Extract the text and use Playwright's text locator instead
            const buttonText = containsMatch[1]
            await page.getByRole('button', { name: buttonText }).first().click({ timeout: 3000 })
          } else {
            await page.click(selector, { timeout: 3000 })
          }
          await page.waitForTimeout(500)
          
          // Take new screenshot and extract more details
          const expandedScreenshot = await page.screenshot({ type: 'png', fullPage: true })
          const expandedDetails = await extractConsentDetails(page, expandedScreenshot)
          
          // Merge the details
          consentDetails = {
            ...consentDetails,
            categories: [...consentDetails.categories, ...expandedDetails.categories]
              .filter((c, i, arr) => arr.findIndex(x => x.name === c.name) === i),
            partners: [...consentDetails.partners, ...expandedDetails.partners]
              .filter((p, i, arr) => arr.findIndex(x => x.name === p.name) === i),
            purposes: [...new Set([...consentDetails.purposes, ...expandedDetails.purposes])],
            rawText: consentDetails.rawText + '\n\n' + expandedDetails.rawText,
          }
          
          // Send updated consent details
          sendEvent('consentDetails', {
            categories: consentDetails.categories,
            partners: consentDetails.partners,
            purposes: consentDetails.purposes,
            expanded: true,
          })
          
          console.log('Expanded consent details:', {
            categories: consentDetails.categories.length,
            partners: consentDetails.partners.length,
          })
        } catch (expandError) {
          console.log('Could not expand cookie preferences:', expandError)
        }
      }

      try {
        sendProgress('consent-click', '👆 Clicking accept button...', 62)
        
        // Try multiple click strategies
        cookieConsentClicked = await tryClickConsentButton(
          page,
          consentDetection.selector,
          consentDetection.buttonText
        )

        if (cookieConsentClicked) {
          sendProgress('consent-wait', '⏳ Waiting for page to update...', 70)
          await page.waitForTimeout(1000)
          await page.waitForLoadState('domcontentloaded').catch(() => {})

          sendProgress('recapture', '🔄 Recapturing tracking data...', 75)
          await captureCurrentCookies()
          storage = await captureStorage()
          screenshot = await page.screenshot({ type: 'png', fullPage: false })
          base64Screenshot = screenshot.toString('base64')

          // Send screenshot after consent (stage 2)
          sendEvent('screenshot', { 
            screenshot: `data:image/png;base64,${base64Screenshot}`,
            cookies: trackedCookies,
            scripts: trackedScripts,
            networkRequests: trackedNetworkRequests,
            localStorage: storage.localStorage,
            sessionStorage: storage.sessionStorage,
          })

          sendEvent('consent', {
            detected: true,
            clicked: true,
            details: cookieConsentInfo,
          })
        } else {
          console.log('All consent click strategies failed')
          sendEvent('consent', {
            detected: true,
            clicked: false,
            details: cookieConsentInfo,
            error: 'Failed to click consent button with all strategies',
          })
        }
      } catch (clickError) {
        console.error('Failed to click cookie consent:', clickError)
        sendEvent('consent', {
          detected: true,
          clicked: false,
          details: cookieConsentInfo,
          error: 'Failed to click consent button',
        })
      }
    } else {
      sendProgress('consent-none', 'ℹ️ No cookie consent banner detected', 70)
      sendEvent('consent', {
        detected: false,
        clicked: false,
        details: null,
        reason: consentDetection.reason,
      })
    }

    sendProgress('analysis', '🤖 Running AI privacy analysis...', 80)
    console.log('Starting tracking analysis...')

    const analysisResult = await runTrackingAnalysis(
      trackedCookies,
      storage.localStorage,
      storage.sessionStorage,
      trackedNetworkRequests,
      trackedScripts,
      url,
      consentDetails
    )

    console.log('Analysis result:', analysisResult.success ? 'Success' : analysisResult.error)
    sendProgress('complete', '✅ Analysis complete!', 100)

    // Send final complete event
    sendEvent('complete', {
      success: true,
      message: cookieConsentClicked 
        ? 'Browser opened, cookie consent accepted, and tracking analyzed' 
        : 'Browser opened and tracking analyzed',
      analysis: analysisResult.success ? analysisResult.analysis : null,
      highRisks: analysisResult.success ? analysisResult.highRisks : null,
      analysisSummary: analysisResult.success ? analysisResult.summary : null,
      analysisError: analysisResult.success ? null : analysisResult.error,
      consentDetails: consentDetails,
    })

    res.end()
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    sendEvent('error', { error: message })
    res.end()
  }
})

// Keep the original POST endpoint for backwards compatibility
app.post('/api/open-browser', async (req, res) => {
  const { url } = req.body

  if (!url) {
    res.status(400).json({ error: 'URL is required' })
    return
  }

  try {
    // Close existing browser if open
    if (browser) {
      await browser.close()
    }

    // Clear tracked data
    trackedCookies.length = 0
    trackedScripts.length = 0
    trackedNetworkRequests.length = 0
    pageUrl = url

    // Launch browser in headless mode
    browser = await chromium.launch({
      headless: true,
    })

    context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
    })

    page = await context.newPage()

    // Track all network requests
    page.on('request', (request) => {
      const resourceType = request.resourceType()
      const requestUrl = request.url()
      const domain = extractDomain(requestUrl)
      
      // Track scripts separately
      if (resourceType === 'script') {
        if (!trackedScripts.some(s => s.url === requestUrl)) {
          trackedScripts.push({
            url: requestUrl,
            domain,
            timestamp: new Date().toISOString(),
          })
        }
      }
      
      // Track all network requests (for third-party analysis)
      const networkRequest: NetworkRequest = {
        url: requestUrl,
        domain,
        method: request.method(),
        resourceType,
        isThirdParty: isThirdParty(requestUrl, pageUrl),
        timestamp: new Date().toISOString(),
      }
      
      // Avoid duplicate URLs
      if (!trackedNetworkRequests.some(r => r.url === requestUrl)) {
        trackedNetworkRequests.push(networkRequest)
      }
    })

    await page.goto(url, { waitUntil: 'networkidle' })

    // Capture initial cookies
    await captureCurrentCookies()

    // Capture storage
    let storage = await captureStorage()

    // Take initial screenshot
    let screenshot = await page.screenshot({ type: 'png', fullPage: true })
    let base64Screenshot = screenshot.toString('base64')

    // Get page HTML for cookie consent detection
    const html = await page.content()

    // Detect cookie consent banner
    console.log('Detecting cookie consent banner...')
    const consentDetection = await detectCookieConsent(screenshot, html)

    let cookieConsentClicked = false
    let cookieConsentInfo: CookieConsentDetection | null = null

    if (consentDetection.found && consentDetection.selector) {
      console.log(`Cookie consent found! Attempting to click: ${consentDetection.selector}`)
      cookieConsentInfo = consentDetection

      try {
        // Try to click the consent button
        await page.click(consentDetection.selector, { timeout: 5000 })
        cookieConsentClicked = true
        console.log('Cookie consent accepted!')

        // Wait for page to settle after accepting cookies
        await page.waitForTimeout(2000)
        await page.waitForLoadState('networkidle').catch(() => {})

        // Recapture everything after accepting cookies
        await captureCurrentCookies()
        storage = await captureStorage()
        screenshot = await page.screenshot({ type: 'png', fullPage: true })
        base64Screenshot = screenshot.toString('base64')
        
        console.log('Captured tracking data after cookie consent')
      } catch (clickError) {
        console.error('Failed to click cookie consent:', clickError)
        // Try alternative approach with buttonText
        if (consentDetection.buttonText) {
          try {
            await page.getByRole('button', { name: consentDetection.buttonText }).click({ timeout: 3000 })
            cookieConsentClicked = true
            console.log('Cookie consent accepted via button text!')

            await page.waitForTimeout(2000)
            await page.waitForLoadState('networkidle').catch(() => {})

            await captureCurrentCookies()
            storage = await captureStorage()
            screenshot = await page.screenshot({ type: 'png', fullPage: true })
            base64Screenshot = screenshot.toString('base64')
          } catch {
            console.error('Alternative click also failed')
          }
        }
      }
    } else {
      console.log('No cookie consent banner detected:', consentDetection.reason)
    }

    // Run automatic tracking analysis
    console.log('Running automatic tracking analysis...')
    const analysisResult = await runTrackingAnalysis(
      trackedCookies,
      storage.localStorage,
      storage.sessionStorage,
      trackedNetworkRequests,
      trackedScripts,
      url
    )

    res.json({
      success: true,
      message: cookieConsentClicked 
        ? `Browser opened, cookie consent accepted, and tracking analyzed` 
        : `Browser opened and tracking analyzed`,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
      cookieConsent: {
        detected: consentDetection.found,
        clicked: cookieConsentClicked,
        details: cookieConsentInfo,
      },
      analysis: analysisResult.success ? analysisResult.analysis : null,
      analysisSummary: analysisResult.success ? analysisResult.summary : null,
      analysisError: analysisResult.success ? null : analysisResult.error,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

async function captureCurrentCookies() {
  if (!context) return

  const cookies = await context.cookies()
  
  for (const cookie of cookies) {
    // Check if we already have this cookie (by name and domain)
    const existingIndex = trackedCookies.findIndex(
      c => c.name === cookie.name && c.domain === cookie.domain
    )
    
    const trackedCookie: TrackedCookie = {
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      expires: cookie.expires,
      httpOnly: cookie.httpOnly,
      secure: cookie.secure,
      sameSite: cookie.sameSite,
      timestamp: new Date().toISOString(),
    }

    if (existingIndex >= 0) {
      // Update existing cookie
      trackedCookies[existingIndex] = trackedCookie
    } else {
      // Add new cookie
      trackedCookies.push(trackedCookie)
    }
  }
}

async function captureStorage(): Promise<{ localStorage: StorageItem[], sessionStorage: StorageItem[] }> {
  if (!page) return { localStorage: [], sessionStorage: [] }

  try {
    const storageData = await page.evaluate(() => {
      const getStorageItems = (storage: Storage) => {
        const items: { key: string, value: string }[] = []
        for (let i = 0; i < storage.length; i++) {
          const key = storage.key(i)
          if (key) {
            items.push({ key, value: storage.getItem(key) || '' })
          }
        }
        return items
      }

      return {
        localStorage: getStorageItems(window.localStorage),
        sessionStorage: getStorageItems(window.sessionStorage),
      }
    })

    const timestamp = new Date().toISOString()
    
    return {
      localStorage: storageData.localStorage.map(item => ({ ...item, timestamp })),
      sessionStorage: storageData.sessionStorage.map(item => ({ ...item, timestamp })),
    }
  } catch {
    return { localStorage: [], sessionStorage: [] }
  }
}

// Click at specific coordinates
app.post('/api/click', async (req, res) => {
  const { x, y } = req.body

  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await page.mouse.click(x, y)
    await page.waitForTimeout(1000) // Wait for any animations/requests
    
    // Capture cookies after interaction
    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await page.screenshot({ type: 'png', fullPage: true })
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Click on element by selector
app.post('/api/click-selector', async (req, res) => {
  const { selector } = req.body

  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await page.click(selector, { timeout: 5000 })
    await page.waitForTimeout(1000)
    
    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await page.screenshot({ type: 'png', fullPage: true })
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Type text
app.post('/api/type', async (req, res) => {
  const { selector, text } = req.body

  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await page.fill(selector, text)
    
    const storage = await captureStorage()
    const screenshot = await page.screenshot({ type: 'png', fullPage: true })
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Get current state (screenshot, cookies, scripts)
app.get('/api/state', async (_req, res) => {
  if (!page) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await captureCurrentCookies()
    const storage = await captureStorage()

    const screenshot = await page.screenshot({ type: 'png', fullPage: true })
    const base64Screenshot = screenshot.toString('base64')

    res.json({
      success: true,
      screenshot: `data:image/png;base64,${base64Screenshot}`,
      cookies: trackedCookies,
      scripts: trackedScripts,
      networkRequests: trackedNetworkRequests,
      localStorage: storage.localStorage,
      sessionStorage: storage.sessionStorage,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Get only cookies
app.get('/api/cookies', async (_req, res) => {
  if (!context) {
    res.status(400).json({ error: 'No browser session active' })
    return
  }

  try {
    await captureCurrentCookies()
    res.json({ cookies: trackedCookies })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Get only scripts
app.get('/api/scripts', async (_req, res) => {
  res.json({ scripts: trackedScripts })
})

app.post('/api/close-browser', async (_req, res) => {
  try {
    if (browser) {
      await browser.close()
      browser = null
      context = null
      page = null
    }
    res.json({ success: true, message: 'Browser closed' })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: message })
  }
})

// Analyze tracking data with Azure OpenAI
app.post('/api/analyze', async (req, res) => {
  const { 
    cookies, 
    localStorage, 
    sessionStorage, 
    networkRequests, 
    scripts, 
    pageUrl: analyzedUrl 
  } = req.body as {
    cookies: TrackedCookie[]
    localStorage: StorageItem[]
    sessionStorage: StorageItem[]
    networkRequests: NetworkRequest[]
    scripts: TrackedScript[]
    pageUrl: string
  }

  const client = getOpenAIClient()
  if (!client) {
    res.status(503).json({ 
      error: 'Azure OpenAI not configured. Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT in .env file.' 
    })
    return
  }

  try {
    // Group data by domain for analysis
    const domainData: Record<string, {
      cookies: TrackedCookie[],
      scripts: TrackedScript[],
      networkRequests: NetworkRequest[],
    }> = {}

    // Group cookies by domain
    for (const cookie of cookies || []) {
      if (!domainData[cookie.domain]) {
        domainData[cookie.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[cookie.domain].cookies.push(cookie)
    }

    // Group scripts by domain
    for (const script of scripts || []) {
      if (!domainData[script.domain]) {
        domainData[script.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[script.domain].scripts.push(script)
    }

    // Group network requests by domain
    for (const request of networkRequests || []) {
      if (!domainData[request.domain]) {
        domainData[request.domain] = { cookies: [], scripts: [], networkRequests: [] }
      }
      domainData[request.domain].networkRequests.push(request)
    }

    // Prepare summary for LLM
    const trackingSummary = {
      analyzedUrl,
      totalCookies: cookies?.length || 0,
      totalScripts: scripts?.length || 0,
      totalNetworkRequests: networkRequests?.length || 0,
      localStorageItems: localStorage?.length || 0,
      sessionStorageItems: sessionStorage?.length || 0,
      thirdPartyDomains: Object.keys(domainData).filter(domain => {
        try {
          const pageBaseDomain = new URL(analyzedUrl).hostname.split('.').slice(-2).join('.')
          const domainBase = domain.split('.').slice(-2).join('.')
          return pageBaseDomain !== domainBase
        } catch {
          return true
        }
      }),
      domainBreakdown: Object.entries(domainData).map(([domain, data]) => ({
        domain,
        cookieCount: data.cookies.length,
        cookieNames: data.cookies.map(c => c.name),
        scriptCount: data.scripts.length,
        requestCount: data.networkRequests.length,
        requestTypes: [...new Set(data.networkRequests.map(r => r.resourceType))],
      })),
      localStorage: localStorage?.map((item: StorageItem) => ({ key: item.key, valuePreview: item.value.substring(0, 100) })) || [],
      sessionStorage: sessionStorage?.map((item: StorageItem) => ({ key: item.key, valuePreview: item.value.substring(0, 100) })) || [],
    }

    const systemPrompt = `You are a privacy and web tracking expert analyst. Your task is to analyze tracking data collected from a website and provide insights about:

1. **Tracking Technologies Identified**: Identify known tracking services (Google Analytics, Facebook Pixel, advertising networks, etc.) based on cookie names, script URLs, and network requests.

2. **Data Collection Analysis**: What types of data are likely being collected (browsing behavior, user identification, cross-site tracking, etc.)

3. **Third-Party Services**: List each third-party domain found and explain what company/service it belongs to and what they typically track.

4. **Privacy Risk Assessment**: Rate the privacy risk level (Low/Medium/High/Very High) and explain why.

5. **Cookie Analysis**: Analyze cookie purposes - which are functional, which are for tracking, and their persistence.

6. **Storage Analysis**: Analyze localStorage/sessionStorage usage and what data might be persisted.

7. **Recommendations**: What users can do to protect their privacy on this site.

Format your response in clear sections with markdown headings. Be specific about which domains and cookies you're referring to. If you recognize specific tracking technologies, name them explicitly.`

    const userPrompt = `Analyze the following tracking data collected from: ${analyzedUrl}

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

Please provide a comprehensive privacy analysis of this tracking data.`

    const deployment = process.env.AZURE_OPENAI_DEPLOYMENT!
    
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt }
      ],
      max_completion_tokens: 2000,
    })

    const analysis = response.choices[0]?.message?.content || 'No analysis generated'

    res.json({
      success: true,
      analysis,
      summary: trackingSummary,
    })
  } catch (error) {
    console.error('Analysis error:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    res.status(500).json({ error: `Analysis failed: ${message}` })
  }
})

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`)
})
