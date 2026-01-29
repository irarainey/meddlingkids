/**
 * @fileoverview Partner risk classification service.
 * Classifies consent partners by risk level based on their business practices.
 * Uses pattern matching for known entities and optionally LLM for unknowns.
 * 
 * Data is loaded from JSON files in server/src/data/partners/
 */

import type { ConsentPartner } from '../types.js'
import {
  getPartnerDatabase,
  PARTNER_CATEGORIES,
  type PartnerRiskLevel,
  type PartnerCategory,
  type PartnerClassification,
  type PartnerDatabase,
  type PartnerCategoryConfig,
} from '../data/index.js'
import { getOpenAIClient, getDeploymentName } from './openai.js'
import { createLogger, getErrorMessage, withRetry } from '../utils/index.js'

const log = createLogger('PartnerClassify')

// ============================================================================
// Re-export Types from data module
// ============================================================================

export type { PartnerRiskLevel, PartnerCategory, PartnerClassification }

// ============================================================================
// Types
// ============================================================================

/** Extended consent details with partner classifications */
export interface EnhancedConsentDetails {
  /** Original partner list */
  partners: ConsentPartner[]
  /** Classified partners with risk info */
  classifiedPartners: PartnerClassification[]
  /** Summary statistics */
  partnerStats: {
    total: number
    critical: number
    high: number
    medium: number
    low: number
    unknown: number
    totalRiskScore: number
  }
}

// ============================================================================
// Classification Functions
// ============================================================================

/**
 * Check if a partner name matches a database entry.
 */
function matchesPartner(
  nameLower: string,
  key: string,
  aliases: string[]
): boolean {
  return nameLower.includes(key) || aliases.some(a => nameLower.includes(a))
}

/**
 * Classify a partner against a specific database.
 */
function classifyAgainstDatabase(
  partner: ConsentPartner,
  nameLower: string,
  database: PartnerDatabase,
  config: PartnerCategoryConfig
): PartnerClassification | null {
  for (const [key, data] of Object.entries(database)) {
    if (matchesPartner(nameLower, key, data.aliases)) {
      return {
        name: partner.name,
        riskLevel: config.riskLevel,
        category: config.category,
        reason: config.reason,
        concerns: data.concerns,
        riskScore: config.riskScore,
      }
    }
  }
  return null
}

/**
 * Classify a partner based on its purpose text.
 */
function classifyByPurpose(
  partner: ConsentPartner,
  purposeLower: string
): PartnerClassification | null {
  if (purposeLower.includes('sell') || purposeLower.includes('broker') || purposeLower.includes('data marketplace')) {
    return {
      name: partner.name,
      riskLevel: 'critical',
      category: 'data-broker',
      reason: 'Partner purpose indicates data selling or brokering',
      concerns: ['Data selling disclosed in purpose'],
      riskScore: 9,
    }
  }
  
  if (purposeLower.includes('cross-site') || purposeLower.includes('cross-device') || purposeLower.includes('identity')) {
    return {
      name: partner.name,
      riskLevel: 'high',
      category: 'cross-site-tracking',
      reason: 'Partner purpose indicates cross-site or cross-device tracking',
      concerns: ['Cross-site tracking disclosed'],
      riskScore: 7,
    }
  }
  
  if (purposeLower.includes('advertising') || purposeLower.includes('ads') || purposeLower.includes('marketing')) {
    return {
      name: partner.name,
      riskLevel: 'medium',
      category: 'advertising',
      reason: 'Advertising or marketing partner',
      concerns: ['Behavioral targeting likely'],
      riskScore: 5,
    }
  }
  
  if (purposeLower.includes('analytics') || purposeLower.includes('measurement')) {
    return {
      name: partner.name,
      riskLevel: 'medium',
      category: 'analytics',
      reason: 'Analytics or measurement partner',
      concerns: ['Behavioral data collection'],
      riskScore: 4,
    }
  }
  
  if (purposeLower.includes('fraud') || purposeLower.includes('security') || purposeLower.includes('bot')) {
    return {
      name: partner.name,
      riskLevel: 'low',
      category: 'fraud-prevention',
      reason: 'Security or fraud prevention service',
      concerns: [],
      riskScore: 2,
    }
  }
  
  if (purposeLower.includes('cdn') || purposeLower.includes('content delivery') || purposeLower.includes('hosting')) {
    return {
      name: partner.name,
      riskLevel: 'low',
      category: 'content-delivery',
      reason: 'Content delivery or infrastructure partner',
      concerns: [],
      riskScore: 1,
    }
  }
  
  return null
}

/**
 * Classify a single partner based on known databases.
 * Synchronous version for quick classification without LLM.
 * Exported for use in enriching consent details.
 */
export function classifyPartnerByPatternSync(partner: ConsentPartner): PartnerClassification | null {
  const nameLower = partner.name.toLowerCase().trim()
  const purposeLower = partner.purpose?.toLowerCase() || ''
  
  // Check each partner category database in order of severity
  for (const config of PARTNER_CATEGORIES) {
    const database = getPartnerDatabase(config.file)
    const result = classifyAgainstDatabase(partner, nameLower, database, config)
    if (result) {
      return result
    }
  }
  
  // Fall back to purpose-based classification
  return classifyByPurpose(partner, purposeLower)
}

/**
 * Use LLM to classify unknown partners in batch.
 */
