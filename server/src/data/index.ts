/**
 * @fileoverview Barrel export for data modules.
 * 
 * Data is loaded from JSON files in the trackers/ and partners/ directories.
 * This separation allows:
 * - Easy updates to data without code changes
 * - Future migration to a database
 * - Better testability with mock data
 * - Reduced file size for code-only files
 */

// Types
export type {
  ScriptPattern,
  ScriptPatternRaw,
  PartnerEntry,
  PartnerDatabase,
  PartnerRiskLevel,
  PartnerCategory,
  PartnerClassification,
  PartnerCategoryConfig,
} from './types.js'

// Category configuration
export { PARTNER_CATEGORIES } from './types.js'

// Data loaders
export {
  getTrackingScripts,
  getBenignScripts,
  getPartnerDatabase,
  getAllPartnerDatabases,
} from './loader.js'
