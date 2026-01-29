/**
 * @fileoverview Script analysis service using LLM.
 * Analyzes JavaScript files to determine their purpose.
 * Groups similar scripts (like application chunks) to reduce noise.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { getTrackingScripts, getBenignScripts } from '../data/index.js'
import { createLogger, getErrorMessage, withRetry } from '../utils/index.js'
import type { TrackedScript, ScriptGroup } from '../types.js'

const log = createLogger('Script-Analysis')

/** Minimum number of similar scripts to form a group */
const MIN_GROUP_SIZE = 3

/**
 * Check if a script is a known tracking script.
 * @returns Description if it's a tracking script, null otherwise
 */
function identifyTrackingScript(url: string): string | null {
  for (const { pattern, description } of getTrackingScripts()) {
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
  for (const { pattern, description } of getBenignScripts()) {
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

/** Maximum number of scripts to analyze in a single LLM batch */
const MAX_BATCH_SIZE = 10

/** Maximum total content length for a batch (characters) */
const MAX_BATCH_CONTENT_LENGTH = 50000

/**
 * Batch script analysis prompt.
 */
const BATCH_SCRIPT_ANALYSIS_PROMPT = `You are a web security analyst. Analyze each script URL and briefly describe its purpose.

For each script, provide a SHORT description (max 10 words) of what the script does.
Focus on: tracking, analytics, advertising, functionality, UI framework, etc.

Return a JSON array with objects containing "url" and "description" for each script.
Example: [{"url": "https://example.com/script.js", "description": "User analytics tracking"}]

Return ONLY the JSON array, no other text.`

/**
 * Analyze multiple scripts in a single LLM batch call.
 * 
 * @param scripts - Array of {url, content} to analyze
 * @returns Map of URL to description
 */
async function analyzeBatchWithLLM(
  scripts: Array<{ url: string; content: string | null }>
): Promise<Map<string, string>> {
  const client = getOpenAIClient()
  const results = new Map<string, string>()
  
  if (!client || scripts.length === 0) {
    return results
  }

  const deployment = getDeploymentName()
  
  // Build batch content
  const batchContent = scripts.map((s, i) => {
    const content = s.content 
      ? s.content.substring(0, 3000) // Limit each script to 3KB for batching
      : '[Content not available]'
    return `Script ${i + 1}: ${s.url}\n${content}\n---`
  }).join('\n')

  try {
    log.debug('Sending batch to LLM', { scriptCount: scripts.length })
    
    const response = await withRetry(
      () => client.chat.completions.create({
        model: deployment,
        messages: [
          { role: 'system', content: BATCH_SCRIPT_ANALYSIS_PROMPT },
          { role: 'user', content: `Analyze these ${scripts.length} scripts:\n\n${batchContent}` },
        ],
        max_completion_tokens: 1000,
      }),
      { context: `Batch script analysis (${scripts.length} scripts)`, maxRetries: 2 }
    )

    const content = response.choices[0]?.message?.content || '[]'
    
    // Parse JSON response
    let jsonStr = content.trim()
    if (jsonStr.startsWith('```')) {
      jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
    }
    
    const parsed = JSON.parse(jsonStr) as Array<{ url: string; description: string }>
    
    for (const item of parsed) {
      if (item.url && item.description) {
        results.set(item.url, item.description)
      }
    }
    
    log.debug('Batch analysis complete', { received: results.size, expected: scripts.length })
    
  } catch (error) {
    log.error('Batch script analysis failed', { error: getErrorMessage(error) })
    // Fall back to URL inference for all scripts in this batch
    for (const script of scripts) {
      results.set(script.url, inferFromUrl(script.url))
    }
  }
  
  return results
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

// ============================================================================
// Script Grouping
// ============================================================================

/**
 * Patterns for identifying groupable scripts.
 * Scripts matching these patterns will be grouped together by domain.
 */
const GROUPABLE_PATTERNS: Array<{
  id: string
  name: string
  description: string
  pattern: RegExp
}> = [
  {
    id: 'app-chunks',
    name: 'Application code chunks',
    description: 'Code-split application bundles (SPA framework chunks)',
    pattern: /chunk[-._]?[a-f0-9]{6,}\.js|[a-f0-9]{8,}\.chunk\.js|\d+\.[a-f0-9]+\.js|chunks?\/[^/]+\.js/i,
  },
  {
    id: 'vendor-bundles',
    name: 'Vendor bundles',
    description: 'Third-party library bundles (node_modules)',
    pattern: /vendor[-._]?[a-f0-9]*\.js|vendors[-~][a-f0-9]+\.js|node_modules.*\.js/i,
  },
  {
    id: 'webpack-runtime',
    name: 'Webpack runtime',
    description: 'Webpack module loading runtime',
    pattern: /webpack[-._]?runtime[-._]?[a-f0-9]*\.js|runtime[-~][a-f0-9]+\.js/i,
  },
  {
    id: 'lazy-modules',
    name: 'Lazy-loaded modules',
    description: 'Dynamically imported modules',
    pattern: /lazy[-._]?[a-f0-9]+\.js|async[-._]?[a-f0-9]+\.js|dynamic[-._]?[a-f0-9]+\.js/i,
  },
  {
    id: 'css-chunks',
    name: 'CSS-in-JS chunks',
    description: 'Styled component or CSS module chunks',
    pattern: /styles?[-._]?[a-f0-9]+\.js|css[-._]?[a-f0-9]+\.js/i,
  },
]

/**
 * Check if a script URL matches a groupable pattern.
 * @returns The group info if matched, null otherwise
 */
function getGroupablePattern(url: string): typeof GROUPABLE_PATTERNS[0] | null {
  for (const group of GROUPABLE_PATTERNS) {
    if (group.pattern.test(url)) {
      return group
    }
  }
  return null
}

/**
 * Result of grouping scripts.
 */
export interface GroupedScriptsResult {
  /** Scripts that should be displayed individually */
  individualScripts: TrackedScript[]
  /** Groups of similar scripts */
  groups: ScriptGroup[]
  /** All original scripts with group assignments */
  allScripts: TrackedScript[]
}

/**
 * Group similar scripts together to reduce noise.
 * Groups scripts like application chunks by domain.
 * 
 * @param scripts - Array of tracked scripts
 * @returns Grouped result with individual scripts and groups
 */
export function groupSimilarScripts(scripts: TrackedScript[]): GroupedScriptsResult {
  const domainGroups = new Map<string, Map<string, TrackedScript[]>>()
  const individualScripts: TrackedScript[] = []
  const allScripts: TrackedScript[] = []
  
  // First pass: categorize scripts
  for (const script of scripts) {
    const groupPattern = getGroupablePattern(script.url)
    
    if (groupPattern) {
      // This script can be grouped
      const key = `${script.domain}:${groupPattern.id}`
      if (!domainGroups.has(key)) {
        domainGroups.set(key, new Map())
      }
      const group = domainGroups.get(key)!
      if (!group.has(groupPattern.id)) {
        group.set(groupPattern.id, [])
      }
      group.get(groupPattern.id)!.push(script)
    } else {
      // Individual script
      individualScripts.push(script)
      allScripts.push(script)
    }
  }
  
  // Second pass: create groups for scripts that meet minimum size
  const groups: ScriptGroup[] = []
  
  for (const [key, patternMap] of domainGroups) {
    const [domain, patternId] = key.split(':')
    const patternInfo = GROUPABLE_PATTERNS.find(p => p.id === patternId)
    
    for (const [, scriptsInGroup] of patternMap) {
      if (scriptsInGroup.length >= MIN_GROUP_SIZE && patternInfo) {
        // Create a group
        const groupId = `${domain}-${patternId}`
        groups.push({
          id: groupId,
          name: patternInfo.name,
          description: `${scriptsInGroup.length} ${patternInfo.description.toLowerCase()}`,
          count: scriptsInGroup.length,
          exampleUrls: scriptsInGroup.slice(0, 3).map(s => s.url),
          domain,
        })
        
        // Mark scripts as grouped
        for (const script of scriptsInGroup) {
          allScripts.push({
            ...script,
            groupId,
            isGrouped: true,
            description: patternInfo.description,
          })
        }
      } else {
        // Not enough to group, treat individually
        for (const script of scriptsInGroup) {
          individualScripts.push(script)
          allScripts.push(script)
        }
      }
    }
  }
  
  log.info('Script grouping complete', { 
    total: scripts.length, 
    individual: individualScripts.length, 
    groups: groups.length,
    grouped: allScripts.filter(s => s.isGrouped).length 
  })
  
  return { individualScripts, groups, allScripts }
}

/**
 * Progress callback for script analysis.
 * @param phase - Current phase ('matching' or 'analyzing')
 * @param current - Current item being processed
 * @param total - Total items in this phase
 * @param detail - Optional detail message
 */
export type ScriptAnalysisProgressCallback = (
  phase: 'matching' | 'fetching' | 'analyzing',
  current: number,
  total: number,
  detail?: string
) => void

/**
 * Result of script analysis including groups.
 */
export interface ScriptAnalysisResult {
  /** All scripts with descriptions */
  scripts: TrackedScript[]
  /** Groups of similar scripts */
  groups: ScriptGroup[]
}

/**
 * Analyze multiple scripts to determine their purposes.
 * 
 * Process:
 * 1. Group similar scripts (chunks, vendor bundles) - these skip LLM analysis
 * 2. Match remaining scripts against known patterns (495 tracking + 51 benign)
 * 3. Send only truly unknown scripts to LLM for analysis
 * 
 * @param scripts - Array of tracked scripts to analyze
 * @param onProgress - Optional callback for progress updates
 * @returns Scripts with descriptions and groups
 */
export async function analyzeScripts(
  scripts: TrackedScript[],
  onProgress?: ScriptAnalysisProgressCallback
): Promise<ScriptAnalysisResult> {
  // Step 1: Group similar scripts first
  const { individualScripts, groups, allScripts } = groupSimilarScripts(scripts)
  
  // Create results array matching allScripts order
  const results: TrackedScript[] = [...allScripts]
  const unknownScripts: Array<{ script: TrackedScript; index: number }> = []

  // Report matching phase start
  if (onProgress) {
    const groupedCount = allScripts.filter(s => s.isGrouped).length
    const detail = groupedCount > 0 
      ? `Grouped ${groupedCount} similar scripts, matching ${individualScripts.length} against known patterns...`
      : 'Matching scripts against known patterns...'
    onProgress('matching', 0, individualScripts.length, detail)
  }

  // Step 2: Match non-grouped scripts against known patterns
  for (let i = 0; i < results.length; i++) {
    const script = results[i]
    
    // Skip grouped scripts - they already have descriptions
    if (script.isGrouped) {
      continue
    }
    
    // Check if it's a known tracking script
    const trackingDescription = identifyTrackingScript(script.url)
    if (trackingDescription) {
      results[i] = { ...script, description: trackingDescription }
      continue
    }
    
    // Check if it's a known benign script (skip LLM analysis)
    const benignDescription = identifyBenignScript(script.url)
    if (benignDescription) {
      results[i] = { ...script, description: benignDescription }
      continue
    }
    
    // Unknown script - queue for LLM analysis
    results[i] = { ...script, description: 'Analyzing...' }
    unknownScripts.push({ script, index: i })
  }
  
  // Report matching complete
  const groupedCount = allScripts.filter(s => s.isGrouped).length
  const knownCount = individualScripts.length - unknownScripts.length
  if (onProgress) {
    onProgress('matching', individualScripts.length, individualScripts.length, 
      `Grouped ${groupedCount} scripts, identified ${knownCount} known, ${unknownScripts.length} unknown`)
  }

  // Step 3: Analyze unknown scripts with LLM in batches
  const totalToAnalyze = unknownScripts.length
  
  if (unknownScripts.length > 0) {
    log.info('Starting LLM analysis of unknown scripts', { 
      toAnalyze: unknownScripts.length, 
      grouped: groupedCount,
      knownCount, 
      total: scripts.length,
      batchSize: MAX_BATCH_SIZE
    })
    
    // Report analysis phase start
    if (onProgress) {
      onProgress('analyzing', 0, totalToAnalyze, `Analyzing ${totalToAnalyze} unknown scripts...`)
    }
    
    // First, fetch all script contents in parallel with progress
    log.info('Fetching script contents...')
    if (onProgress) {
      onProgress('fetching', 0, totalToAnalyze, `Fetching ${totalToAnalyze} script contents...`)
    }
    
    let fetchedCount = 0
    const scriptContents = await Promise.all(
      unknownScripts.map(async ({ script }) => {
        const content = await fetchScriptContent(script.url)
        fetchedCount++
        // Report progress every 5 scripts or at the end
        if (onProgress && (fetchedCount % 5 === 0 || fetchedCount === totalToAnalyze)) {
          onProgress('fetching', fetchedCount, totalToAnalyze, `Fetched ${fetchedCount}/${totalToAnalyze} scripts...`)
        }
        return { url: script.url, content }
      })
    )
    log.info('Script contents fetched', { fetched: scriptContents.filter(s => s.content).length, failed: scriptContents.filter(s => !s.content).length })
    
    // Create batches
    const batches: Array<Array<{ url: string; content: string | null; index: number }>> = []
    let currentBatch: Array<{ url: string; content: string | null; index: number }> = []
    let currentBatchContentLength = 0
    
    for (let i = 0; i < unknownScripts.length; i++) {
      const { script, index } = unknownScripts[i]
      const content = scriptContents[i].content
      const contentLength = content?.length || 0
      
      // Start new batch if current would exceed limits
      if (currentBatch.length >= MAX_BATCH_SIZE || 
          (currentBatchContentLength + contentLength > MAX_BATCH_CONTENT_LENGTH && currentBatch.length > 0)) {
        batches.push(currentBatch)
        currentBatch = []
        currentBatchContentLength = 0
      }
      
      currentBatch.push({ url: script.url, content, index })
      currentBatchContentLength += contentLength
    }
    
    // Don't forget the last batch
    if (currentBatch.length > 0) {
      batches.push(currentBatch)
    }
    
    log.info('Processing scripts in batches', { batches: batches.length, totalScripts: totalToAnalyze })
    
    // Report starting batch analysis
    if (onProgress) {
      onProgress('analyzing', 0, totalToAnalyze, `Analyzing ${totalToAnalyze} unknown scripts in ${batches.length} batches...`)
    }
    
    // Process batches sequentially to avoid rate limits
    let completedCount = 0
    
    for (let batchIndex = 0; batchIndex < batches.length; batchIndex++) {
      const batch = batches[batchIndex]
      
      // Report batch start
      if (onProgress) {
        onProgress('analyzing', completedCount, totalToAnalyze, 
          `Analyzing unknown script batch ${batchIndex + 1} of ${batches.length}...`)
      }
      
      log.info(`Processing batch ${batchIndex + 1}/${batches.length}`, { scriptsInBatch: batch.length })
      
      // Analyze batch
      const batchResults = await analyzeBatchWithLLM(
        batch.map(s => ({ url: s.url, content: s.content }))
      )
      
      // Apply results
      for (const item of batch) {
        const description = batchResults.get(item.url) || inferFromUrl(item.url)
        results[item.index] = { ...results[item.index], description }
        completedCount++
      }
      
      // Report progress after each batch
      if (onProgress) {
        onProgress('analyzing', completedCount, totalToAnalyze, 
          `Completed batch ${batchIndex + 1} of ${batches.length} (${completedCount}/${totalToAnalyze} scripts)`)
      }
    }
    
    // Ensure final progress is reported
    if (onProgress) {
      onProgress('analyzing', totalToAnalyze, totalToAnalyze, 'Script analysis complete')
    }
    
    log.success('Script analysis complete', { 
      analyzed: completedCount, 
      batches: batches.length,
      grouped: groupedCount, 
      total: results.length 
    })
  } else {
    log.info('All scripts identified from patterns or grouped, no LLM analysis needed')
    if (onProgress) {
      onProgress('analyzing', 0, 0, 'All scripts identified from patterns or grouped')
    }
  }

  return { scripts: results, groups }
}
