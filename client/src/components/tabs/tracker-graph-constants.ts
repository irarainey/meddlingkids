/**
 * Shared types, constants, and helpers for the tracker-graph feature.
 */

import type { SimulationNodeDatum, SimulationLinkDatum } from 'd3'

// ============================================================================
// Types
// ============================================================================

/** Category label used to colour-code graph nodes. */
export type TrackerCategory = 'origin' | 'first-party' | 'analytics' | 'advertising' | 'social' | 'identity' | 'replay' | 'consent' | 'cdn' | 'other'

/** Available graph view modes. */
export type ViewMode = 'all' | 'third-party' | 'pre-consent'

/** A node in the tracker relationship graph. */
export interface GraphNode extends SimulationNodeDatum {
  id: string
  label: string
  category: TrackerCategory
  requestCount: number
  isThirdParty: boolean
}

/** A directed edge between two domains. */
export interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  sourceId: string
  targetId: string
  weight: number
  preConsent: boolean
}

// ============================================================================
// Colours & labels
// ============================================================================

export const CATEGORY_COLOURS: Record<TrackerCategory, string> = {
  origin: '#22c55e',
  'first-party': '#86efac',
  analytics: '#3b82f6',
  advertising: '#ef4444',
  social: '#a855f7',
  identity: '#f59e0b',
  replay: '#ec4899',
  consent: '#06b6d4',
  cdn: '#14b8a6',
  other: '#6b7280',
}

export const CATEGORY_LABELS: Record<TrackerCategory, string> = {
  origin: 'Origin Site',
  'first-party': 'First Party',
  analytics: 'Analytics',
  advertising: 'Advertising',
  social: 'Social Media',
  identity: 'Identity Resolution',
  replay: 'Session Replay',
  consent: 'Consent Management',
  cdn: 'CDN / Infrastructure',
  other: 'Other',
}

// ============================================================================
// Domain fragment arrays
// ============================================================================

/**
 * Known session-replay / experience-analytics domain fragments.
 * Sourced from `tracker_patterns.py` SESSION_REPLAY_PATTERNS and
 * BEHAVIOURAL_TRACKING_PATTERNS.
 */
export const REPLAY_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
  // Session replay
  'hotjar.com',
  'fullstory.com',
  'clarity.ms',
  'logrocket.io', 'lr-ingest.io', 'lr-in.com',
  'mouseflow.com',
  'smartlook.com',
  'luckyorange.com', 'luckyorange.net',
  'inspectlet.com',
  // Experience analytics / heatmap platforms
  'contentsquare.com', 'contentsquare.net',
  'crazyegg.com',
  'clicktale.com', 'clicktale.net',
  'decibelinsight.com',
  'glassboxdigital.com',
  'quantummetric.com',
]

/**
 * Known CMP domain fragments used to classify consent-management nodes.
 * Sourced from `consent-platforms.json` iframe patterns.
 */
export const CMP_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
  // Sourcepoint
  'sourcepoint.mgr.consensu.org', 'notice.sp-prod.net', 'cdn.privacy-mgmt.com', 'sp-prod.net',
  // InMobi / Quantcast Choice
  'quantcast.mgr.consensu.org',
  // Cookiebot
  'consent.cookiebot.com', 'consentcdn.cookiebot.com',
  // Didomi
  'sdk.privacy-center.org',
  // TrustArc
  'consent.trustarc.com', 'consent-pref.trustarc.com', 'consent.truste.com',
  // Usercentrics
  'app.usercentrics.eu',
  // consentmanager
  'delivery.consentmanager.net', 'cdn.consentmanager.net', 'app.consentmanager.net',
  'consentmanager.mgr.consensu.org',
  // iubenda
  'cdn.iubenda.com',
  // Google Funding Choices
  'fundingchoicesmessages.google.com', 'consent.google.com',
  // Termly
  'app.termly.io',
  // Sirdata
  'sddan.com',
  // Crownpeak / Evidon
  'evidon.com', 'betrad.com',
  // Commanders Act / TrustCommander
  'cdn.trustcommander.net',
]

