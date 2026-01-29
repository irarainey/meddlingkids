/**
 * @fileoverview Deterministic privacy score calculation.
 * Provides consistent scoring based on quantifiable tracking factors.
 * Score ranges from 0 (best privacy) to 100 (worst privacy).
 * 
 * Major scoring factors:
 * - Number of data sharing partners (heavily weighted)
 * - Partner risk classification (data brokers score highest)
 * - Cross-site/cross-device tracking presence
 * - Tracking before consent is given
 */

import type { TrackedCookie, TrackedScript, NetworkRequest, StorageItem, ConsentDetails } from '../types.js'
import { getTrackingScripts } from '../data/index.js'
import { createLogger } from '../utils/logger.js'
import { getPartnerRiskSummary } from './partner-classification.js'

const log = createLogger('PrivacyScore')

// ============================================================================
// Types
// ============================================================================

/** Detailed breakdown of the privacy score calculation */
export interface PrivacyScoreBreakdown {
  /** Final score 0-100 (higher = worse privacy) */
  totalScore: number
  /** Individual category scores and details */
  categories: {
    cookies: CategoryScore
    thirdPartyTrackers: CategoryScore
    dataCollection: CategoryScore
    fingerprinting: CategoryScore
    advertising: CategoryScore
    socialMedia: CategoryScore
    sensitiveData: CategoryScore
    consent: CategoryScore
  }
  /** Key factors that influenced the score */
  factors: string[]
  /** One-sentence summary */
  summary: string
}

/** Score for an individual category */
interface CategoryScore {
  /** Points contributed to total (higher = worse) */
  points: number
  /** Maximum possible points for this category */
  maxPoints: number
  /** Specific issues found */
  issues: string[]
}

// ============================================================================
// Known Tracker Classifications
// ============================================================================

/** High-risk trackers that significantly impact privacy */
const HIGH_RISK_TRACKERS: RegExp[] = [
  // Cross-site tracking / Fingerprinting
  /fingerprint|fpjs|fingerprintjs/i,
  /clarity\.ms/,
  /fullstory/i,
  /hotjar/i,
  /logrocket/i,
  /session.?replay/i,
  /mouseflow/i,
  /smartlook/i,
  /luckyorange/i,
  /inspectlet/i,
  
  // Data brokers / DMPs
  /bluekai/i,
  /oracle.*cloud/i,
  /liveramp/i,
  /acxiom/i,
  /experian/i,
  /lotame/i,
  /neustar/i,
  /tapad/i,
  /drawbridge/i,
  /crossdevice/i,
  /id5/i,
  /unified.?id/i,
  /thetradedesk/i,
  /adsrvr\.org/,
]

/** Major advertising networks */
const ADVERTISING_TRACKERS: RegExp[] = [
  /doubleclick/i,
  /googlesyndication/i,
  /googleadservices/i,
  /google.*(ads|adwords)/i,
  /facebook.*pixel|fbevents|connect\.facebook/i,
  /amazon-adsystem/i,
  /criteo/i,
  /adnxs|appnexus/i,
  /rubiconproject|magnite/i,
  /pubmatic/i,
  /openx/i,
  /outbrain/i,
  /taboola/i,
  /bidswitch/i,
  /casalemedia|indexexchange/i,
  /adroll/i,
  /bing.*ads|bat\.bing/i,
  /tiktok.*pixel|analytics\.tiktok/i,
  /snapchat.*pixel|sc-static/i,
  /pinterest.*tag|pinimg.*tag/i,
  /linkedin.*insight|snap\.licdn/i,
  /twitter.*pixel|ads-twitter/i,
  /media\.net/i,
  /33across/i,
  /sharethrough/i,
]

/** Social media trackers */
const SOCIAL_MEDIA_TRACKERS: RegExp[] = [
  /facebook\.net|facebook\.com.*sdk|fbcdn/i,
  /twitter\.com.*widgets|platform\.twitter/i,
  /linkedin\.com.*insight|platform\.linkedin/i,
  /pinterest\.com.*pinit/i,
  /tiktok\.com/i,
  /instagram\.com/i,
  /snapchat\.com/i,
  /reddit\.com.*pixel/i,
  /addthis/i,
  /sharethis/i,
  /addtoany/i,
]

