/**
 * @fileoverview Type definitions for tracker and partner data.
 * These types define the structure of data loaded from JSON files.
 */

// ============================================================================
// Script Pattern Types
// ============================================================================

/**
 * Raw script pattern as stored in JSON (pattern is a string).
 */
export interface ScriptPatternRaw {
  /** Regular expression pattern string (without delimiters) */
  pattern: string
  /** Human-readable description of what the script does */
  description: string
}

/**
 * Compiled script pattern with RegExp ready for matching.
 */
export interface ScriptPattern {
  /** Compiled regular expression for matching script URLs */
  pattern: RegExp
  /** Human-readable description of what the script does */
  description: string
}

// ============================================================================
// Partner Data Types
// ============================================================================

/**
 * Partner entry as stored in JSON.
 */
export interface PartnerEntry {
  /** Known privacy concerns about this partner */
  concerns: string[]
  /** Alternative names/spellings for this partner */
  aliases: string[]
}

/**
 * Partner database - maps partner name to their details.
 */
export type PartnerDatabase = Record<string, PartnerEntry>

/**
 * Risk level for a data partner.
 */
export type PartnerRiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'unknown'

/**
 * Categories of partner businesses.
 */
export type PartnerCategory =
  | 'data-broker'
  | 'advertising'
  | 'cross-site-tracking'
  | 'identity-resolution'
  | 'analytics'
  | 'social-media'
  | 'content-delivery'
  | 'fraud-prevention'
  | 'personalization'
  | 'measurement'
  | 'unknown'

/**
 * Classification result for a partner.
 */
export interface PartnerClassification {
  /** Original partner name */
  name: string
  /** Assessed risk level */
  riskLevel: PartnerRiskLevel
  /** Category of business */
  category: PartnerCategory
  /** Reason for the classification */
  reason: string
  /** Known privacy concerns */
  concerns: string[]
  /** Risk score contribution (0-10) */
  riskScore: number
}

// ============================================================================
// Partner Category Configuration
// ============================================================================

/**
 * Configuration for how a partner category should be classified.
 */
export interface PartnerCategoryConfig {
  /** File name of the JSON data file */
  file: string
  /** Risk level for partners in this category */
  riskLevel: PartnerRiskLevel
  /** Category label */
  category: PartnerCategory
  /** Default reason for classification */
  reason: string
  /** Risk score for this category */
  riskScore: number
}

/**
 * All partner category configurations.
 */
export const PARTNER_CATEGORIES: PartnerCategoryConfig[] = [
  {
    file: 'data-brokers.json',
    riskLevel: 'critical',
    category: 'data-broker',
    reason: 'Known data broker that aggregates and sells personal information',
    riskScore: 10,
  },
  {
    file: 'identity-trackers.json',
    riskLevel: 'critical',
    category: 'identity-resolution',
    reason: 'Identity resolution service that links your identity across devices and sites',
    riskScore: 9,
  },
  {
    file: 'session-replay.json',
    riskLevel: 'high',
    category: 'cross-site-tracking',
    reason: 'Session replay service that records your interactions on the site',
    riskScore: 8,
  },
  {
    file: 'ad-networks.json',
    riskLevel: 'high',
    category: 'advertising',
    reason: 'Major advertising network that tracks across many websites',
    riskScore: 7,
  },
  {
    file: 'mobile-sdk-trackers.json',
    riskLevel: 'high',
    category: 'cross-site-tracking',
    reason: 'Mobile SDK tracker embedded in apps for user tracking',
    riskScore: 7,
  },
  {
    file: 'analytics-trackers.json',
    riskLevel: 'medium',
    category: 'analytics',
    reason: 'Analytics or marketing platform that collects behavioral data',
    riskScore: 5,
  },
  {
    file: 'social-trackers.json',
    riskLevel: 'medium',
    category: 'social-media',
    reason: 'Social media tracker that monitors social interactions across sites',
    riskScore: 5,
  },
  {
    file: 'consent-platforms.json',
    riskLevel: 'medium',
    category: 'personalization',
    reason: 'Consent management platform that may share consent signals',
    riskScore: 4,
  },
]
