<script setup lang="ts">
/**
 * Interactive force-directed network graph showing domain-to-domain
 * tracker relationships derived from captured network requests.
 */

import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  select,
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  zoom as d3Zoom,
  drag as d3Drag,
  max,
  scaleLinear,
  scaleSqrt,
  zoomIdentity,

} from 'd3'
import type {
  Simulation,
  SimulationNodeDatum,
  SimulationLinkDatum,
  DragBehavior,
  SubjectPosition,
  ZoomBehavior,
} from 'd3'
import type { NetworkRequest, StructuredReport } from '../../types'
import { countryFlagUrl, countryName } from '../../utils'

// ============================================================================
// Types
// ============================================================================

/** Category label used to colour-code graph nodes. */
type TrackerCategory = 'origin' | 'first-party' | 'analytics' | 'advertising' | 'social' | 'identity' | 'replay' | 'consent' | 'cdn' | 'other'

/** Available graph view modes. */
type ViewMode = 'all' | 'third-party' | 'pre-consent'

/** A node in the tracker relationship graph. */
interface GraphNode extends SimulationNodeDatum {
  id: string
  label: string
  category: TrackerCategory
  requestCount: number
  isThirdParty: boolean
}

/** A directed edge between two domains. */
interface GraphEdge extends SimulationLinkDatum<GraphNode> {
  sourceId: string
  targetId: string
  weight: number
  preConsent: boolean
}

// ============================================================================
// Props
// ============================================================================

const props = defineProps<{
  /** Raw (un-filtered) network requests from the analysis */
  networkRequests: NetworkRequest[]
  /** Structured report used to classify domains by tracker category */
  structuredReport: StructuredReport | null
  /** The URL that was analysed (used to identify the origin node) */
  analyzedUrl: string
}>()

// ============================================================================
// Colours & layout constants
// ============================================================================

const CATEGORY_COLOURS: Record<TrackerCategory, string> = {
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

const CATEGORY_LABELS: Record<TrackerCategory, string> = {
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

/**
 * Known session-replay / experience-analytics domain fragments.
 * Sourced from `tracker_patterns.py` SESSION_REPLAY_PATTERNS and
 * BEHAVIOURAL_TRACKING_PATTERNS.
 */
const REPLAY_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
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
const CMP_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
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
const CDN_DOMAIN_FRAGMENTS: ReadonlyArray<string> = [
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
const FIRST_PARTY_ALIASES: Readonly<Record<string, ReadonlyArray<string>>> = {
  'bbc.co.uk': ['bbci.co.uk'],
  'theguardian.com': ['guim.co.uk', 'guardianapis.com'],
}

/**
 * Domain keyword fragments for client-side classification fallback.
 * Used when a domain isn't in the structured report and doesn't match
 * the replay or CMP fragment lists.  Checked before falling back to 'other'.
 *
 * Each entry is a tuple of [keyword-fragments-array, TrackerCategory].
 * A domain matches if any fragment appears as a whole dot-separated segment
 * or is contained within a segment.
 */
const ADVERTISING_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'adsystem', 'adserver', 'adservice', 'adtech', 'adnetwork', 'adexchange',
  'adclick', 'adform', 'admarvel', 'adroll', 'adnxs', 'adnexus',
  'doubleclick', 'googlesyndication', 'googleadservices',
  'criteo', 'pubmatic', 'openx', 'outbrain', 'taboola', 'bidswitch',
  'rubiconproject', 'magnite', 'sharethrough', 'prebid',
  'amazon-adsystem', 'casalemedia', 'indexexchange',
  'media.net', '33across', 'appnexus',
  'retarget', 'remarket',
]

const ANALYTICS_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'google-analytics', 'googletagmanager', 'analytics.google',
  'segment.com', 'segment.io', 'amplitude', 'mixpanel',
  'heap.io', 'heapanalytics', 'matomo', 'piwik',
  'chartbeat', 'parsely', 'parse.ly', 'newrelic', 'datadog',
  'sentry.io', 'etracker', 'rudderstack', 'rudderlabs',
  'plausible.io', 'leadinfo', 'bugsnag',
]

const SOCIAL_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
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

const IDENTITY_DOMAIN_KEYWORDS: ReadonlyArray<string> = [
  'liveramp', 'tapad', 'drawbridge', 'lotame', 'zeotap',
  'id5-sync', 'thetradedesk', 'adsrvr.org',
  'acxiom', 'experian', 'neustar',
  'fingerprintjs', 'fpjs.io',
]

/**
 * Subdomain prefix sets for last-resort classification.
 * When the base domain is unknown, the leading subdomain label
 * frequently reveals purpose (e.g. `cdn.example.com`, `pixel.example.com`).
 */
const CDN_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'cdn', 'static', 'assets', 'media', 'img', 'images',
  'fonts', 'js', 'css', 'files', 'dl', 'download',
  'content', 'resources', 'res', 'pub', 'dist',
  'video', 'vod', 'stream',
])

const AD_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'ad', 'ads', 'adserver', 'pixel', 'tag', 'tags',
  'beacon', 'serving', 'bid', 'rtb',
])

const ANALYTICS_SUBDOMAIN_PREFIXES: ReadonlySet<string> = new Set([
  'analytics', 'tracking', 'tracker', 'telemetry',
  'metrics', 'stats', 'log', 'logs', 'collect',
])

// ============================================================================
// Refs
// ============================================================================

const svgRef = ref<SVGSVGElement | null>(null)
const minimapRef = ref<HTMLCanvasElement | null>(null)
const hoveredNode = ref<GraphNode | null>(null)
const selectedNode = ref<GraphNode | null>(null)
const isFullscreen = ref(false)
const viewMode = ref<ViewMode>('all')
const showExplanation = ref(true)

/** Cached domain info keyed by domain (for country flags). */
const domainInfo = reactive<Record<string, { country: string | null }>>({})