/** Standard analytics (lower risk than session replay) */
const ANALYTICS_TRACKERS: RegExp[] = [
  /google-analytics|googletagmanager.*gtag/i,
  /analytics\.google/i,
  /segment\.com|segment\.io/i,
  /amplitude/i,
  /mixpanel/i,
  /heap\.io|heapanalytics/i,
  /matomo|piwik/i,
  /chartbeat/i,
  /parsely/i,
  /newrelic/i,
  /datadog/i,
  /sentry\.io/i,
]

/** Cookie names that indicate tracking */
const TRACKING_COOKIE_PATTERNS: RegExp[] = [
  /^_ga|^_gid|^_gat/i,                    // Google Analytics
  /^_fbp|^_fbc/i,                          // Facebook
  /^_gcl/i,                                // Google Ads
  /^_uet/i,                                // Bing Ads
  /^__utm/i,                               // UTM tracking
  /^_hjid|^_hjSession/i,                   // Hotjar
  /^_clck|^_clsk/i,                        // Microsoft Clarity
  /^IDE|^DSID|^FLC/i,                      // DoubleClick
  /^NID|^SID|^HSID|^SSID|^APISID|^SAPISID/i, // Google auth/tracking
  /^fr$/i,                                 // Facebook
  /^personalization_id|^guest_id/i,        // Twitter
  /^lidc|^bcookie|^bscookie/i,             // LinkedIn
  /criteo/i,
  /adroll/i,
  /taboola/i,
  /outbrain/i,
]

/** Cookie names that indicate fingerprinting */
const FINGERPRINT_COOKIE_PATTERNS: RegExp[] = [
  /fingerprint/i,
  /fpjs/i,
  /device.?id/i,
  /browser.?id/i,
  /visitor.?id/i,
  /unique.?id/i,
  /client.?id/i,
]

/** Storage keys that indicate tracking */
const TRACKING_STORAGE_PATTERNS: RegExp[] = [
  /amplitude/i,
  /segment/i,
  /mixpanel/i,
  /analytics/i,
  /tracking/i,
  /visitor/i,
  /user.?id/i,
  /session.?id/i,
  /fingerprint/i,
  /device.?id/i,
]

/** Sensitive data categories in consent */
const SENSITIVE_PURPOSES: RegExp[] = [
  /politic|political/i,
  /health|medical/i,
  /religio/i,
  /ethnic|racial/i,
  /sexual|sex/i,
  /biometric/i,
  /genetic/i,
  /location|geo|gps/i,
  /child|minor|kid/i,
  /financial|credit|income/i,
]

// ============================================================================
// Scoring Functions
// ============================================================================

/**
 * Calculate the complete privacy score breakdown.
 * 
 * @param cookies - Captured cookies
 * @param scripts - Detected scripts  
 * @param networkRequests - Network requests made
 * @param localStorage - localStorage items
 * @param sessionStorage - sessionStorage items
 * @param analyzedUrl - URL being analyzed
 * @param consentDetails - Optional consent dialog info
 * @returns Complete score breakdown with factors
 */