/**
 * Known CDN, content delivery, and infrastructure domain fragments.
 * These are classified as "Content" by Disconnect (→ "other") but are
 * infrastructure services, not trackers.  Giving them their own colour
 * keeps the graph informative without misrepresenting them as unknown.
 */
export const CDN_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
  // Google infrastructure (NOT analytics/ads — those are in Disconnect as Advertising/Analytics)
  'googleapis.com', 'gstatic.com', 'googleusercontent.com',
  'googlevideo.com', 'ggpht.com', 'google.com', 'google.co.uk',
  // YouTube (video hosting)
  'youtube.com', 'ytimg.com', 'youtube-nocookie.com', 'youtu.be',
  // Microsoft infrastructure (NOT clarity.ms — that's session replay)
  'microsoft.com', 'msn.com', 'azure.com', 'azurefd.net',
  'msecnd.net', 'aspnetcdn.com', 'live.com', 'office.com',
  // Amazon / AWS
  'cloudfront.net', 'amazonaws.com', 'amazon.com', 'media-amazon.com',
  // Cloudflare
  'cloudflare.com', 'cloudflarestream.com', 'cdnjs.cloudflare.com',
  // Akamai
  'akamaihd.net', 'akamaized.net', 'akstat.io',
  'akamai.com', 'akamai.net', 'edgekey.net', 'edgesuite.net',
  // Fastly
  'fastly.net', 'fastlylb.net', 'fastly.com',
  // Other CDNs
  'jsdelivr.net', 'unpkg.com', 'cdnjs.com', 'bootstrapcdn.com',
  'stackpathcdn.com', 'stackpathdns.com', 'bunny.net', 'bunnycdn.b-cdn.net',
  'imgix.net', 'cloudinary.com',
  // Fonts / design assets
  'typekit.net', 'typekit.com', 'fontawesome.com',
  'fonts.googleapis.com', 'fonts.gstatic.com',
  // WordPress / Automattic
  'wp.com', 'gravatar.com', 'wordpress.com',
  // Shopify
  'cdn.shopify.com', 'shopifyapps.com', 'shopifysvc.com', 'shopify.com',
  // Payment / commerce (functional, not tracking)
  'stripe.com', 'paypal.com', 'paypalobjects.com', 'klarna.com',
  'klarnaservices.com', 'checkout.com', 'afterpay.com',
  // Security / anti-fraud / captcha
  'recaptcha.net', 'hcaptcha.com', 'arkoselabs.com',
  'datadome.co', 'captcha-delivery.com', 'geocomply.com',
  // Video platforms
  'vimeo.com', 'vimeocdn.com', 'jwplayer.com', 'jwplatform.com',
  'jwpcdn.com', 'jwpsrv.com', 'brightcove.com', 'brightcove.net',
  'bitmovin.com', 'mux.com', 'wistia.com', 'video-cdn.net',
  // Yahoo / AOL
  'yahoo.com', 'yahooapis.com', 'yimg.com', 'aolcdn.com',
  // Zendesk / support widgets
  'zendesk.com', 'zdassets.com',
  // Salesforce
  'salesforce.com', 'salesforceliveagent.com',
  // Apple
  'apple.com', 'mzstatic.com', 'icloud.com',
  // Other infrastructure
  'scene7.com', 'kaltura.com',
]

// ============================================================================
// First-party aliases
// ============================================================================

/**
 * Cross-domain first-party aliases.
 *
 * Some publishers use separate registrable domains for asset
 * delivery, APIs, or regional sites that are functionally
 * first-party but have a different base domain.  This map
 * lets the graph recognise them when the origin matches.
 *
 * Key   = base domain of the origin site.
 * Value = additional base domains that should be treated as
 *         first-party for that origin.
 */
export const FIRST_PARTY_ALIASES: Readonly<Record<string, ReadonlyArray<string>>> = {
  'bbc.co.uk': ['bbci.co.uk'],
  'theguardian.com': ['guim.co.uk', 'guardianapis.com'],
}

// ============================================================================
// Domain keyword arrays
// ============================================================================