/** Fetch country info for all graph domains. */
async function fetchDomainInfo(domains: string[]): Promise<void> {
  const unknown = domains.filter((d) => !(d in domainInfo))
  if (unknown.length === 0) return
  try {
    const apiBase = import.meta.env.VITE_API_URL || ''
    const response = await fetch(`${apiBase}/api/domain-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domains: unknown }),
    })
    if (response.ok) {
      const data = await response.json()
      for (const [domain, info] of Object.entries(data)) {
        domainInfo[domain] = info as { country: string | null }
      }
    }
  } catch {
    // Silently fail — enrichment is non-critical
  }
}

/** The single active category filter — null means "show all". */
const activeCategory = ref<TrackerCategory | null>(null)

/** Select a category exclusively (click again to deselect). Origin is ignored. */
function toggleCategory(cat: TrackerCategory): void {
  if (cat === 'origin') return
  activeCategory.value = activeCategory.value === cat ? null : cat
}

/** Whether a category is currently highlighted in the legend. */
function isCategoryActive(cat: TrackerCategory): boolean {
  if (cat === 'origin') return true
  return activeCategory.value === null || activeCategory.value === cat
}

const VIEW_MODE_LABELS: Record<ViewMode, string> = {
  all: 'All Domains',
  'third-party': 'Third-Party Only',
  'pre-consent': 'Pre-Consent Only',
}

const VIEW_MODE_DESCRIPTIONS: Record<ViewMode, string> = {
  all: 'Network connections observed during the page capture, including first-party resources. This may not represent all traffic from the site.',
  'third-party': 'Only third-party domains — hides first-party requests to highlight the external tracker ecosystem.',
  'pre-consent': 'Only connections that occurred before consent was granted — these may violate GDPR requirements.',
}

/** Debounce timer for resize-triggered re-renders. */
let resizeTimer: ReturnType<typeof setTimeout> | null = null
/** Prevents concurrent or re-entrant renderGraph() calls. */
let isRendering = false
/** Last rendered dimensions — skip re-render when unchanged. */
let lastWidth = 0
let lastHeight = 0
/** Label-visibility threshold for the current render. */
let currentLabelThreshold = 3
/** Current zoom transform for minimap viewport calculation. */
let currentTransform = { x: 0, y: 0, k: 1 }
/** D3 zoom behaviour reference for programmatic panning (minimap click). */
let zoomRef: ZoomBehavior<SVGSVGElement, unknown> | null = null
/** Last-computed minimap coordinate mapping for click handling. */
let minimapMapping: { minX: number; minY: number; scale: number; offsetX: number; offsetY: number } | null = null
/** Snapshot of the currently rendered graph data for minimap redraws outside simulation ticks. */
let renderedNodes: GraphNode[] = []
let renderedEdges: GraphEdge[] = []

/**
 * Toggle fullscreen mode.
 * Pauses the ResizeObserver during the transition to prevent layout
 * oscillation, waits for the DOM to settle, then re-renders once.
 */
function toggleFullscreen(): void {
  // Pause observer to avoid resize → render → resize loop
  if (resizeObserver) resizeObserver.disconnect()
  if (resizeTimer) { clearTimeout(resizeTimer); resizeTimer = null }

  isFullscreen.value = !isFullscreen.value

  // Wait for Vue to flush the DOM change, then give the browser an
  // extra frame to finish layout before re-rendering the graph.
  nextTick(() => {
    requestAnimationFrame(() => {
      // Reset dimension cache so the re-render isn't skipped
      lastWidth = 0
      lastHeight = 0
      renderGraph()
      // Re-connect observer after the render has stabilised
      if (resizeObserver && svgRef.value) {
        resizeObserver.observe(svgRef.value)
      }
    })
  })
}

/** Close fullscreen on Escape key. */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && isFullscreen.value) {
    toggleFullscreen()
  }
}

// ============================================================================
// Computed graph data
// ============================================================================

/**
 * Build a domain → tracker-category lookup from the structured report.
 */
const domainCategoryMap = computed<Map<string, TrackerCategory>>(() => {
  const map = new Map<string, TrackerCategory>()
  const report = props.structuredReport
  if (!report) return map

  const categories: { key: TrackerCategory; entries: { domains: string[] }[] }[] = [
    { key: 'analytics', entries: report.trackingTechnologies.analytics },
    { key: 'advertising', entries: report.trackingTechnologies.advertising },
    { key: 'social', entries: report.trackingTechnologies.socialMedia },
    { key: 'identity', entries: report.trackingTechnologies.identityResolution },
    { key: 'other', entries: report.trackingTechnologies.other },
  ]

  for (const { key, entries } of categories) {
    for (const entry of entries) {
      for (const domain of entry.domains) {
        map.set(domain, key)
      }
    }
  }
  return map
})

/**
 * Extract the origin domain from the analysed URL.
 */
const originDomain = computed(() => {
  try {
    return new URL(props.analyzedUrl).hostname
  } catch {
    return 'origin'
  }
})

/**
 * Derive the base (registrable) domain from a hostname.
 * Strips leading subdomains, keeping the last two segments
 * (or three for known two-part TLDs like `.co.uk`).
 */
function getBaseDomain(hostname: string): string {
  const parts = hostname.split('.')
  // Handle two-part TLDs like co.uk, com.au, org.uk, etc.
  const twoPartTlds = ['co.uk', 'com.au', 'org.uk', 'co.nz', 'co.za', 'com.br', 'co.jp', 'co.kr', 'co.in']
  if (parts.length >= 3) {
    const lastTwo = parts.slice(-2).join('.')
    if (twoPartTlds.includes(lastTwo)) {
      return parts.slice(-3).join('.')
    }
  }
  return parts.slice(-2).join('.')
}

/**
 * The base (registrable) domain of the origin, used to
 * detect first-party subdomains that share the same base.
 */
const originBaseDomain = computed(() => getBaseDomain(originDomain.value))

/**
 * Set of base domains that should be treated as first-party
 * for the current origin, including the origin itself and any
 * aliases declared in FIRST_PARTY_ALIASES.
 */
const firstPartyBases = computed(() => {
  const base = originBaseDomain.value
  const set = new Set<string>([base])
  const aliases = FIRST_PARTY_ALIASES[base]
  if (aliases) {
    for (const a of aliases) set.add(a)
  }
  return set
})

/**
 * Derive the node and edge lists from the raw network requests.
 */
const graphData = computed(() => {
  const nodeMap = new Map<string, GraphNode>()
  const edgeKey = (src: string, tgt: string) => `${src}>>>${tgt}`
  const edgeMap = new Map<string, GraphEdge>()

  // Ensure origin node always exists
  const origin = originDomain.value
  const fpBases = firstPartyBases.value

  nodeMap.set(origin, {
    id: origin,
    label: origin,
    category: 'origin',
    requestCount: 0,
    isThirdParty: false,
  })

  for (const req of props.networkRequests) {
    const target = req.domain
    if (!target || target === 'unknown') continue

    // Determine the source (initiator) domain — fall back to origin if absent
    const source = req.initiatorDomain && req.initiatorDomain !== 'unknown'
      ? req.initiatorDomain
      : origin

    // Ensure source node exists
    if (!nodeMap.has(source)) {
      const isOrigin = source === origin
      const isFirstParty = !isOrigin && fpBases.has(getBaseDomain(source))
      nodeMap.set(source, {
        id: source,
        label: source,
        category: isOrigin ? 'origin' : isFirstParty ? 'first-party' : lookupCategory(source),
        requestCount: 0,
        isThirdParty: isOrigin || isFirstParty ? false : source !== origin,
      })
    }

    // Ensure target node exists and bump its request count
    if (!nodeMap.has(target)) {
      const isOrigin = target === origin
      const isFirstParty = !isOrigin && fpBases.has(getBaseDomain(target))
      nodeMap.set(target, {
        id: target,
        label: target,
        category: isOrigin ? 'origin' : isFirstParty ? 'first-party' : lookupCategory(target),
        requestCount: 0,
        isThirdParty: isOrigin || isFirstParty ? false : req.isThirdParty,
      })
    }
    nodeMap.get(target)!.requestCount++

    // Skip self-loops
    if (source === target) continue

    // Add or aggregate edge
    const key = edgeKey(source, target)
    const existing = edgeMap.get(key)
    if (existing) {
      existing.weight++
      if (req.preConsent) existing.preConsent = true
    } else {
      edgeMap.set(key, {
        sourceId: source,
        targetId: target,
        source: source,
        target: target,
        weight: 1,
        preConsent: Boolean(req.preConsent),
      })
    }
  }

  return {
    nodes: Array.from(nodeMap.values()),
    edges: Array.from(edgeMap.values()),
  }

  function matchesDomainList(domain: string, fragments: ReadonlyArray<string>): boolean {
    return fragments.some(f => domain === f || domain.endsWith(`.${f}`))
  }

  /**
   * Check if a domain contains any keyword from a list.
   * Matches if the keyword appears anywhere in the domain string.
   */
  function matchesDomainKeywords(domain: string, keywords: ReadonlyArray<string>): boolean {
    return keywords.some(kw => domain.includes(kw))
  }

  function lookupCategory(domain: string): TrackerCategory {
    // Session-replay services take priority — they are often
    // classified as "analytics" by Disconnect but warrant a
    // distinct colour on the graph.
    if (matchesDomainList(domain, REPLAY_DOMAIN_FRAGMENTS)) return 'replay'
    // Consent-management platform domains.
    if (matchesDomainList(domain, CMP_DOMAIN_FRAGMENTS)) return 'consent'
    // Exact match from structured report categories.
    const direct = domainCategoryMap.value.get(domain)
    if (direct && direct !== 'other') return direct
    // Try matching the parent domain (e.g. "pixel.facebook.com" → "facebook.com")
    const parts = domain.split('.')
    if (parts.length > 2) {
      const parent = parts.slice(-2).join('.')
      const parentMatch = domainCategoryMap.value.get(parent)
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
})

/** Summary statistics shown above the graph. */
const stats = computed(() => {
  const { nodes, edges } = filteredGraphData.value
  const thirdParty = nodes.filter(n => n.isThirdParty).length
  const preConsentEdges = edges.filter(e => e.preConsent).length
  return { totalNodes: nodes.length, thirdParty, totalEdges: edges.length, preConsentEdges }
})

/** Categories that have at least one node in the full (unfiltered) graph. */
const presentCategories = computed(() => {
  const cats = new Set<TrackerCategory>()
  for (const n of graphData.value.nodes) cats.add(n.category)
  return cats
})

// Fetch country info whenever graph nodes change.
watch(
  () => graphData.value.nodes.map(n => n.id),
  (domains) => {
    if (domains.length > 0) fetchDomainInfo(domains)
  },
  { immediate: true },
)

/**
 * Apply the active view mode filter to the full graph data.
 * Returns a new node/edge set with only the relevant subset.
 */
const filteredGraphData = computed(() => {
  const { nodes, edges } = graphData.value
  const mode = viewMode.value
  const catFilter = activeCategory.value

  // 1. View-mode filter
  let modeNodes = nodes
  let modeEdges = edges

  if (mode !== 'all') {
    if (mode === 'third-party') {
      const thirdPartyIds = new Set(nodes.filter(n => n.isThirdParty).map(n => n.id))
      modeEdges = edges.filter(e => thirdPartyIds.has(e.sourceId) || thirdPartyIds.has(e.targetId))
    } else {
      // pre-consent
      modeEdges = edges.filter(e => e.preConsent)
    }

    const referencedIds = new Set<string>()
    for (const e of modeEdges) {
      referencedIds.add(e.sourceId)
      referencedIds.add(e.targetId)
    }
    referencedIds.add(originDomain.value)
    modeNodes = nodes.filter(n => referencedIds.has(n.id))
  }

  // 2. Category filter — trace full path chains from origin
  //    through any intermediate categories to nodes of the
  //    selected category.  Reverse-BFS from target nodes finds
  //    every ancestor on a path leading to them, so chains like
  //    origin → advertising → social are kept when "Social" is
  //    selected, but branches ending at other categories are pruned.
  if (catFilter !== null) {
    // Target node IDs (the selected category)
    const targetIds = new Set(
      modeNodes.filter(n => n.category === catFilter).map(n => n.id),
    )

    // Build a reverse adjacency list (targetId → set of sourceIds)
    const reverseAdj = new Map<string, string[]>()
    for (const e of modeEdges) {
      let sources = reverseAdj.get(e.targetId)
      if (!sources) { sources = []; reverseAdj.set(e.targetId, sources) }
      sources.push(e.sourceId)
    }

    // BFS backwards from every target node to discover all ancestors
    const reachable = new Set<string>(targetIds)
    const queue = [...targetIds]
    while (queue.length > 0) {
      const current = queue.shift()!
      const sources = reverseAdj.get(current)
      if (sources) {
        for (const src of sources) {
          if (!reachable.has(src)) {
            reachable.add(src)
            queue.push(src)
          }
        }
      }
    }
    reachable.add(originDomain.value)

    // Keep only edges and nodes on the discovered paths
    modeEdges = modeEdges.filter(e => reachable.has(e.sourceId) && reachable.has(e.targetId))
    const edgeNodeIds = new Set<string>()
    for (const e of modeEdges) {
      edgeNodeIds.add(e.sourceId)
      edgeNodeIds.add(e.targetId)
    }
    edgeNodeIds.add(originDomain.value)
    modeNodes = modeNodes.filter(n => edgeNodeIds.has(n.id))
  }

  return { nodes: modeNodes, edges: modeEdges }
})

// ============================================================================
// D3 Simulation
// ============================================================================

let simulation: Simulation<GraphNode, GraphEdge> | null = null
let resizeObserver: ResizeObserver | null = null
/** Tracks whether a RAF tick is already scheduled. */
let tickScheduled = false
/** Render (or re-render) the force-directed graph inside the SVG element. */
function renderGraph() {
  // Guard against overlapping renders
  if (isRendering) return
  isRendering = true

  try {
    renderGraphInner()
  } finally {
    isRendering = false
  }
}

function renderGraphInner() {
  const svg = svgRef.value
  if (!svg) return

  const { nodes, edges } = filteredGraphData.value
  if (nodes.length === 0) return

  // Stop any running simulation first
  if (simulation) { simulation.stop(); simulation = null }
  tickScheduled = false

  const width = svg.clientWidth || 900
  const height = svg.clientHeight || 500

  // Skip re-render when dimensions haven't changed and we already have
  // a rendered graph (avoids unnecessary full rebuilds on no-op resizes)
  if (width === lastWidth && height === lastHeight && svg.childElementCount > 0) return
  lastWidth = width
  lastHeight = height

  // Clear previous render
  select(svg).selectAll('*').remove()

  const svgSel = select(svg)
    .attr('viewBox', `0 0 ${width} ${height}`)

  // Container for zoom/pan
  const container = svgSel.append('g')

  // Zoom behaviour
  zoomRef = d3Zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.2, 4])
    .on('zoom', (event) => {
      container.attr('transform', event.transform)
      currentTransform = { x: event.transform.x, y: event.transform.y, k: event.transform.k }
      // Redraw minimap viewport rectangle on every zoom / pan event
      renderMinimap(renderedNodes, renderedEdges)
    })
  svgSel.call(zoomRef)

  // Click on background (not a node) to deselect
  svgSel.on('click', (event) => {
    if (event.target === svg || event.target.tagName === 'rect') {
      selectedNode.value = null
    }
  })

  // Arrow marker for directed edges
  svgSel.append('defs').append('marker')
    .attr('id', 'arrowhead')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#4b5563')

  // Pre-consent arrow marker (orange)
  svgSel.select('defs').append('marker')
    .attr('id', 'arrowhead-precon')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#f59e0b')

  // Glow filter for node hover effect
  const glowFilter = svgSel.select('defs').append('filter')
    .attr('id', 'node-glow')
    .attr('x', '-50%').attr('y', '-50%')
    .attr('width', '200%').attr('height', '200%')
  glowFilter.append('feGaussianBlur')
    .attr('in', 'SourceGraphic')
    .attr('stdDeviation', '4')
    .attr('result', 'blur')
  glowFilter.append('feComposite')
    .attr('in', 'SourceGraphic')
    .attr('in2', 'blur')
    .attr('operator', 'over')

  // Edge scale for stroke width
  const maxWeight = max(edges, e => e.weight) ?? 1
  const strokeScale = scaleLinear().domain([1, maxWeight]).range([1, 4])

  // Draw edges as curved paths
  const linkGroup = container.append('g').attr('class', 'links')
  const linkSel = linkGroup.selectAll<SVGPathElement, GraphEdge>('path')
    .data(edges)
    .join('path')
    .attr('fill', 'none')
    .attr('stroke', d => d.preConsent ? '#f59e0b' : '#4b5563')
    .attr('stroke-width', d => strokeScale(d.weight))
    .attr('stroke-dasharray', d => d.preConsent ? '5,3' : 'none')
    .attr('marker-end', d => d.preConsent ? 'url(#arrowhead-precon)' : 'url(#arrowhead)')
    .attr('opacity', 0)

  // Node radius scale
  const maxReq = max(nodes, n => n.requestCount) ?? 1
  const radiusScale = scaleSqrt().domain([0, maxReq]).range([6, 24])

  /** Minimum request count to show a persistent label. */
  const labelThreshold = Math.max(3, Math.ceil(nodes.length * 0.08))
  currentLabelThreshold = labelThreshold

  // Draw nodes
  const nodeGroup = container.append('g').attr('class', 'nodes')
  const nodeSel = nodeGroup.selectAll<SVGCircleElement, GraphNode>('circle')
    .data(nodes, d => d.id)
    .join('circle')
    .attr('r', 0)
    .attr('fill', d => CATEGORY_COLOURS[d.category])
    .attr('stroke', '#1e2235')
    .attr('stroke-width', 1.5)
    .attr('cursor', 'pointer')
    .on('mouseover', function (_event, d) {
      hoveredNode.value = d
      // Apply glow filter on hover — operate on `this` element directly
      select(this)
        .attr('filter', 'url(#node-glow)')
        .transition().duration(200)
        .attr('stroke', CATEGORY_COLOURS[d.category])
        .attr('stroke-width', 3)
      // Show label on hover for nodes that lack a persistent label
      labelSel.filter(n => n.id === d.id).attr('opacity', 1)
    })
    .on('mouseout', function (_event, d) {
      hoveredNode.value = null
      // Remove glow filter — operate on `this` element directly
      select(this)
        .attr('filter', null)
        .transition().duration(300)
        .attr('stroke', '#1e2235')
        .attr('stroke-width', 1.5)
      // Restore original opacity
      labelSel.filter(n => n.id === d.id)
        .attr('opacity', n => showLabel(n) ? 1 : 0)
    })
    .on('click', (event, d) => {
      event.stopPropagation()
      selectedNode.value = selectedNode.value?.id === d.id ? null : d
    })

  /** Whether a node gets a persistent label. */
  function showLabel(d: GraphNode): boolean {
    return d.category === 'origin' || d.requestCount >= labelThreshold
  }

  // Labels — only permanently visible for origin + high-activity nodes
  const labelGroup = container.append('g').attr('class', 'labels')
  const labelSel = labelGroup.selectAll<SVGTextElement, GraphNode>('text')
    .data(nodes)
    .join('text')
    .text(d => truncateLabel(d.label))
    .attr('font-size', d => d.category === 'origin' ? '11px' : '9px')
    .attr('fill', '#c7d2fe')
    .attr('text-anchor', 'middle')
    .attr('dy', d => -(d.category === 'origin' ? 20 : radiusScale(d.requestCount) + 6))
    .attr('pointer-events', 'none')
    .attr('opacity', 0)

  // ── Entrance animations ──
  // Staggered node scale-up
  nodeSel.transition()
    .delay((_d, i) => i * 3)
    .duration(150)
    .attr('r', d => d.category === 'origin' ? 16 : radiusScale(d.requestCount))

  // Fade in edges after nodes settle
  linkSel.transition()
    .delay(80)
    .duration(150)
    .attr('opacity', 0.6)

  // Fade in labels
  labelSel.transition()
    .delay(120)
    .duration(150)
    .attr('opacity', d => showLabel(d) ? 1 : 0)

  // Tune parameters based on graph size
  const nodeCount = nodes.length

  // Throttle minimap to avoid re-drawing every frame for large graphs
  let minimapTickCount = 0
  const minimapInterval = nodeCount > 100 ? 3 : 1

  // Store a reference to the currently rendered data so the
  // zoom handler can redraw the minimap after simulation stops.
  renderedNodes = nodes
  renderedEdges = edges

  // Force simulation — adaptive parameters for large graphs
  const chargeStrength = nodeCount > 150 ? -180 : nodeCount > 80 ? -250 : -320
  const linkDistance = nodeCount > 150 ? 100 : nodeCount > 80 ? 120 : 140
  const alphaDecay = nodeCount > 100 ? 0.08 : 0.05

  simulation = forceSimulation<GraphNode, GraphEdge>(nodes)
    .alphaDecay(alphaDecay)
    .force('link', forceLink<GraphNode, GraphEdge>(edges).id(d => d.id).distance(linkDistance))
    .force('charge', forceManyBody().strength(chargeStrength).distanceMax(nodeCount > 100 ? 400 : 600))
    .force('center', forceCenter(width / 2, height / 2))
    .force('collision', forceCollide<GraphNode>().radius(d => radiusScale(d.requestCount) + 12))
    .on('tick', () => {
      // Throttle DOM updates to one per animation frame
      if (tickScheduled) return
      tickScheduled = true
      requestAnimationFrame(() => {
        tickScheduled = false

        // Curved links with quadratic Bézier offset
        linkSel.attr('d', (d: GraphEdge) => {
          const src = d.source as GraphNode
          const tgt = d.target as GraphNode
          const sx = src.x ?? 0, sy = src.y ?? 0
          const tx = tgt.x ?? 0, ty = tgt.y ?? 0
          const dx = tx - sx, dy = ty - sy
          // Perpendicular offset for curve (proportional to distance, capped)
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const offset = Math.min(dist * 0.15, 40)
          const mx = (sx + tx) / 2 - (dy / dist) * offset
          const my = (sy + ty) / 2 + (dx / dist) * offset
          return `M${sx},${sy}Q${mx},${my} ${tx},${ty}`
        })

        nodeSel
          .attr('cx', d => d.x ?? 0)
          .attr('cy', d => d.y ?? 0)

        labelSel
          .attr('x', d => d.x ?? 0)
          .attr('y', d => d.y ?? 0)

        minimapTickCount++
        if (minimapTickCount % minimapInterval === 0) {
          renderMinimap(nodes, edges)
        }
      })
    })

  // Wire drag behaviour now that simulation is initialised
  nodeSel.call(drag(simulation))

  // Re-apply subgraph highlight if a node was selected before re-render
  if (selectedNode.value) applyHighlight()

}

/**
 * Create a D3 drag behaviour for graph nodes.
 */
function drag(
  sim: Simulation<GraphNode, GraphEdge>,
): DragBehavior<SVGCircleElement, GraphNode, GraphNode | SubjectPosition> {
  return d3Drag<SVGCircleElement, GraphNode>()
    .on('start', (event, d) => {
      if (!event.active) sim.alphaTarget(0.3).restart()
      d.fx = d.x
      d.fy = d.y
    })
    .on('drag', (event, d) => {
      d.fx = event.x
      d.fy = event.y
    })
    .on('end', (event, d) => {
      if (!event.active) sim.alphaTarget(0)
      d.fx = null
      d.fy = null
    })
}

// ============================================================================
// Subgraph Highlighting
// ============================================================================

/**
 * Dim unrelated nodes and edges when a node is selected, or restore
 * defaults when the selection is cleared.
 */
function applyHighlight(): void {
  const svg = svgRef.value
  if (!svg) return

  const svgSel = select(svg)
  const circlesSel = svgSel.selectAll<SVGCircleElement, GraphNode>('.nodes circle')
  const pathsSel = svgSel.selectAll<SVGPathElement, GraphEdge>('.links path')
  const textsSel = svgSel.selectAll<SVGTextElement, GraphNode>('.labels text')

  const sel = selectedNode.value
  if (!sel) {
    // Restore defaults
    circlesSel
      .attr('opacity', 1)
      .attr('filter', null)
      .attr('stroke', '#1e2235')
      .attr('stroke-width', 1.5)
    const maxWeight = max(filteredGraphData.value.edges, e => e.weight) ?? 1
    const s = scaleLinear().domain([1, maxWeight]).range([1, 4])
    pathsSel
      .attr('opacity', 0.6)
      .attr('stroke-opacity', null)
      .attr('marker-end', (d: GraphEdge) => d.preConsent ? 'url(#arrowhead-precon)' : 'url(#arrowhead)')
      .attr('stroke-width', d => s(d.weight))
    textsSel.attr('opacity', (d: GraphNode) =>
      d.category === 'origin' || d.requestCount >= currentLabelThreshold ? 1 : 0)
    // Remove any path trace highlights
    svgSel.selectAll('.path-trace').remove()
    return
  }

  // Build set of directly connected node IDs
  const { edges } = filteredGraphData.value
  const connectedIds = new Set<string>([sel.id])
  for (const e of edges) {
    if (e.sourceId === sel.id) connectedIds.add(e.targetId)
    if (e.targetId === sel.id) connectedIds.add(e.sourceId)
  }

  // Path tracing: find all paths from origin to selected node via BFS
  const traceIds = tracePathToOrigin(sel.id, edges, originDomain.value)

  // Combine connected + traced nodes
  const highlightIds = new Set([...connectedIds, ...traceIds])

  circlesSel.attr('opacity', (d: GraphNode) => highlightIds.has(d.id) ? 1 : 0.12)
  pathsSel.each(function (this: SVGPathElement, d: GraphEdge) {
    const isDirectlyConnected = d.sourceId === sel!.id || d.targetId === sel!.id
    const isOnTracedPath = traceIds.has(d.sourceId) && traceIds.has(d.targetId)
    const highlighted = isDirectlyConnected || isOnTracedPath

    const pathEl = select(this)
    pathEl.attr('opacity', isDirectlyConnected ? 0.85 : isOnTracedPath ? 0.6 : 0.04)
    pathEl.attr('stroke-opacity', highlighted ? null : 0.04)
    pathEl.attr('marker-end', highlighted
      ? (d.preConsent ? 'url(#arrowhead-precon)' : 'url(#arrowhead)')
      : 'none')
  })
  textsSel.attr('opacity', (d: GraphNode) => highlightIds.has(d.id) ? 1 : 0.04)

  // Glow the selected node
  circlesSel
    .filter((d: GraphNode) => d.id === sel.id)
    .attr('filter', 'url(#node-glow)')
    .attr('stroke', CATEGORY_COLOURS[sel.category])
    .attr('stroke-width', 3)
}

// ============================================================================
// Path Tracing
// ============================================================================

/**
 * Trace all nodes on any path from origin to the target node.
 * Uses reverse BFS from the target back to origin, collecting
 * every node along the way.
 */
function tracePathToOrigin(targetId: string, edges: GraphEdge[], origin: string): Set<string> {
  if (targetId === origin) return new Set([origin])

  // Build forward adjacency: source → [targets]
  const adj = new Map<string, string[]>()
  for (const e of edges) {
    let targets = adj.get(e.sourceId)
    if (!targets) { targets = []; adj.set(e.sourceId, targets) }
    targets.push(e.targetId)
  }

  // BFS from origin, recording parent pointers
  const parents = new Map<string, string[]>()
  const visited = new Set<string>([origin])
  const queue = [origin]
  let found = false

  while (queue.length > 0) {
    const current = queue.shift()!
    if (current === targetId) { found = true; continue }
    const neighbors = adj.get(current) ?? []
    for (const next of neighbors) {
      if (!parents.has(next)) parents.set(next, [])
      parents.get(next)!.push(current)
      if (!visited.has(next)) {
        visited.add(next)
        queue.push(next)
      }
    }
  }

  if (!found) return new Set([targetId])

  // Walk backwards from target to origin to collect all nodes on paths
  const onPath = new Set<string>([targetId])
  const backQueue = [targetId]
  while (backQueue.length > 0) {
    const current = backQueue.shift()!
    const preds = parents.get(current) ?? []
    for (const p of preds) {
      if (!onPath.has(p)) {
        onPath.add(p)
        backQueue.push(p)
      }
    }
  }
  return onPath
}

// ============================================================================
// Minimap
// ============================================================================

/**
 * Draw a small overview of the graph with a viewport rectangle.
 * Called on every simulation tick so node positions stay in sync.
 */
function renderMinimap(nodes: GraphNode[], edges: GraphEdge[]): void {
  const canvas = minimapRef.value
  if (!canvas || nodes.length < 6) return

  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const mw = canvas.width
  const mh = canvas.height

  // Compute data extent
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of nodes) {
    const x = n.x ?? 0
    const y = n.y ?? 0
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  const pad = 40
  minX -= pad; minY -= pad; maxX += pad; maxY += pad
  const dataW = maxX - minX || 1
  const dataH = maxY - minY || 1

  const scale = Math.min(mw / dataW, mh / dataH)
  const offsetX = (mw - dataW * scale) / 2
  const offsetY = (mh - dataH * scale) / 2

  // Store mapping for the click handler
  minimapMapping = { minX, minY, scale, offsetX, offsetY }

  const toMx = (x: number) => (x - minX) * scale + offsetX
  const toMy = (y: number) => (y - minY) * scale + offsetY

  // Clear & background
  ctx.clearRect(0, 0, mw, mh)
  ctx.fillStyle = 'rgba(21, 24, 37, 0.9)'
  ctx.fillRect(0, 0, mw, mh)

  // Edges — batch into a single path for large graphs
  ctx.strokeStyle = 'rgba(75, 85, 99, 0.35)'
  ctx.lineWidth = 0.5
  ctx.beginPath()
  for (const e of edges) {
    const src = e.source as GraphNode
    const tgt = e.target as GraphNode
    ctx.moveTo(toMx(src.x ?? 0), toMy(src.y ?? 0))
    ctx.lineTo(toMx(tgt.x ?? 0), toMy(tgt.y ?? 0))
  }
  ctx.stroke()

  // Nodes — batch by colour to minimise fillStyle changes
  const byColour = new Map<string, GraphNode[]>()
  for (const n of nodes) {
    const colour = CATEGORY_COLOURS[n.category]
    let group = byColour.get(colour)
    if (!group) { group = []; byColour.set(colour, group) }
    group.push(n)
  }
  for (const [colour, group] of byColour) {
    ctx.fillStyle = colour
    ctx.globalAlpha = 0.8
    ctx.beginPath()
    for (const n of group) {
      const mx = toMx(n.x ?? 0)
      const my = toMy(n.y ?? 0)
      const r = n.category === 'origin' ? 3 : 2
      ctx.moveTo(mx + r, my)
      ctx.arc(mx, my, r, 0, Math.PI * 2)
    }
    ctx.fill()
  }
  // Re-draw origin on top at full opacity
  const originNode = nodes.find(n => n.category === 'origin')
  if (originNode) {
    ctx.fillStyle = CATEGORY_COLOURS.origin
    ctx.globalAlpha = 1
    ctx.beginPath()
    ctx.arc(toMx(originNode.x ?? 0), toMy(originNode.y ?? 0), 3, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.globalAlpha = 1

  // Viewport rectangle
  const svg = svgRef.value
  if (svg) {
    const svgW = svg.clientWidth || 900
    const svgH = svg.clientHeight || 500
    const t = currentTransform
    const vx1 = -t.x / t.k
    const vy1 = -t.y / t.k
    const vx2 = (svgW - t.x) / t.k
    const vy2 = (svgH - t.y) / t.k

    ctx.strokeStyle = 'rgba(99, 102, 241, 0.8)'
    ctx.lineWidth = 1.5
    ctx.strokeRect(toMx(vx1), toMy(vy1), (vx2 - vx1) * scale, (vy2 - vy1) * scale)
  }
}

/**
 * Handle click on the minimap — pan the main graph to centre
 * on the corresponding data coordinate.
 */
function onMinimapClick(event: MouseEvent): void {
  const canvas = minimapRef.value
  const svg = svgRef.value
  if (!canvas || !svg || !zoomRef || !minimapMapping) return

  const rect = canvas.getBoundingClientRect()
  const mx = event.clientX - rect.left
  const my = event.clientY - rect.top

  const { minX, minY, scale, offsetX, offsetY } = minimapMapping
  const dataX = (mx - offsetX) / scale + minX
  const dataY = (my - offsetY) / scale + minY

  const svgW = svg.clientWidth || 900
  const svgH = svg.clientHeight || 500
  const k = currentTransform.k

  const newTransform = zoomIdentity
    .translate(svgW / 2 - dataX * k, svgH / 2 - dataY * k)
    .scale(k)

  select<SVGSVGElement, unknown>(svg)
    .call(zoomRef.transform, newTransform)
}

/** Shorten long domain labels for legibility. */
function truncateLabel(domain: string): string {
  return domain.length > 28 ? domain.slice(0, 25) + '…' : domain
}

/**
 * Smoothly pan the graph so the given node is visible if it's
 * currently outside the viewport, centering it on screen.
 */
function panToNodeIfNeeded(node: GraphNode): void {
  const svg = svgRef.value
  if (!svg || !zoomRef) return

  const nx = node.x ?? 0
  const ny = node.y ?? 0
  const k = currentTransform.k
  const tx = currentTransform.x
  const ty = currentTransform.y

  // Node position in screen (SVG pixel) coordinates
  const screenX = nx * k + tx
  const screenY = ny * k + ty

  const svgW = svg.clientWidth || 900
  const svgH = svg.clientHeight || 500

  // Margin from edges before we consider the node "out of view"
  const margin = 60

  if (screenX >= margin && screenX <= svgW - margin &&
      screenY >= margin && screenY <= svgH - margin) {
    return // already in view
  }

  const newTransform = zoomIdentity
    .translate(svgW / 2 - nx * k, svgH / 2 - ny * k)
    .scale(k)

  select<SVGSVGElement, unknown>(svg)
    .transition()
    .duration(300)
    .call(zoomRef.transform, newTransform)
}

// ============================================================================
// Lifecycle & Reactivity
// ============================================================================

onMounted(() => {
  renderGraph()
  resizeObserver = new ResizeObserver(() => {
    // Debounce resize-triggered re-renders (250 ms is long enough to
    // let fullscreen layout changes settle without causing a loop).
    if (resizeTimer) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      resizeTimer = null
      renderGraph()
    }, 250)
  })
  if (svgRef.value) resizeObserver.observe(svgRef.value)
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  if (simulation) { simulation.stop(); simulation = null }
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (resizeTimer) { clearTimeout(resizeTimer); resizeTimer = null }
  document.removeEventListener('keydown', onKeydown)
})

watch(filteredGraphData, () => {
  // Data changed — reset dimension cache so renderGraph performs a full rebuild
  selectedNode.value = null
  lastWidth = 0
  lastHeight = 0
  renderGraph()
}, { flush: 'post' })

watch(selectedNode, (node) => {
  applyHighlight()
  if (node) panToNodeIfNeeded(node)
})

/** Connected domains for the selected node (shown in detail panel). */
const selectedConnections = computed(() => {
  if (!selectedNode.value) return []
  const id = selectedNode.value.id
  const { edges } = graphData.value
  return edges
    .filter(e => e.sourceId === id || e.targetId === id)
    .map(e => ({
      domain: e.sourceId === id ? e.targetId : e.sourceId,
      direction: e.sourceId === id ? 'outbound' as const : 'inbound' as const,
      weight: e.weight,
      preConsent: e.preConsent,
    }))
    .sort((a, b) => b.weight - a.weight)
})

/** Human-friendly labels and icons for common Playwright resource types. */
const RESOURCE_TYPE_META: Record<string, { icon: string; label: string }> = {
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

/** Resource-type breakdown for the currently selected domain. */
const selectedResourceBreakdown = computed(() => {
  if (!selectedNode.value) return []
  const domain = selectedNode.value.id
  const counts = new Map<string, number>()

  for (const req of props.networkRequests) {
    if (req.domain !== domain) continue
    const type = req.resourceType || 'other'
    counts.set(type, (counts.get(type) ?? 0) + 1)
  }

  return Array.from(counts.entries())
    .map(([type, count]) => {
      const meta = RESOURCE_TYPE_META[type] ?? { icon: '📦', label: type }
      return { type, count, icon: meta.icon, label: meta.label }
    })
    .sort((a, b) => b.count - a.count)
})

/** Category breakdown for the stats overlay. */
const graphStatsOverlay = computed(() => {
  const { nodes } = filteredGraphData.value
  const counts = new Map<TrackerCategory, number>()
  for (const n of nodes) {
    counts.set(n.category, (counts.get(n.category) ?? 0) + 1)
  }
  return Array.from(counts.entries())
    .map(([cat, count]) => ({
      category: cat,
      label: CATEGORY_LABELS[cat],
      colour: CATEGORY_COLOURS[cat],
      count,
    }))
    .sort((a, b) => b.count - a.count)
})

</script>

<template>
  <div class="tab-content tracker-graph-tab" :class="{ fullscreen: isFullscreen }">
    <div v-if="networkRequests.length === 0 || graphData.edges.length === 0" class="empty-state">
      No network connections to display.
    </div>
    <template v-else>
      <!-- Explanation -->
      <div v-if="showExplanation" class="graph-explanation">
        <button class="explanation-close" title="Dismiss" @click="showExplanation = false">&times;</button>
        <p>
          This graph maps the <strong>tracker ecosystem</strong> detected on the analysed page.
          Each circle is a domain, and arrows show which domain initiated requests to others.
          Larger circles mean more requests. Dashed orange lines indicate activity that occurred
          <strong>before consent</strong> was granted. Click any node for details.
        </p>
        <p class="explanation-mode">{{ VIEW_MODE_DESCRIPTIONS[viewMode] }}</p>
      </div>

      <!-- Controls bar -->
      <div class="graph-controls">
        <!-- View mode selector -->
        <div class="view-modes">
          <button
            v-for="(label, mode) in VIEW_MODE_LABELS"
            :key="mode"
            class="mode-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode as ViewMode"
          >
            {{ label }}
          </button>
        </div>

        <!-- Stats -->
        <div class="graph-stats">
          <span class="stat"><strong>{{ stats.totalNodes }}</strong> domains</span>
          <span class="stat"><strong>{{ stats.thirdParty }}</strong> third-party</span>
          <span class="stat"><strong>{{ stats.totalEdges }}</strong> connections</span>
          <span v-if="stats.preConsentEdges > 0" class="stat stat-warn">
            <strong>{{ stats.preConsentEdges }}</strong> pre-consent
          </span>
        </div>

        <button class="fullscreen-btn" :title="isFullscreen ? 'Exit fullscreen' : 'Fullscreen'" @click="toggleFullscreen">
          {{ isFullscreen ? '✕' : '⛶' }}
        </button>
      </div>

      <!-- Legend (clickable category filters) -->
      <div class="graph-legend">
        <button
          v-for="(colour, cat) in CATEGORY_COLOURS"
          v-show="presentCategories.has(cat as TrackerCategory)"
          :key="cat"
          class="legend-btn"
          :class="{
            dimmed: !isCategoryActive(cat as TrackerCategory),
            'legend-btn-fixed': (cat as TrackerCategory) === 'origin',
          }"
          :title="(cat as TrackerCategory) === 'origin'
            ? 'Origin site (always visible)'
            : `Toggle ${CATEGORY_LABELS[cat as TrackerCategory]}`"
          @click="toggleCategory(cat as TrackerCategory)"
        >
          <span class="legend-dot" :style="{ background: colour }"></span>
          {{ CATEGORY_LABELS[cat as TrackerCategory] }}
        </button>
        <span class="legend-item">
          <span class="legend-line legend-line-dashed"></span>
          Pre-consent
        </span>
        <button
          v-if="activeCategory !== null"
          class="legend-reset"
          title="Show all categories"
          @click="activeCategory = null"
        >
          Show all
        </button>
      </div>

      <div v-if="filteredGraphData.nodes.length <= 1" class="empty-state">
        No connections to show for the current filters.
        <button v-if="activeCategory !== null" class="legend-reset" style="margin-top: 0.5rem" @click="activeCategory = null">Show all categories</button>
      </div>

      <!-- Graph container -->
      <div v-else class="graph-wrapper">
        <svg ref="svgRef" class="graph-svg"></svg>

        <!-- Minimap (overview + viewport indicator) -->
        <canvas
          v-if="filteredGraphData.nodes.length >= 6"
          ref="minimapRef"
          class="graph-minimap"
          width="160"
          height="100"
          title="Click to navigate"
          @click="onMinimapClick"
        ></canvas>

        <!-- Hover tooltip -->
        <div
          v-if="hoveredNode && !selectedNode"
          class="graph-tooltip"
        >
          <strong>
            <img v-if="domainInfo[hoveredNode.id]?.country" :src="countryFlagUrl(domainInfo[hoveredNode.id]!.country!)" :alt="domainInfo[hoveredNode.id]!.country!" class="country-flag" :title="countryName(domainInfo[hoveredNode.id]!.country!)" />
            {{ hoveredNode.label }}
          </strong>
          <span class="tooltip-cat" :style="{ color: CATEGORY_COLOURS[hoveredNode.category] }">
            {{ CATEGORY_LABELS[hoveredNode.category] }}
          </span>
          <span>{{ hoveredNode.requestCount }} request{{ hoveredNode.requestCount !== 1 ? 's' : '' }}</span>
        </div>

        <!-- Graph statistics overlay -->
        <div class="graph-stats-overlay">
          <div class="stats-overlay-row" v-for="cat in graphStatsOverlay" :key="cat.category">
            <span class="stats-overlay-dot" :style="{ background: cat.colour }"></span>
            <span class="stats-overlay-label">{{ cat.label }}</span>
            <span class="stats-overlay-count">{{ cat.count }}</span>
          </div>
          <div class="stats-overlay-divider"></div>
          <div class="stats-overlay-row">
            <span class="stats-overlay-label stats-overlay-total">Connections</span>
            <span class="stats-overlay-count">{{ filteredGraphData.edges.length }}</span>
          </div>
        </div>

        <!-- Selected-node detail panel (overlay) -->
        <div v-if="selectedNode" class="detail-panel">
          <div class="detail-header">
            <span class="detail-dot" :style="{ background: CATEGORY_COLOURS[selectedNode.category] }"></span>
            <img v-if="domainInfo[selectedNode.id]?.country" :src="countryFlagUrl(domainInfo[selectedNode.id]!.country!)" :alt="domainInfo[selectedNode.id]!.country!" class="country-flag" :title="countryName(domainInfo[selectedNode.id]!.country!)" />
            <strong>{{ selectedNode.label }}</strong>
            <span class="detail-cat">{{ CATEGORY_LABELS[selectedNode.category] }}</span>
            <button class="detail-close" @click="selectedNode = null">&times;</button>
          </div>
          <div class="detail-stats">
            <span>{{ selectedNode.requestCount }} request{{ selectedNode.requestCount !== 1 ? 's' : '' }}</span>
            <span v-if="selectedNode.isThirdParty" class="third-party-badge">3rd Party</span>
            <span v-if="domainInfo[selectedNode.id]?.country" class="detail-country" :title="countryName(domainInfo[selectedNode.id]!.country!)">{{ countryName(domainInfo[selectedNode.id]!.country!) }}</span>
          </div>
          <div v-if="selectedConnections.length > 0" class="detail-connections">
            <h4>Connections</h4>
            <div v-for="conn in selectedConnections" :key="conn.domain + conn.direction" class="conn-item">
              <span class="conn-dir">{{ conn.direction === 'outbound' ? '→' : '←' }}</span>
              <img v-if="domainInfo[conn.domain]?.country" :src="countryFlagUrl(domainInfo[conn.domain]!.country!)" :alt="domainInfo[conn.domain]!.country!" class="country-flag" :title="countryName(domainInfo[conn.domain]!.country!)" />
              <span class="conn-domain">{{ conn.domain }}</span>
              <span class="conn-weight">×{{ conn.weight }}</span>
              <span v-if="conn.preConsent" class="pre-consent-badge">Pre-consent</span>
            </div>
          </div>
          <div v-if="selectedResourceBreakdown.length > 0" class="detail-resources">
            <h4>Resource Types</h4>
            <div class="resource-grid">
              <div v-for="res in selectedResourceBreakdown" :key="res.type" class="resource-item">
                <span class="resource-icon">{{ res.icon }}</span>
                <span class="resource-label">{{ res.label }}</span>
                <span class="resource-count">{{ res.count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <p class="graph-hint">
        Drag nodes to rearrange. Scroll to zoom. Click a node for details. Press <kbd>Esc</kbd> to exit fullscreen.
      </p>
    </template>
  </div>
</template>

<style scoped>
.tracker-graph-tab {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Fullscreen mode */
.tracker-graph-tab.fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: #1a1a2e;
  border: none;
  border-radius: 0;
  margin: 0;
  padding: 1rem;
  overflow: hidden;
}

.tracker-graph-tab.fullscreen .graph-wrapper {
  flex: 1 1 0;
  min-height: 0;
}

.tracker-graph-tab.fullscreen .graph-svg {
  height: 100%;
}

/* Explanation */
.graph-explanation {
  position: relative;
  background: var(--surface-panel);
  border: 1px solid var(--border-separator);
  border-left: 3px solid var(--border-accent);
  border-radius: 6px;
  padding: 0.6rem 2rem 0.6rem 0.75rem;
  font-size: var(--body-size);
  color: var(--body-color);
  line-height: 1.5;
}

.graph-explanation p {
  margin: 0 0 0.3rem;
}

.graph-explanation p:last-child {
  margin-bottom: 0;
}

.graph-explanation strong {
  color: #e0e7ff;
}

.explanation-mode {
  font-style: italic;
  font-size: 0.8rem;
}

.explanation-close {
  position: absolute;
  top: 0.3rem;
  right: 0.4rem;
  background: transparent;
  border: none;
  color: #6b7280;
  font-size: 1rem;
  cursor: pointer;
  padding: 0 0.3rem;
  line-height: 1;
}

.explanation-close:hover {
  color: #e0e7ff;
}

/* Controls bar */
.graph-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.view-modes {
  display: flex;
  gap: 0.25rem;
}

.mode-btn {
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  border: 1px solid var(--border-separator);
  border-radius: 4px;
  background: var(--surface-section);
  color: var(--muted-light);
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.mode-btn:hover {
  border-color: #6366f1;
  color: #c7d2fe;
}

.mode-btn.active {
  background: #3730a3;
  border-color: #6366f1;
  color: #e0e7ff;
  font-weight: 600;
}

/* Stats bar */
.graph-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  font-size: 0.9rem;
  color: #9ca3af;
  margin-left: auto;
}

.stat strong {
  color: #e0e7ff;
}

.stat-warn strong {
  color: #f59e0b;
}

.fullscreen-btn {
  margin-left: auto;
  background: var(--surface-panel);
  border: 1px solid var(--border-separator);
  color: var(--muted-light);
  font-size: 1.1rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  line-height: 1;
  transition: color 0.2s, border-color 0.2s;
}

.fullscreen-btn:hover {
  color: #e0e7ff;
  border-color: #6366f1;
}

/* Legend */
.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
  font-size: 0.7rem;
  color: #9ca3af;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.7rem;
}

.legend-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1rem 0.35rem;
  border: 1px solid transparent;
  border-radius: 3px;
  background: none;
  color: #9ca3af;
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.legend-btn:hover {
  border-color: #4b5563;
  color: #e0e7ff;
}

.legend-btn.dimmed {
  opacity: 0.35;
}

.legend-btn.dimmed:hover {
  opacity: 0.7;
}

.legend-btn-fixed {
  cursor: default;
  opacity: 1 !important;
}

.legend-btn-fixed:hover {
  border-color: transparent;
  color: #9ca3af;
}

.legend-reset {
  padding: 0.2rem 0.5rem;
  border: 1px solid var(--border-separator);
  border-radius: 4px;
  background: var(--surface-section);
  color: #9ca3af;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.legend-reset:hover {
  border-color: #6366f1;
  color: #c7d2fe;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}

.legend-line {
  width: 18px;
  height: 2px;
  background: #4b5563;
  display: inline-block;
}

.legend-line-dashed {
  background: repeating-linear-gradient(
    90deg,
    #f59e0b 0 5px,
    transparent 5px 8px
  );
}

/* Graph area */
.graph-wrapper {
  position: relative;
  border: 1px solid var(--border-separator);
  border-radius: 6px;
  background: #151825;
  overflow: hidden;
}

.graph-svg {
  width: 100%;
  height: 720px;
  display: block;
}

/* Tooltip */
.graph-tooltip {
  position: absolute;
  top: 12px;
  left: 12px;
  background: rgba(21, 24, 37, 0.1);
  border: 1px solid var(--border-separator);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  font-size: var(--body-size);
  pointer-events: none;
  z-index: 10;
  color: var(--section-title-color);
  backdrop-filter: blur(4px);
}

.tooltip-cat {
  font-size: 0.75rem;
  font-weight: 600;
}

/* Detail panel */
.detail-panel {
  position: absolute;
  bottom: 12px;
  left: 12px;
  max-width: 360px;
  background: rgba(21, 24, 37, 0.1);
  border: 1px solid var(--border-separator);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  z-index: 10;
  backdrop-filter: blur(4px);
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.95rem;
}

.detail-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.detail-cat {
  font-size: 0.8rem;
  color: #9ca3af;
}

.detail-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0 0.3rem;
  line-height: 1;
}

.detail-close:hover {
  color: #e0e7ff;
}

.detail-stats {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  margin-top: 0.4rem;
  font-size: var(--body-size);
  color: var(--muted-light);
}

.third-party-badge {
  background: #ef4444;
  color: white;
  padding: var(--badge-padding);
  border-radius: var(--badge-radius);
  font-size: var(--badge-size);
  font-weight: 600;
}

.detail-country {
  font-size: var(--badge-size);
  color: var(--muted-light);
  font-style: italic;
}

.detail-connections {
  margin-top: 0.75rem;
  max-height: 180px;
  overflow-y: auto;
}

.detail-connections h4 {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: #e0e7ff;
}

.conn-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--border-separator);
  font-size: var(--body-size);
}

.conn-item:last-child {
  border-bottom: none;
}

.conn-dir {
  color: #6b7280;
  font-size: 0.9rem;
  width: 1.2rem;
  text-align: center;
}

.conn-domain {
  color: #c7d2fe;
  word-break: break-all;
}

.conn-weight {
  color: #9ca3af;
  font-size: 0.8rem;
  margin-left: auto;
  flex-shrink: 0;
}

.pre-consent-badge {
  font-size: var(--badge-size);
  font-weight: 600;
  background: #7c2d12;
  color: #fed7aa;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  flex-shrink: 0;
}

/* Resource-type breakdown */
.detail-resources {
  margin-top: 0.75rem;
}

.detail-resources h4 {
  margin: 0 0 0.4rem;
  font-size: 0.85rem;
  color: #e0e7ff;
}

.resource-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.resource-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  background: var(--surface-section);
  border: 1px solid var(--border-separator);
  border-radius: 4px;
  padding: 0.2rem 0.5rem;
  font-size: 0.8rem;
}

.resource-icon {
  font-size: 0.85rem;
}

.resource-label {
  color: #c7d2fe;
}

.resource-count {
  color: #9ca3af;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Minimap */
.graph-minimap {
  position: absolute;
  bottom: 8px;
  right: 8px;
  border: 1px solid var(--border-separator);
  border-radius: 4px;
  cursor: crosshair;
  z-index: 5;
  opacity: 0.85;
  transition: opacity 0.2s;
}

.graph-minimap:hover {
  opacity: 1;
}

.graph-hint {
  font-size: 0.8rem;
  color: var(--muted-color);
  text-align: center;
  margin: 0;
}

/* Graph statistics overlay */
.graph-stats-overlay {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(21, 24, 37, 0.1);
  border: 1px solid var(--border-separator);
  border-radius: 6px;
  padding: 0.5rem 0.65rem;
  font-size: 0.7rem;
  color: #9ca3af;
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  backdrop-filter: blur(4px);
  min-width: 130px;
}

.stats-overlay-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.stats-overlay-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stats-overlay-label {
  flex: 1;
  color: #9ca3af;
}

.stats-overlay-total {
  color: #c7d2fe;
  font-weight: 500;
}

.stats-overlay-count {
  font-weight: 600;
  color: #e0e7ff;
  text-align: right;
}

.stats-overlay-divider {
  height: 1px;
  background: var(--border-separator);
  margin: 0.15rem 0;
}
</style>