export function calculatePrivacyScore(
  cookies: TrackedCookie[],
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[],
  localStorage: StorageItem[],
  sessionStorage: StorageItem[],
  analyzedUrl: string,
  consentDetails?: ConsentDetails | null
): PrivacyScoreBreakdown {
  log.info('Calculating privacy score', { 
    cookies: cookies.length, 
    scripts: scripts.length,
    requests: networkRequests.length 
  })

  // Get site hostname and base domain for first-party detection
  let siteHostname = ''
  let baseDomain = ''
  try {
    const urlObj = new URL(analyzedUrl)
    siteHostname = urlObj.hostname.replace(/^www\./, '').toLowerCase()
    
    // Handle multi-part TLDs (co.uk, com.au, etc.)
    const parts = siteHostname.split('.')
    if (parts.length >= 2) {
      // Check for known two-part TLDs
      const twoPartTlds = ['co.uk', 'com.au', 'co.nz', 'co.jp', 'com.br', 'co.in', 'org.uk', 'net.uk', 'gov.uk']
      const lastTwo = parts.slice(-2).join('.')
      if (twoPartTlds.includes(lastTwo) && parts.length >= 3) {
        baseDomain = parts.slice(-3).join('.')
      } else {
        baseDomain = parts.slice(-2).join('.')
      }
    } else {
      baseDomain = siteHostname
    }
  } catch {
    siteHostname = analyzedUrl
    baseDomain = analyzedUrl
  }

  // Calculate each category
  const cookieScore = calculateCookieScore(cookies, baseDomain)
  const thirdPartyScore = calculateThirdPartyScore(networkRequests, scripts, baseDomain)
  const dataCollectionScore = calculateDataCollectionScore(localStorage, sessionStorage, networkRequests)
  const fingerprintScore = calculateFingerprintScore(cookies, scripts, networkRequests)
  const advertisingScore = calculateAdvertisingScore(scripts, networkRequests, cookies)
  const socialMediaScore = calculateSocialMediaScore(scripts, networkRequests)
  const sensitiveDataScore = calculateSensitiveDataScore(consentDetails, scripts, networkRequests)
  const consentScore = calculateConsentScore(consentDetails, cookies, scripts)

  // Calculate total (sum of points, capped at 100)
  // Max theoretical: cookies(15) + thirdParty(20) + data(10) + fingerprint(20) + ads(15) + social(10) + sensitive(10) + consent(25) = 125
  const rawTotal = 
    cookieScore.points +
    thirdPartyScore.points +
    dataCollectionScore.points +
    fingerprintScore.points +
    advertisingScore.points +
    socialMediaScore.points +
    sensitiveDataScore.points +
    consentScore.points

  const totalScore = Math.min(100, Math.round(rawTotal))

  // Collect significant factors - prioritize consent/partners and fingerprinting as they're most important
  const factors: string[] = []
  
  // Consent issues (partners, pre-consent tracking) are most important
  if (consentScore.issues.length > 0) factors.push(...consentScore.issues.slice(0, 2))
  // Cross-site/fingerprinting is very serious
  if (fingerprintScore.issues.length > 0) factors.push(...fingerprintScore.issues.slice(0, 2))
  // Third-party tracking
  if (thirdPartyScore.issues.length > 0) factors.push(...thirdPartyScore.issues.slice(0, 2))
  // Advertising
  if (advertisingScore.issues.length > 0) factors.push(...advertisingScore.issues.slice(0, 1))
  // Cookies
  if (cookieScore.issues.length > 0) factors.push(...cookieScore.issues.slice(0, 1))
  // Social media
  if (socialMediaScore.issues.length > 0) factors.push(...socialMediaScore.issues.slice(0, 1))
  // Sensitive data
  if (sensitiveDataScore.issues.length > 0) factors.push(...sensitiveDataScore.issues.slice(0, 1))

  // Generate summary - use full hostname for display
  const summary = generateSummary(siteHostname, totalScore, factors)

  log.success('Privacy score calculated', { 
    totalScore,
    consent: consentScore.points,
    fingerprinting: fingerprintScore.points,
    thirdParty: thirdPartyScore.points,
    advertising: advertisingScore.points,
    cookies: cookieScore.points
  })

  return {
    totalScore,
    categories: {
      cookies: cookieScore,
      thirdPartyTrackers: thirdPartyScore,
      dataCollection: dataCollectionScore,
      fingerprinting: fingerprintScore,
      advertising: advertisingScore,
      socialMedia: socialMediaScore,
      sensitiveData: sensitiveDataScore,
      consent: consentScore,
    },
    factors,
    summary,
  }
}

/**
 * Calculate cookie-related privacy score.
 * Max 15 points.
 * 
 * Scoring rationale:
 * - Any cookies beyond essential = privacy impact
 * - Third-party cookies = cross-site tracking concern
 * - Known tracking cookies = definite privacy issue
 */
