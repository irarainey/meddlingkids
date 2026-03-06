/**
 * @fileoverview Formatting utility functions for display.
 */

// ============================================================================
// Score Display Utilities
// ============================================================================

/**
 * Get a themed exclamation phrase based on privacy risk score.
 *
 * @param score - Privacy risk score (0-100), or null
 * @returns Scooby-Doo themed exclamation
 */
export function getExclamation(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'Zoinks!'
  if (s >= 60) return 'Jeepers!'
  if (s >= 40) return 'Ruh-Roh!'
  if (s >= 20) return 'Jinkies!'
  return 'Scoob-tastic!'
}

/**
 * Get the risk level label based on privacy score.
 *
 * @param score - Privacy risk score (0-100), or null
 * @returns Human-readable risk level
 */
export function getRiskLevel(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'Critical Risk'
  if (s >= 60) return 'High Risk'
  if (s >= 40) return 'Moderate Risk'
  if (s >= 20) return 'Low Risk'
  return 'Very Low Risk'
}

/**
 * Get the CSS class for score styling based on risk level.
 *
 * @param score - Privacy risk score (0-100), or null
 * @returns CSS class name for theming
 */
export function getScoreClass(score: number | null): string {
  const s = Number(score)
  if (s >= 80) return 'score-critical'
  if (s >= 60) return 'score-high'
  if (s >= 40) return 'score-moderate'
  if (s >= 20) return 'score-low'
  return 'score-safe'
}

// ============================================================================
// Data Formatting Utilities
// ============================================================================

/**
 * Format a cookie expiry timestamp for display.
 *
 * @param expires - Unix timestamp in seconds, or -1 for session cookies
 * @returns Human-readable expiry string
 */
export function formatExpiry(expires: number): string {
  if (expires === -1) return 'Session'
  const date = new Date(expires * 1000)
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString()
}

/**
 * Truncate a string value for display.
 *
 * @param value - The string to truncate
 * @param maxLength - Maximum length before truncation (default: 50)
 * @returns Truncated string with ellipsis if needed
 */
export function truncateValue(value: string, maxLength = 50): string {
  if (value.length <= maxLength) return value
  return value.substring(0, maxLength) + '...'
}

/**
 * Get an emoji icon for a network resource type.
 *
 * @param type - The resource type (script, xhr, image, etc.)
 * @returns Emoji representing the resource type
 */
export function getResourceTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    script: '📜',
    xhr: '🔄',
    fetch: '🔄',
    image: '🖼️',
    stylesheet: '🎨',
    font: '🔤',
    document: '📄',
    other: '📦',
  }
  return icons[type] || '📦'
}

/**
 * Strip markdown formatting from text for plain-text display.
 *
 * LLM-generated text sometimes includes markdown bold (`**text**`),
 * italic (`*text*`), inline code (`` `text` ``), or links
 * (`[text](url)`). When rendered via Vue text interpolation
 * (`{{ }}`), the raw markup characters are visible to the user.
 * This function removes them, leaving only the readable content.
 *
 * @param text - Text that may contain markdown formatting
 * @returns Plain text with markdown syntax stripped
 */
export function stripMarkdown(text: string): string {
  return text
    // Bold: **text** or __text__
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    // Italic: *text* or _text_ (single markers)
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/(?<!\w)_(.+?)_(?!\w)/g, '$1')
    // Inline code: `text`
    .replace(/`(.+?)`/g, '$1')
    // Links: [text](url)
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')
    // Headers: ### text
    .replace(/^#{1,6}\s+/gm, '')
}
