/**
 * @fileoverview Data loader for tracker and partner databases.
 * Loads JSON files and compiles patterns into RegExp objects.
 * 
 * ============================================================================
 * DATA SOURCES
 * ============================================================================
 * 
 * This data is compiled from publicly available sources:
 * 
 * === GOVERNMENT & REGULATORY ===
 * - FTC Data Broker Reports: https://www.ftc.gov/reports/data-brokers-call-transparency-accountability
 * - California CCPA Data Broker Registry: https://oag.ca.gov/data-brokers
 * - Vermont Data Broker Registry: https://ago.vermont.gov/cap/data-broker-search
 * - Texas Data Broker Registry: https://www.texas.gov/data-broker
 * - Oregon Data Broker Registry: https://justice.oregon.gov/databroker/
 * - EU GDPR Enforcement Tracker: https://www.enforcementtracker.com/
 * 
 * === OPEN SOURCE FILTER LISTS ===
 * - EasyList / EasyPrivacy: https://easylist.to/
 * - Disconnect.me Tracker List: https://disconnect.me/trackerprotection
 * - DuckDuckGo Tracker Radar: https://github.com/nickyvadera/tracker-radar
 * - Privacy Badger: https://github.com/EFForg/privacybadger
 * - uBlock Origin Filter Lists: https://github.com/uBlockOrigin/uAssets
 * - AdGuard Filter Lists: https://github.com/AdguardTeam/AdguardFilters
 * - WhoTracks.Me Database: https://whotracks.me/
 * 
 * === MOBILE APP TRACKERS ===
 * - Exodus Privacy: https://exodus-privacy.eu.org/
 * - AppCensus: https://appcensus.io/
 * 
 * === ACADEMIC & RESEARCH ===
 * - Princeton WebTAP: https://webtap.princeton.edu/
 * - The Markup's Blacklight: https://themarkup.org/blacklight
 * 
 * === INDUSTRY SOURCES ===
 * - IAB TCF Vendor List: https://iabeurope.eu/tcf-2-0/
 * - Cookiepedia: https://cookiepedia.co.uk/
 * 
 * Last comprehensive update: January 2026
 * ============================================================================
 */

import { readFileSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'
import type {
  ScriptPattern,
  ScriptPatternRaw,
  PartnerDatabase,
  PartnerCategoryConfig,
} from './types.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

// ============================================================================
// JSON File Loading
// ============================================================================

/**
 * Load and parse a JSON file.
 */
function loadJson<T>(relativePath: string): T {
  const fullPath = join(__dirname, relativePath)
  const content = readFileSync(fullPath, 'utf-8')
  return JSON.parse(content) as T
}

// ============================================================================
// Script Pattern Loading
// ============================================================================

/**
 * Load script patterns from a JSON file and compile to RegExp.
 */
function loadScriptPatterns(filename: string): ScriptPattern[] {
  const raw = loadJson<ScriptPatternRaw[]>(`trackers/${filename}`)
  return raw.map(entry => ({
    pattern: new RegExp(entry.pattern, 'i'),
    description: entry.description,
  }))
}

/** Tracking scripts database - loaded once at startup */
let _trackingScripts: ScriptPattern[] | null = null

/** Benign scripts database - loaded once at startup */
let _benignScripts: ScriptPattern[] | null = null

/**
 * Get tracking scripts database (lazy loaded and cached).
 */
export function getTrackingScripts(): ScriptPattern[] {
  if (!_trackingScripts) {
    _trackingScripts = loadScriptPatterns('tracking-scripts.json')
  }
  return _trackingScripts
}

/**
 * Get benign scripts database (lazy loaded and cached).
 */
export function getBenignScripts(): ScriptPattern[] {
  if (!_benignScripts) {
    _benignScripts = loadScriptPatterns('benign-scripts.json')
  }
  return _benignScripts
}

// ============================================================================
// Partner Data Loading
// ============================================================================

/**
 * Load partner database from a JSON file.
 */
function loadPartnerDatabase(filename: string): PartnerDatabase {
  return loadJson<PartnerDatabase>(`partners/${filename}`)
}

/** Cache for loaded partner databases */
const partnerDatabaseCache = new Map<string, PartnerDatabase>()

/**
 * Get a partner database by filename (lazy loaded and cached).
 */
export function getPartnerDatabase(filename: string): PartnerDatabase {
  if (!partnerDatabaseCache.has(filename)) {
    partnerDatabaseCache.set(filename, loadPartnerDatabase(filename))
  }
  return partnerDatabaseCache.get(filename)!
}

/**
 * Get all partner databases keyed by category config.
 */
export function getAllPartnerDatabases(
  categories: readonly PartnerCategoryConfig[]
): Map<PartnerCategoryConfig, PartnerDatabase> {
  const result = new Map<PartnerCategoryConfig, PartnerDatabase>()
  for (const config of categories) {
    result.set(config, getPartnerDatabase(config.file))
  }
  return result
}