function calculateCookieScore(cookies: TrackedCookie[], baseDomain: string): CategoryScore {
  const issues: string[] = []
  let points = 0

  // Count third-party cookies
  const thirdPartyCookies = cookies.filter(c => {
    const cookieDomain = c.domain.replace(/^\./, '')
    return !cookieDomain.endsWith(baseDomain)
  })
  
  // Count tracking cookies
  const trackingCookies = cookies.filter(c => 
    TRACKING_COOKIE_PATTERNS.some(p => p.test(c.name))
  )

  // Count long-lived cookies (> 1 year)
  const now = Date.now() / 1000
  const longLivedCookies = cookies.filter(c => 
    c.expires > 0 && (c.expires - now) > 365 * 24 * 60 * 60
  )

  // Scoring - more aggressive thresholds
  if (cookies.length > 30) {
    points += 5
    issues.push(`${cookies.length} cookies set (heavy tracking)`)
  } else if (cookies.length > 15) {
    points += 4
    issues.push(`${cookies.length} cookies set`)
  } else if (cookies.length > 5) {
    points += 2
  }

  if (thirdPartyCookies.length > 5) {
    points += 5
    issues.push(`${thirdPartyCookies.length} third-party cookies`)
  } else if (thirdPartyCookies.length > 2) {
    points += 3
    issues.push(`${thirdPartyCookies.length} third-party cookies`)
  } else if (thirdPartyCookies.length > 0) {
    points += 2
  }

  if (trackingCookies.length > 3) {
    points += 5
    issues.push(`${trackingCookies.length} known tracking cookies`)
  } else if (trackingCookies.length > 0) {
    points += 3
    issues.push(`${trackingCookies.length} tracking cookies detected`)
  }

  if (longLivedCookies.length > 3) {
    points += 2
    issues.push(`${longLivedCookies.length} cookies persist over 1 year`)
  } else if (longLivedCookies.length > 0) {
    points += 1
  }

  return { points: Math.min(15, points), maxPoints: 15, issues }
}

/**
 * Calculate third-party tracker score.
 * Max 20 points.
 * 
 * This is the most important category - third-party requests
 * indicate data being shared with external companies.
 */
function calculateThirdPartyScore(
  networkRequests: NetworkRequest[], 
  scripts: TrackedScript[],
  baseDomain: string
): CategoryScore {
  const issues: string[] = []
  let points = 0

  // Get unique third-party domains
  const thirdPartyDomains = new Set<string>()
  
  for (const req of networkRequests) {
    if (req.isThirdParty) {
      thirdPartyDomains.add(req.domain)
    }
  }
  
  for (const script of scripts) {
    if (!script.domain.endsWith(baseDomain)) {
      thirdPartyDomains.add(script.domain)
    }
  }

  // Count third-party requests
  const thirdPartyRequests = networkRequests.filter(r => r.isThirdParty)

  // Identify known trackers from our database
  const knownTrackers = new Set<string>()
  const allUrls = [
    ...scripts.map(s => s.url),
    ...networkRequests.map(r => r.url)
  ]

  const trackingScripts = getTrackingScripts()
  for (const url of allUrls) {
    for (const pattern of trackingScripts) {
      if (pattern.pattern.test(url)) {
        const match = url.match(/https?:\/\/([^/]+)/)?.[1]
        if (match) knownTrackers.add(match)
        break
      }
    }
  }

  // Scoring - any third-party presence is significant
  if (thirdPartyDomains.size > 20) {
    points += 10
    issues.push(`${thirdPartyDomains.size} third-party domains contacted`)
  } else if (thirdPartyDomains.size > 10) {
    points += 7
    issues.push(`${thirdPartyDomains.size} third-party domains`)
  } else if (thirdPartyDomains.size > 5) {
    points += 5
    issues.push(`${thirdPartyDomains.size} third-party domains`)
  } else if (thirdPartyDomains.size > 0) {
    points += 3
  }

  if (thirdPartyRequests.length > 100) {
    points += 5
    issues.push(`${thirdPartyRequests.length} third-party requests`)
  } else if (thirdPartyRequests.length > 50) {
    points += 3
  } else if (thirdPartyRequests.length > 20) {
    points += 2
  }

  // Known trackers are definite privacy concerns
  if (knownTrackers.size > 8) {
    points += 8
    issues.push(`${knownTrackers.size} known tracking services identified`)
  } else if (knownTrackers.size > 4) {
    points += 6
    issues.push(`${knownTrackers.size} known tracking services`)
  } else if (knownTrackers.size > 1) {
    points += 4
    issues.push(`${knownTrackers.size} known trackers`)
  } else if (knownTrackers.size > 0) {
    points += 2
  }

  return { points: Math.min(20, points), maxPoints: 20, issues }
}

/**
 * Calculate data collection score based on storage, beacons, and analytics.
 * Max 10 points.
 */
