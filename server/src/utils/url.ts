// URL and domain utility functions

export function extractDomain(url: string): string {
  try {
    const urlObj = new URL(url)
    return urlObj.hostname
  } catch {
    return 'unknown'
  }
}

export function getBaseDomain(domain: string): string {
  const parts = domain.split('.')
  // Handle common TLDs like co.uk, com.au, etc.
  if (parts.length > 2 && parts[parts.length - 2].length <= 3) {
    return parts.slice(-3).join('.')
  }
  return parts.slice(-2).join('.')
}

export function isThirdParty(requestUrl: string, pageUrl: string): boolean {
  try {
    const requestDomain = extractDomain(requestUrl)
    const pageDomain = extractDomain(pageUrl)
    return getBaseDomain(requestDomain) !== getBaseDomain(pageDomain)
  } catch {
    return true
  }
}
