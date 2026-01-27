/**
 * @fileoverview Script analysis service using LLM.
 * Analyzes JavaScript files to determine their purpose.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { SCRIPT_ANALYSIS_SYSTEM_PROMPT, buildScriptAnalysisUserPrompt } from '../prompts/index.js'
import { TRACKING_SCRIPTS, BENIGN_SCRIPTS } from '../data/index.js'
import type { TrackedScript } from '../types.js'

/** Maximum script content length to send to LLM (in characters) */
const MAX_SCRIPT_LENGTH = 30000

/**
 * Check if a script is a known tracking script.
 * @returns Description if it's a tracking script, null otherwise
 */
function identifyTrackingScript(url: string): string | null {
  for (const { pattern, description } of TRACKING_SCRIPTS) {
    if (pattern.test(url)) {
      return description
    }
  }
  return null
}

/**
 * Check if a script is a known benign script (should skip LLM analysis).
 * @returns Description if it's benign, null otherwise
 */
function identifyBenignScript(url: string): string | null {
  for (const { pattern, description } of BENIGN_SCRIPTS) {
    if (pattern.test(url)) {
      return description
    }
  }
  return null
}

/**
 * Fetch a script's content for analysis.
 * 
 * @param url - The script URL
 * @returns The script content or null if fetch failed
 */
async function fetchScriptContent(url: string): Promise<string | null> {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000) // 5 second timeout
    
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; SecurityAnalyzer/1.0)',
      },
    })
    
    clearTimeout(timeoutId)
    
    if (!response.ok) {
      return null
    }
    
    const content = await response.text()
    return content
  } catch {
    return null
  }
}

/**
 * Analyze a single script using LLM.
 * 
 * @param scriptContent - The JavaScript content (will be truncated if too long)
 * @param url - The script URL for context
 * @returns A short description of the script's purpose
 */
async function analyzeScriptWithLLM(scriptContent: string, url: string): Promise<string> {
  const client = getOpenAIClient()
  if (!client) {
    return 'Analysis unavailable - OpenAI not configured'
  }

  const deployment = getDeploymentName()
  
  // Truncate content if too long
  const truncatedContent = scriptContent.length > MAX_SCRIPT_LENGTH
    ? scriptContent.substring(0, MAX_SCRIPT_LENGTH) + '\n... [truncated]'
    : scriptContent

  try {
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: SCRIPT_ANALYSIS_SYSTEM_PROMPT },
        { role: 'user', content: buildScriptAnalysisUserPrompt(url, truncatedContent) },
      ],
      max_completion_tokens: 150,
      temperature: 0.3, // Lower temperature for more consistent results
    })

    const description = response.choices[0]?.message?.content?.trim() || 'Purpose unclear'
    return description
  } catch (error) {
    console.error('Script analysis error:', error)
    return 'Analysis failed'
  }
}

/**
 * Infer a script's purpose from its URL when content is unavailable.
 * 
 * @param url - The script URL
 * @returns A best-guess description
 */
function inferFromUrl(url: string): string {
  const urlLower = url.toLowerCase()
  
  // Check filename patterns
  if (urlLower.includes('analytics')) return 'Analytics script'
  if (urlLower.includes('tracking') || urlLower.includes('tracker')) return 'Tracking script'
  if (urlLower.includes('pixel')) return 'Tracking pixel'
  if (urlLower.includes('consent') || urlLower.includes('gdpr') || urlLower.includes('privacy')) return 'Consent/privacy related'
  if (urlLower.includes('chat') || urlLower.includes('widget')) return 'Chat or widget script'
  if (urlLower.includes('ads') || urlLower.includes('advert')) return 'Advertising script'
  if (urlLower.includes('social') || urlLower.includes('share')) return 'Social sharing script'
  if (urlLower.includes('vendor') || urlLower.includes('third-party')) return 'Third-party vendor script'
  if (urlLower.includes('polyfill')) return 'Browser compatibility polyfill'
  if (urlLower.includes('main') || urlLower.includes('app') || urlLower.includes('bundle')) return 'Application bundle'
  if (urlLower.includes('chunk')) return 'Code-split chunk'
  
  return 'Third-party script'
}

/**
 * Progress callback for script analysis.
 */
export type ScriptAnalysisProgressCallback = (current: number, total: number) => void

/**
 * Analyze multiple scripts to determine their purposes.
 * Uses pattern matching for known tracking/benign scripts and LLM for unknown ones.
 * Only analyzes unknown scripts with LLM - skips benign libraries/frameworks.
 * 
 * @param scripts - Array of tracked scripts to analyze
 * @param maxLLMAnalyses - Maximum number of scripts to analyze with LLM (default: 20)
 * @param onProgress - Optional callback for progress updates
 * @returns Scripts with descriptions added
 */
export async function analyzeScripts(
  scripts: TrackedScript[],
  maxLLMAnalyses: number = 20,
  onProgress?: ScriptAnalysisProgressCallback
): Promise<TrackedScript[]> {
  const results: TrackedScript[] = []
  const unknownScripts: Array<{ script: TrackedScript; index: number }> = []

  // First pass: identify known scripts by URL pattern
  for (let i = 0; i < scripts.length; i++) {
    const script = scripts[i]
    
    // Check if it's a known tracking script
    const trackingDescription = identifyTrackingScript(script.url)
    if (trackingDescription) {
      results.push({ ...script, description: trackingDescription })
      continue
    }
    
    // Check if it's a known benign script (skip LLM analysis)
    const benignDescription = identifyBenignScript(script.url)
    if (benignDescription) {
      results.push({ ...script, description: benignDescription })
      continue
    }
    
    // Unknown script - queue for LLM analysis
    results.push({ ...script, description: 'Analyzing...' })
    unknownScripts.push({ script, index: i })
  }

  // Second pass: analyze unknown scripts with LLM (limited to maxLLMAnalyses)
  const scriptsToAnalyze = unknownScripts.slice(0, maxLLMAnalyses)
  const totalToAnalyze = scriptsToAnalyze.length
  let analyzedCount = 0
  
  if (scriptsToAnalyze.length > 0) {
    console.log(`Analyzing ${scriptsToAnalyze.length} unknown scripts with LLM in parallel (skipped ${scripts.length - unknownScripts.length} known scripts)...`)
    
    // Process all scripts in parallel - OpenAI handles rate limiting internally
    const analysisPromises = scriptsToAnalyze.map(async ({ script, index }) => {
      try {
        // Try to fetch script content
        const content = await fetchScriptContent(script.url)
        
        if (content) {
          const description = await analyzeScriptWithLLM(content, script.url)
          results[index] = { ...results[index], description }
        } else {
          // Couldn't fetch content - try to infer from URL
          results[index] = { ...results[index], description: inferFromUrl(script.url) }
        }
      } catch (error) {
        console.error(`Error analyzing script ${script.url}:`, error)
        results[index] = { ...results[index], description: inferFromUrl(script.url) }
      }
      
      // Update progress
      analyzedCount++
      if (onProgress) {
        onProgress(analyzedCount, totalToAnalyze)
      }
    })
    
    await Promise.all(analysisPromises)
  } else {
    console.log('All scripts identified from known patterns, no LLM analysis needed')
  }

  // Mark remaining unknown scripts (beyond maxLLMAnalyses)
  for (let i = maxLLMAnalyses; i < unknownScripts.length; i++) {
    const { index, script } = unknownScripts[i]
    results[index] = { ...results[index], description: inferFromUrl(script.url) }
  }

  return results
}
