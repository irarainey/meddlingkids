/**
 * @fileoverview URL and domain utility functions for tracking analysis.
 * Provides helpers to extract domains and detect third-party requests.
 */

/**
 * Extract the hostname from a URL string.
 *
 * @param url - The full URL to parse
 * @returns The hostname (e.g., 'www.example.com') or 'unknown' if parsing fails
 *
 * @example
 * extractDomain('https://www.example.com/path') // Returns 'www.example.com'
 * extractDomain('invalid-url') // Returns 'unknown'
 */
export function extractDomain(url: string): string {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname
  } catch {
    return 'unknown'
  }
}

/**
 * Extract the base domain (last two or three parts) from a full domain.
 * Handles common multi-part TLDs like co.uk, com.au, etc.
 *
 * @param domain - The full domain name
 * @returns The base domain (e.g., 'example.com' from 'www.example.com')
 *
 * @example
 * getBaseDomain('www.example.com') // Returns 'example.com'
 * getBaseDomain('sub.domain.co.uk') // Returns 'domain.co.uk'
 */
function getBaseDomain(domain: string): string {
  const parts = domain.split('.')
  // Handle common TLDs like co.uk, com.au, etc.
  if (parts.length > 2 && parts[parts.length - 2].length <= 3) {
    return parts.slice(-3).join('.')
  }
  return parts.slice(-2).join('.')
}

/**
 * Determine if a request URL is from a third-party domain relative to the page URL.
 * Third-party requests are those going to a different base domain than the page.
 *
 * @param requestUrl - The URL of the outgoing request
 * @param pageUrl - The URL of the page making the request
 * @returns True if the request is to a third-party domain
 *
 * @example
 * isThirdParty('https://tracker.com/pixel.gif', 'https://example.com') // Returns true
 * isThirdParty('https://cdn.example.com/script.js', 'https://example.com') // Returns false
 */
export function isThirdParty(requestUrl: string, pageUrl: string): boolean {
  try {
    const requestDomain = extractDomain(requestUrl)
    const pageDomain = extractDomain(pageUrl)
    return getBaseDomain(requestDomain) !== getBaseDomain(pageDomain)
  } catch {
    return true
  }
}
