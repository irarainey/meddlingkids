/**
 * @fileoverview Partner risk classification service.
 * Classifies consent partners by risk level based on their business practices.
 * Uses pattern matching for known entities.
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

// ============================================================================
// Re-export Types from data module
// ============================================================================

export type { PartnerRiskLevel, PartnerCategory, PartnerClassification }

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