async function classifyUnknownPartnersWithLLM(
  partners: ConsentPartner[]
): Promise<Map<string, PartnerClassification>> {
  const results = new Map<string, PartnerClassification>()
  
  if (partners.length === 0) return results
  
  const client = getOpenAIClient()
  if (!client) {
    log.warn('OpenAI not configured, using default classification for unknown partners')
    for (const p of partners) {
      results.set(p.name, {
        name: p.name,
        riskLevel: 'unknown',
        category: 'unknown',
        reason: 'Could not classify - no pattern match',
        concerns: [],
        riskScore: 3, // Default medium-low risk
      })
    }
    return results
  }
  
  const deployment = getDeploymentName()
  
  // Batch partners for efficiency (max 20 at a time)
  const batches: ConsentPartner[][] = []
  for (let i = 0; i < partners.length; i += 20) {
    batches.push(partners.slice(i, i + 20))
  }
  
  for (const batch of batches) {
    const partnerList = batch.map(p => `- "${p.name}": ${p.purpose || 'No purpose specified'}`).join('\n')
    
    try {
      const response = await withRetry(
        () => client.chat.completions.create({
          model: deployment,
          messages: [
            {
              role: 'system',
              content: `You are a privacy expert analyzing data partners from a website's cookie consent dialog.
              
For each partner, classify their privacy risk level and category.

Risk levels:
- critical: Data brokers, identity resolution, companies that sell data
- high: Major ad networks, session replay, cross-device tracking
- medium: Standard advertising, analytics, personalization
- low: CDN, fraud prevention, essential services

Categories: data-broker, advertising, cross-site-tracking, identity-resolution, analytics, social-media, content-delivery, fraud-prevention, personalization, measurement

Respond with JSON array only:
[{"name": "Partner Name", "riskLevel": "high", "category": "advertising", "reason": "Brief reason", "concerns": ["concern1"], "riskScore": 7}]

Risk scores: critical=9-10, high=6-8, medium=4-5, low=1-3`,
            },
            {
              role: 'user',
              content: `Classify these partners:\n${partnerList}`,
            },
          ],
          max_completion_tokens: 1500,
        }),
        { context: 'Partner classification' }
      )
      
      const content = response.choices[0]?.message?.content || '[]'
      let jsonStr = content.trim()
      if (jsonStr.startsWith('```')) {
        jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
      }
      
      const classifications = JSON.parse(jsonStr) as PartnerClassification[]
      for (const c of classifications) {
        results.set(c.name, c)
      }
    } catch (error) {
      log.warn('LLM partner classification failed for batch', { error: getErrorMessage(error) })
      // Fall back to unknown classification
      for (const p of batch) {
        if (!results.has(p.name)) {
          results.set(p.name, {
            name: p.name,
            riskLevel: 'unknown',
            category: 'unknown',
            reason: 'Classification failed',
            concerns: [],
            riskScore: 3,
          })
        }
      }
    }
  }
  
  return results
}

/**
 * Classify all partners from consent details.
 * Uses pattern matching first, then LLM for unknowns.
 */
export async function classifyPartners(
  partners: ConsentPartner[],
  useLLMForUnknowns: boolean = true
): Promise<EnhancedConsentDetails> {
  log.info('Classifying partners', { count: partners.length, useLLM: useLLMForUnknowns })
  
  const classified: PartnerClassification[] = []
  const unknowns: ConsentPartner[] = []
  
  // First pass: pattern matching
  for (const partner of partners) {
    const result = classifyPartnerByPatternSync(partner)
    if (result) {
      classified.push(result)
    } else {
      unknowns.push(partner)
    }
  }
  
  log.info('Pattern matching complete', { classified: classified.length, unknown: unknowns.length })
  
  // Second pass: LLM for unknowns (if enabled and there are unknowns)
  if (useLLMForUnknowns && unknowns.length > 0) {
    log.info('Classifying unknown partners with LLM...')
    const llmResults = await classifyUnknownPartnersWithLLM(unknowns)
    for (const [, classification] of llmResults) {
      classified.push(classification)
    }
  } else {
    // Add unknowns with default classification
    for (const p of unknowns) {
      classified.push({
        name: p.name,
        riskLevel: 'unknown',
        category: 'unknown',
        reason: 'No pattern match found',
        concerns: [],
        riskScore: 3,
      })
    }
  }
  
  // Calculate statistics
  const stats = {
    total: classified.length,
    critical: classified.filter(c => c.riskLevel === 'critical').length,
    high: classified.filter(c => c.riskLevel === 'high').length,
    medium: classified.filter(c => c.riskLevel === 'medium').length,
    low: classified.filter(c => c.riskLevel === 'low').length,
    unknown: classified.filter(c => c.riskLevel === 'unknown').length,
    totalRiskScore: classified.reduce((sum, c) => sum + c.riskScore, 0),
  }
  
  log.success('Partner classification complete', stats)
  
  return {
    partners,
    classifiedPartners: classified,
    partnerStats: stats,
  }
}

/**
 * Get a quick risk summary for partners without full classification.
 * Uses only pattern matching for speed.
 */
export function getPartnerRiskSummary(partners: ConsentPartner[]): {
  criticalCount: number
  highCount: number
  totalRiskScore: number
  worstPartners: string[]
} {
  let criticalCount = 0
  let highCount = 0
  let totalRiskScore = 0
  const worstPartners: string[] = []
  
  for (const partner of partners) {
    const result = classifyPartnerByPatternSync(partner)
    if (result) {
      totalRiskScore += result.riskScore
      if (result.riskLevel === 'critical') {
        criticalCount++
        worstPartners.push(`${partner.name} (${result.category})`)
      } else if (result.riskLevel === 'high') {
        highCount++
        if (worstPartners.length < 5) {
          worstPartners.push(`${partner.name} (${result.category})`)
        }
      }
    } else {
      totalRiskScore += 3 // Default for unknown
    }
  }
  
  return { criticalCount, highCount, totalRiskScore, worstPartners }
}
