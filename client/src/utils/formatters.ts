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
 * Convert an ISO 3166-1 alpha-2 country code to its flag emoji.
 *
 * Each letter is offset to the Unicode Regional Indicator Symbol
 * range (U+1F1E6..U+1F1FF), which renders as a flag emoji.
 *
 * @param code - Two-letter country code (e.g. "US", "DE")
 * @returns Flag emoji (e.g. "🇺🇸", "🇩🇪"), or empty string for invalid input
 */
export function countryCodeToFlag(code: string): string {
  if (!code || code.length !== 2) return ''
  const upper = code.toUpperCase()
  const first = upper.codePointAt(0)
  const second = upper.codePointAt(1)
  if (!first || !second) return ''
  // Regional indicator symbols: A=0x1F1E6, B=0x1F1E7, ...
  return String.fromCodePoint(first - 0x41 + 0x1F1E6) + String.fromCodePoint(second - 0x41 + 0x1F1E6)
}

/**
 * Get the URL for a country flag SVG image.
 *
 * Uses the flag-icons project (MIT license) via CDN.
 * @see https://github.com/lipis/flag-icons
 *
 * @param code - Two-letter country code (e.g. "US", "DE")
 * @returns URL to a 4x3 SVG flag image, or empty string for invalid input
 */
export function countryFlagUrl(code: string): string {
  if (!code || code.length !== 2) return ''
  return `https://cdn.jsdelivr.net/gh/lipis/flag-icons/flags/4x3/${code.toLowerCase()}.svg`
}

/** Cached Intl.DisplayNames instance for country name lookups. */
const countryNames = new Intl.DisplayNames(['en'], { type: 'region' })

/**
 * Get the full English name for an ISO 3166-1 alpha-2 country code.
 *
 * Uses the browser's built-in Intl.DisplayNames API.
 *
 * @param code - Two-letter country code (e.g. "US", "DE")
 * @returns Full country name (e.g. "United States", "Germany"), or the code itself as fallback
 */
export function countryName(code: string): string {
  if (!code || code.length !== 2) return code
  try {
    return countryNames.of(code.toUpperCase()) ?? code
  } catch {
    return code
  }
}

// ============================================================================
// Risk / Severity Utilities
// ============================================================================

/**
 * Map a severity level to its badge CSS class.
 *
 * @param level - Severity level (critical, very-high, high, medium, low, none)
 * @returns CSS class name for the badge
 */
export function severityClass(level: string): string {
  switch (level) {
    case 'critical':
    case 'very-high':
      return 'badge-critical'
    case 'high':
      return 'badge-high'
    case 'medium':
      return 'badge-medium'
    case 'low':
      return 'badge-low'
    case 'none':
      return 'badge-none'
    default:
      return 'badge-medium'
  }
}

/**
 * Convert a severity level to a human-readable label.
 *
 * @param level - Severity level key
 * @returns Display-friendly label
 */
export function riskLabel(level: string): string {
  switch (level) {
    case 'very-high':
      return 'Very High'
    case 'critical':
      return 'Critical'
    case 'high':
      return 'High'
    case 'medium':
      return 'Medium'
    case 'low':
      return 'Low'
    case 'none':
      return 'None'
    default:
      return level
  }
}

/**
 * Map a risk level to its CSS class.
 *
 * @param level - Risk level (none, low, medium, high, critical, unknown)
 * @returns CSS class name for risk styling
 */
export function riskClass(level: string): string {
  const classes: Record<string, string> = {
    none: 'risk-none',
    low: 'risk-low',
    medium: 'risk-medium',
    high: 'risk-high',
    critical: 'risk-critical',
    unknown: 'risk-unknown',
  }
  return classes[level] || 'risk-low'
}

/**
 * Map a tracking purpose to an emoji-prefixed label.
 *
 * @param purpose - Purpose identifier
 * @returns Emoji + label string
 */
export function purposeLabel(purpose: string): string {
  const labels: Record<string, string> = {
    analytics: '📊 Analytics',
    advertising: '📢 Advertising',
    functional: '⚙️ Functional',
    session: '🔑 Session',
    consent: '✅ Consent',
    'social-media': '👥 Social Media',
    fingerprinting: '🔍 Fingerprinting',
    'identity-resolution': '🆔 Identity Resolution',
    unknown: '❓ Unknown',
  }
  return labels[purpose] || purpose
}

// ============================================================================
// URL Utilities
// ============================================================================

/**
 * Strip query string and fragment from a URL, returning origin + pathname.
 *
 * @param url - Full URL string
 * @returns URL without query/fragment, or the original string on parse failure
 */
export function stripQueryAndFragment(url: string): string {
  try {
    const u = new URL(url)
    return u.origin + u.pathname
  } catch {
    const noQuery = url.indexOf('?') >= 0 ? url.substring(0, url.indexOf('?')) : url
    const noFrag = noQuery.indexOf('#') >= 0 ? noQuery.substring(0, noQuery.indexOf('#')) : noQuery
    return noFrag
  }
}

/** Two-part TLDs that require a three-label base domain. */
const TWO_PART_TLDS = [
  'co.uk', 'com.au', 'org.uk', 'co.jp', 'com.br',
  'co.nz', 'co.za', 'com.mx', 'co.kr', 'com.in',
]

/**
 * Extract the registrable base domain from a hostname.
 *
 * Handles common multi-part TLDs (e.g. co.uk, com.au).
 *
 * @param hostname - Full hostname, optionally with leading dot
 * @returns Base domain (e.g. "example.co.uk")
 */
export function baseDomain(hostname: string): string {
  const parts = hostname.replace(/^\./, '').split('.')
  if (parts.length >= 3) {
    const lastTwo = parts.slice(-2).join('.')
    if (TWO_PART_TLDS.includes(lastTwo)) {
      return parts.slice(-3).join('.')
    }
  }
  return parts.slice(-2).join('.')
}

// ============================================================================
// Text Formatting Utilities
// ============================================================================

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
