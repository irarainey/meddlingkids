/**
 * @fileoverview API configuration constants.
 */

/**
 * Base URL for API requests.
 *
 * Uses the VITE_API_URL environment variable when set (e.g. for
 * development proxying), otherwise defaults to the current origin.
 */
export const API_BASE = import.meta.env.VITE_API_URL || ''