function calculateDataCollectionScore(
  localStorage: StorageItem[],
  sessionStorage: StorageItem[],
  networkRequests: NetworkRequest[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  // Check localStorage
  const trackingStorageItems = localStorage.filter(item =>
    TRACKING_STORAGE_PATTERNS.some(p => p.test(item.key))
  )

  // Check for tracking beacons/pixels
  const beaconRequests = networkRequests.filter(r =>
    r.resourceType === 'image' && r.isThirdParty && r.url.length > 200
  )

  // Check for data exfiltration via POST to third parties
  const thirdPartyPosts = networkRequests.filter(r =>
    r.method === 'POST' && r.isThirdParty
  )

  // Check for analytics scripts
  const analyticsUrls = networkRequests.filter(r =>
    ANALYTICS_TRACKERS.some(p => p.test(r.url))
  )

  // Scoring
  if (localStorage.length > 15) {
    points += 3
    issues.push(`${localStorage.length} localStorage items (extensive data storage)`)
  } else if (localStorage.length > 5) {
    points += 2
  }

  if (trackingStorageItems.length > 0) {
    points += 3
    issues.push(`${trackingStorageItems.length} tracking-related storage items`)
  }

  if (beaconRequests.length > 10) {
    points += 4
    issues.push(`${beaconRequests.length} tracking beacons/pixels detected`)
  } else if (beaconRequests.length > 3) {
    points += 2
  }

  if (thirdPartyPosts.length > 5) {
    points += 3
    issues.push(`${thirdPartyPosts.length} data submissions to third parties`)
  } else if (thirdPartyPosts.length > 0) {
    points += 1
  }

  // Analytics presence adds points
  if (analyticsUrls.length > 0) {
    points += 2
    issues.push('Analytics tracking active')
  }

  return { points: Math.min(10, points), maxPoints: 10, issues }
}

/**
 * Calculate fingerprinting and cross-site tracking risk score.
 * Max 20 points - increased due to severity of cross-site tracking.
 * 
 * Cross-site tracking and fingerprinting are the most invasive
 * forms of tracking as they follow you across the web.
 */
function calculateFingerprintScore(
  cookies: TrackedCookie[],
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  const allUrls = [
    ...scripts.map(s => s.url),
    ...networkRequests.map(r => r.url)
  ]

  // Check for fingerprinting services
  const fingerprintServices: string[] = []
  for (const url of allUrls) {
    for (const pattern of HIGH_RISK_TRACKERS) {
      if (pattern.test(url)) {
        const match = url.match(/https?:\/\/([^/]+)/)?.[1]
        if (match && !fingerprintServices.includes(match)) {
          fingerprintServices.push(match)
        }
      }
    }
  }

  // Check for session replay tools - these record everything
  const sessionReplayPatterns = [/hotjar/i, /fullstory/i, /logrocket/i, /clarity\.ms/i, /mouseflow/i, /smartlook/i, /luckyorange/i, /inspectlet/i]
  const sessionReplayServices = fingerprintServices.filter(s =>
    sessionReplayPatterns.some(p => p.test(s))
  )

  // Check for cross-device/identity tracking
  const crossDevicePatterns = [/liveramp/i, /tapad/i, /drawbridge/i, /unified.?id/i, /id5/i, /thetradedesk/i, /lotame/i, /zeotap/i]
  const crossDeviceTrackers = allUrls.filter(url =>
    crossDevicePatterns.some(p => p.test(url))
  )

  // Check for fingerprint cookies
  const fingerprintCookies = cookies.filter(c =>
    FINGERPRINT_COOKIE_PATTERNS.some(p => p.test(c.name))
  )

  // Scoring - session replay is severe
  if (sessionReplayServices.length > 1) {
    points += 12
    issues.push(`Multiple session replay tools (${sessionReplayServices.join(', ')}) - your interactions are recorded`)
  } else if (sessionReplayServices.length > 0) {
    points += 10
    issues.push(`Session replay active (${sessionReplayServices[0]}) - your mouse movements and clicks are recorded`)
  }

  // Cross-device tracking is very invasive
  if (crossDeviceTrackers.length > 0) {
    points += 8
    issues.push('Cross-device identity tracking detected - you are tracked across all your devices')
  }

  // Other fingerprinting services
  const otherFingerprinters = fingerprintServices.length - sessionReplayServices.length
  if (otherFingerprinters > 3) {
    points += 6
    issues.push(`${otherFingerprinters} fingerprinting services identified`)
  } else if (otherFingerprinters > 0) {
    points += 4
    issues.push(`${otherFingerprinters} fingerprinting/tracking services`)
  }

  if (fingerprintCookies.length > 0) {
    points += 3
    issues.push(`${fingerprintCookies.length} fingerprint-related cookies`)
  }

  return { points: Math.min(20, points), maxPoints: 20, issues }
}

/**
 * Calculate advertising tracker score.
 * Max 15 points.
 * 
 * Ad networks are a major source of tracking - they share data
 * across sites and build detailed profiles.
 */
function calculateAdvertisingScore(
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[],
  cookies: TrackedCookie[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  const allUrls = [
    ...scripts.map(s => s.url),
    ...networkRequests.map(r => r.url)
  ]

  // Identify ad networks
  const adNetworks = new Set<string>()
  for (const url of allUrls) {
    for (const pattern of ADVERTISING_TRACKERS) {
      if (pattern.test(url)) {
        // Extract a readable name
        if (/doubleclick|googlesyndication|googleadservices/i.test(url)) adNetworks.add('Google Ads')
        else if (/facebook|fbevents/i.test(url)) adNetworks.add('Facebook Ads')
        else if (/amazon-adsystem/i.test(url)) adNetworks.add('Amazon Ads')
        else if (/criteo/i.test(url)) adNetworks.add('Criteo')
        else if (/adnxs|appnexus/i.test(url)) adNetworks.add('Xandr/AppNexus')
        else if (/taboola/i.test(url)) adNetworks.add('Taboola')
        else if (/outbrain/i.test(url)) adNetworks.add('Outbrain')
        else if (/thetradedesk|adsrvr/i.test(url)) adNetworks.add('The Trade Desk')
        else if (/linkedin/i.test(url)) adNetworks.add('LinkedIn Ads')
        else if (/twitter|ads-twitter/i.test(url)) adNetworks.add('Twitter Ads')
        else if (/tiktok/i.test(url)) adNetworks.add('TikTok Ads')
        else if (/pinterest/i.test(url)) adNetworks.add('Pinterest Ads')
        else if (/snapchat|sc-static/i.test(url)) adNetworks.add('Snapchat Ads')
        else {
          const domain = url.match(/https?:\/\/([^/]+)/)?.[1]
          if (domain) adNetworks.add(domain)
        }
        break
      }
    }
  }

  // Scoring - any ad network is a privacy concern
  if (adNetworks.size > 6) {
    points += 12
    issues.push(`${adNetworks.size} advertising networks: ${[...adNetworks].slice(0, 5).join(', ')}...`)
  } else if (adNetworks.size > 3) {
    points += 8
    issues.push(`${adNetworks.size} ad networks: ${[...adNetworks].join(', ')}`)
  } else if (adNetworks.size > 1) {
    points += 5
    issues.push(`${adNetworks.size} ad networks: ${[...adNetworks].join(', ')}`)
  } else if (adNetworks.size > 0) {
    points += 3
    issues.push(`Ad network detected: ${[...adNetworks][0]}`)
  }

  // Check for retargeting cookies
  const retargetingCookies = cookies.filter(c =>
    /criteo|adroll|retarget/i.test(c.name) || /criteo|adroll/i.test(c.domain)
  )
  if (retargetingCookies.length > 0) {
    points += 4
    issues.push('Retargeting cookies present (ads follow you)')
  }

  // Programmatic ad bidding - indicates real-time data sharing
  const biddingIndicators = allUrls.filter(url =>
    /prebid|bidswitch|openx|pubmatic|magnite|rubicon|indexexchange|casalemedia/i.test(url)
  )
  if (biddingIndicators.length > 0) {
    points += 4
    issues.push('Real-time ad bidding detected')
  }

  return { points: Math.min(15, points), maxPoints: 15, issues }
}

/**
 * Calculate social media tracker score.
 * Max 10 points.
 */
function calculateSocialMediaScore(
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  const allUrls = [
    ...scripts.map(s => s.url),
    ...networkRequests.map(r => r.url)
  ]

  // Identify social media trackers
  const socialTrackers = new Set<string>()
  for (const url of allUrls) {
    for (const pattern of SOCIAL_MEDIA_TRACKERS) {
      if (pattern.test(url)) {
        if (/facebook|fbcdn/i.test(url)) socialTrackers.add('Facebook')
        else if (/twitter/i.test(url)) socialTrackers.add('Twitter/X')
        else if (/linkedin/i.test(url)) socialTrackers.add('LinkedIn')
        else if (/pinterest/i.test(url)) socialTrackers.add('Pinterest')
        else if (/tiktok/i.test(url)) socialTrackers.add('TikTok')
        else if (/instagram/i.test(url)) socialTrackers.add('Instagram')
        else if (/snapchat/i.test(url)) socialTrackers.add('Snapchat')
        else if (/reddit/i.test(url)) socialTrackers.add('Reddit')
        else if (/addthis|sharethis|addtoany/i.test(url)) socialTrackers.add('Social sharing widgets')
        break
      }
    }
  }

  // Scoring - social tracking is significant privacy concern
  if (socialTrackers.size > 3) {
    points += 10
    issues.push(`${socialTrackers.size} social media trackers: ${[...socialTrackers].join(', ')}`)
  } else if (socialTrackers.size > 1) {
    points += 6
    issues.push(`Social media tracking: ${[...socialTrackers].join(', ')}`)
  } else if (socialTrackers.size > 0) {
    points += 4
    issues.push(`${[...socialTrackers].join(', ')} tracking present`)
  }

  // Social plugins (like buttons, embeds)
  const socialPlugins = allUrls.filter(url =>
    /platform\.(twitter|facebook|linkedin)|widgets\.(twitter|facebook)/i.test(url)
  )
  if (socialPlugins.length > 0) {
    points += 3
    issues.push('Social media plugins embedded (tracks even without interaction)')
  }

  return { points: Math.min(10, points), maxPoints: 10, issues }
}

/**
 * Calculate sensitive data tracking score.
 * Max 10 points.
 */
function calculateSensitiveDataScore(
  consentDetails: ConsentDetails | null | undefined,
  scripts: TrackedScript[],
  networkRequests: NetworkRequest[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  // Check consent purposes for sensitive categories
  if (consentDetails) {
    const allPurposes = [
      ...consentDetails.purposes,
      ...consentDetails.categories.map(c => c.description),
      consentDetails.rawText
    ].join(' ')

    for (const pattern of SENSITIVE_PURPOSES) {
      if (pattern.test(allPurposes)) {
        points += 2
        if (/location|geo|gps/i.test(pattern.source)) {
          issues.push('Location data collection disclosed')
        } else if (/politic/i.test(pattern.source)) {
          issues.push('Political interest tracking disclosed')
        } else if (/health|medical/i.test(pattern.source)) {
          issues.push('Health-related data collection disclosed')
        } else if (/financial|credit/i.test(pattern.source)) {
          issues.push('Financial data tracking disclosed')
        }
        break // Only count once per type
      }
    }
  }

  // Check for geolocation tracking
  const allUrls = [
    ...scripts.map(s => s.url),
    ...networkRequests.map(r => r.url)
  ]
  
  const geoTracking = allUrls.some(url => /geo|location|ip.?info|ipify|ipapi/i.test(url))
  if (geoTracking) {
    points += 3
    issues.push('Geolocation/IP tracking detected')
  }

  // Check for identity resolution services
  const identityServices = allUrls.some(url => 
    /liveramp|unified.?id|id5|lotame|thetradedesk.*unified/i.test(url)
  )
  if (identityServices) {
    points += 4
    issues.push('Cross-site identity tracking (identity resolution service)')
  }

  return { points: Math.min(10, points), maxPoints: 10, issues }
}

/**
 * Calculate consent-related issues score.
 * Max 25 points - this is now a major category due to partner importance.
 * 
 * Heavy weighting on:
 * - Number of data sharing partners (scaled by count)
 * - Partner risk classification (data brokers, identity trackers score highest)
 * - Tracking that happens before consent is given
 */
function calculateConsentScore(
  consentDetails: ConsentDetails | null | undefined,
  cookies: TrackedCookie[],
  scripts: TrackedScript[]
): CategoryScore {
  const issues: string[] = []
  let points = 0

  // Check for tracking before consent - this is a serious violation
  const trackingPatterns = getTrackingScripts()
  const trackingScripts = scripts.filter(s => 
    trackingPatterns.some(t => t.pattern.test(s.url))
  )
  
  if (trackingScripts.length > 5) {
    points += 10
    issues.push(`${trackingScripts.length} tracking scripts loaded BEFORE consent given (violation)`)
  } else if (trackingScripts.length > 2) {
    points += 7
    issues.push(`${trackingScripts.length} tracking scripts loaded before consent`)
  } else if (trackingScripts.length > 0) {
    points += 4
    issues.push('Tracking active before consent given')
  }

  if (!consentDetails) {
    // No consent dialog - check if tracking exists anyway
    const hasTracking = cookies.length > 5 || trackingScripts.length > 0
    if (hasTracking) {
      points += 8
      issues.push('Tracking present without visible consent dialog')
    }
    return { points: Math.min(25, points), maxPoints: 25, issues }
  }

  // Partner count scoring - heavily weighted, scaled by count
  const partnerCount = consentDetails.partners.length
  
  if (partnerCount > 500) {
    points += 15
    issues.push(`${partnerCount} partners share your data (extreme)`)
  } else if (partnerCount > 300) {
    points += 12
    issues.push(`${partnerCount} partners share your data (massive)`)
  } else if (partnerCount > 150) {
    points += 10
    issues.push(`${partnerCount} partners share your data (excessive)`)
  } else if (partnerCount > 75) {
    points += 8
    issues.push(`${partnerCount} partners share your data`)
  } else if (partnerCount > 30) {
    points += 6
    issues.push(`${partnerCount} data sharing partners`)
  } else if (partnerCount > 10) {
    points += 4
    issues.push(`${partnerCount} data sharing partners`)
  } else if (partnerCount > 0) {
    points += 2
  }

  // Partner risk classification - add extra points for dangerous partners
  if (partnerCount > 0) {
    const riskSummary = getPartnerRiskSummary(consentDetails.partners)
    
    // Data brokers and identity trackers are worst
    if (riskSummary.criticalCount > 5) {
      points += 8
      issues.push(`${riskSummary.criticalCount} data brokers/identity trackers identified`)
    } else if (riskSummary.criticalCount > 2) {
      points += 5
      issues.push(`${riskSummary.criticalCount} data brokers among partners`)
    } else if (riskSummary.criticalCount > 0) {
      points += 3
      issues.push(`Data broker detected: ${riskSummary.worstPartners[0]}`)
    }
    
    // High risk partners (major ad networks, session replay)
    if (riskSummary.highCount > 10) {
      points += 5
      issues.push(`${riskSummary.highCount} high-risk advertising/tracking partners`)
    } else if (riskSummary.highCount > 5) {
      points += 3
    } else if (riskSummary.highCount > 0) {
      points += 2
    }
  }

  // Check for vague/misleading purposes  
  const vagueTerms = /legitimate interest|necessary|essential|basic|functional/i
  const vaguePurposes = consentDetails.purposes.filter(p => vagueTerms.test(p))
  if (vaguePurposes.length > 2) {
    points += 3
    issues.push('Consent uses vague terms to justify tracking')
  }

  return { points: Math.min(25, points), maxPoints: 25, issues }
}

/**
 * Generate a human-readable summary sentence.
 */
function generateSummary(siteName: string, score: number, factors: string[]): string {
  let severity: string
  let description: string

  if (score >= 80) {
    severity = 'extensive'
    description = 'with aggressive cross-site tracking and data sharing'
  } else if (score >= 60) {
    severity = 'significant'
    description = 'with multiple advertising networks and third-party trackers'
  } else if (score >= 40) {
    severity = 'moderate'
    description = 'with standard analytics and some advertising trackers'
  } else if (score >= 20) {
    severity = 'limited'
    description = 'with basic analytics and minimal third-party presence'
  } else {
    severity = 'minimal'
    description = 'with privacy-respecting practices'
  }

  // Add specific detail if available
  const topFactor = factors[0]?.toLowerCase() || ''
  
  if (topFactor.includes('session replay')) {
    description = 'including session recording that captures your interactions'
  } else if (topFactor.includes('fingerprint')) {
    description = 'including device fingerprinting for cross-site tracking'
  } else if (topFactor.includes('ad network')) {
    description = `including ${topFactor}`
  }

  return `${siteName} has ${severity} tracking ${description}.`
}