/**
 * Domain keyword fragments for client-side classification fallback.
 * Used when a domain isn't in the structured report and doesn't match
 * the replay or CMP fragment lists.  Checked before falling back to 'other'.
 *
 * Each entry is a tuple of [keyword-fragments-array, TrackerCategory].
 * A domain matches if any fragment appears as a whole dot-separated segment
 * or is contained within a segment.
 */
export const ADVERTISING_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'adsystem', 'adserver', 'adservice', 'adtech', 'adnetwork', 'adexchange',
  'adclick', 'adform', 'admarvel', 'adroll', 'adnxs', 'adnexus',
  'doubleclick', 'googlesyndication', 'googleadservices',
  'criteo', 'pubmatic', 'openx', 'outbrain', 'taboola', 'bidswitch',
  'rubiconproject', 'magnite', 'sharethrough', 'prebid',
  'amazon-adsystem', 'casalemedia', 'indexexchange',
  'media.net', '33across', 'appnexus',
  'retarget', 'remarket',
]

export const ANALYTICS_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'google-analytics', 'googletagmanager', 'analytics.google',
  'segment.com', 'segment.io', 'amplitude', 'mixpanel',
  'heap.io', 'heapanalytics', 'matomo', 'piwik',
  'chartbeat', 'parsely', 'parse.ly', 'newrelic', 'datadog',
  'sentry.io', 'etracker', 'rudderstack', 'rudderlabs',
  'plausible.io', 'leadinfo', 'bugsnag',
]

export const SOCIAL_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'facebook.com', 'facebook.net', 'fbcdn',
  'twitter.com', 'x.com',
  'linkedin.com', 'licdn.com',
  'pinterest.com', 'pinimg.com',
  'tiktok.com', 'tiktokcdn.com',
  'instagram.com', 'cdninstagram.com',
  'snapchat.com', 'sc-static.net',
  'reddit.com', 'redditmedia.com',
  'addthis.com', 'sharethis.com', 'addtoany.com',
]

export const IDENTITY_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'liveramp', 'tapad', 'drawbridge', 'lotame', 'zeotap',
  'id5-sync', 'thetradedesk', 'adsrvr.org',
  'acxiom', 'experian', 'neustar',
  'fingerprintjs', 'fpjs.io',
]

// ============================================================================
// Subdomain prefix sets
// ============================================================================

/**
 * Subdomain prefix sets for last-resort classification.
 * When the base domain is unknown, the leading subdomain label
 * frequently reveals purpose (e.g. `cdn.example.com`, `pixel.example.com`).
 */
export const CDN_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'cdn', 'static', 'assets', 'media', 'img', 'images',
  'fonts', 'js', 'css', 'files', 'dl', 'download',
  'content', 'resources', 'res', 'pub', 'dist',
  'video', 'vod', 'stream',
])

export const AD_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'ad', 'ads', 'adserver', 'pixel', 'tag', 'tags',
  'beacon', 'serving', 'bid', 'rtb',
])

export const ANALYTICS_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'analytics', 'tracking', 'tracker', 'telemetry',
  'metrics', 'stats', 'log', 'logs', 'collect',
])

// ============================================================================
// View mode labels & descriptions
// ============================================================================

export const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  all: 'All Domains',
  'third-party': 'Third-Party Only',
  'pre-consent': 'Pre-Consent Only',
}

export const VIEW_MODE_DESCRIPTIONS: Record<ViewMode, string> = {
  all: 'Network connections observed during the page capture, including first-party resources. This may not represent all traffic from the site.',
  'third-party': 'Only third-party domains — hides first-party requests to highlight the external tracker ecosystem.',
  'pre-consent': 'Only connections that occurred before consent was granted — these may violate GDPR requirements.',
}

// ============================================================================
// Resource type metadata
// ============================================================================

/** Human-friendly labels and icons for common Playwright resource types. */
export const RESOURCE_TYPE_META: Record<string, { icon: string; label: string }> = {
  script: { icon: '📜', label: 'Scripts' },
  stylesheet: { icon: '🎨', label: 'Stylesheets' },
  image: { icon: '🖼️', label: 'Images' },
  font: { icon: '🔤', label: 'Fonts' },
  xhr: { icon: '📡', label: 'XHR' },
  fetch: { icon: '📡', label: 'Fetch' },
  document: { icon: '📄', label: 'Documents' },
  iframe: { icon: '🪟', label: 'IFrames' },
  media: { icon: '🎬', label: 'Media' },
  websocket: { icon: '🔌', label: 'WebSocket' },
  ping: { icon: '📍', label: 'Pings' },
  manifest: { icon: '📋', label: 'Manifests' },
  preflight: { icon: '✈️', label: 'Preflight' },
  other: { icon: '📦', label: 'Other' },
}

// ============================================================================
// Domain matching helpers
// ============================================================================

export function matchesDomainList(domain: string, fragments: ReadonlyArray<string>): boolean {
  return fragments.some(f => domain === f || domain.endsWith(`.${f}`))
}

/**
 * Check if a domain contains any keyword from a list.
 * Matches if the keyword appears anywhere in the domain string.
 */
export function matchesDomainKeywords(domain: string, keywords: ReadonlyArray<string>): boolean {
  return keywords.some(kw => domain.includes(kw))
}

// ============================================================================
// Category lookup
// ============================================================================

/**
 * Determine the tracker category for a domain.
 *
 * Checks fragment lists, the structured-report category map, keyword
 * heuristics, and subdomain prefixes — in that priority order.
 */
export function lookupCategory(domain: string, domainCategoryMap: Map<string, TrackerCategory>): TrackerCategory {
  // Session-replay services take priority — they are often
  // classified as "analytics" by Disconnect but warrant a
  // distinct colour on the graph.
  if (matchesDomainList(domain, REPLAY_DOMAIN_FRAGMENTS)) return 'replay'
  // Consent-management platform domains.
  if (matchesDomainList(domain, CMP_DOMAIN_FRAGMENTS)) return 'consent'
  // Exact match from structured report categories.
  const direct = domainCategoryMap.get(domain)
  if (direct && direct !== 'other') return direct
  // Try matching the parent domain (e.g. "pixel.facebook.com" → "facebook.com")
  const parts = domain.split('.')
  if (parts.length > 2) {
    const parent = parts.slice(-2).join('.')
    const parentMatch = domainCategoryMap.get(parent)
    if (parentMatch && parentMatch !== 'other') return parentMatch
  }

  // CDN / infrastructure domains (Disconnect "Content" → "other",
  // but these are well-known services, not unknown trackers).
  if (matchesDomainList(domain, CDN_DOMAIN_FRAGMENTS)) return 'cdn'

  // Domain keyword heuristic — inspect the domain name for
  // category-revealing keywords to reduce "other" classifications.
  if (matchesDomainKeywords(domain, ADVERTISING_DOMAIN_KEYWORDS)) return 'advertising'
  if (matchesDomainKeywords(domain, SOCIAL_DOMAIN_KEYWORDS)) return 'social'
  if (matchesDomainKeywords(domain, ANALYTICS_DOMAIN_KEYWORDS)) return 'analytics'
  if (matchesDomainKeywords(domain, IDENTITY_DOMAIN_KEYWORDS)) return 'identity'

  // Subdomain prefix heuristic — the leading label of a hostname
  // often reveals purpose even when the base domain is unknown.
  if (parts.length > 2) {
    const prefix = parts[0]!
    if (CDN_SUBDOMAIN_PREFIXES.has(prefix)) return 'cdn'
    if (AD_SUBDOMAIN_PREFIXES.has(prefix)) return 'advertising'
    if (ANALYTICS_SUBDOMAIN_PREFIXES.has(prefix)) return 'analytics'
  }

  // Fall back to server classification even if "other" (better
  // than no classification at all — it still has a company name).
  if (direct) return direct

  return 'other'
}

// ============================================================================
// Label truncation
// ============================================================================

/** Shorten long domain labels for legibility. */
export function truncateLabel(domain: string): string {
  return domain.length > 28 ? domain.slice(0, 25) + '…' : domain
}
