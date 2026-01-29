/**
 * @fileoverview Partner risk classification service.
 * Classifies consent partners by risk level based on their business practices.
 * Uses pattern matching for known entities and optionally LLM for unknowns.
 */

import type { ConsentPartner } from '../types.js'
import { getOpenAIClient, getDeploymentName } from './openai.js'
import { createLogger, getErrorMessage, withRetry } from '../utils/index.js'

const log = createLogger('PartnerClassify')

// ============================================================================
// Types
// ============================================================================

/** Risk level for a data partner */
export type PartnerRiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'unknown'

/** Classification result for a partner */
export interface PartnerClassification {
  /** Original partner name */
  name: string
  /** Assessed risk level */
  riskLevel: PartnerRiskLevel
  /** Category of business */
  category: PartnerCategory
  /** Reason for the classification */
  reason: string
  /** Known privacy concerns */
  concerns: string[]
  /** Risk score contribution (0-10) */
  riskScore: number
}

/** Categories of partner businesses */
export type PartnerCategory =
  | 'data-broker'
  | 'advertising'
  | 'cross-site-tracking'
  | 'identity-resolution'
  | 'analytics'
  | 'social-media'
  | 'content-delivery'
  | 'fraud-prevention'
  | 'personalization'
  | 'measurement'
  | 'unknown'

/** Extended consent details with partner classifications */
export interface EnhancedConsentDetails {
  /** Original partner list */
  partners: ConsentPartner[]
  /** Classified partners with risk info */
  classifiedPartners: PartnerClassification[]
  /** Summary statistics */
  partnerStats: {
    total: number
    critical: number
    high: number
    medium: number
    low: number
    unknown: number
    totalRiskScore: number
  }
}

// ============================================================================
// Known Bad Actors Database
// Compiled from: EasyList, EasyPrivacy, Disconnect.me, DuckDuckGo Tracker Radar,
// Privacy Badger, uBlock Origin lists, and industry knowledge of tracking practices.
// ============================================================================

/**
 * Known data brokers - companies that aggregate and sell personal data.
 * These are the most privacy-invasive partners.
 * Sources: FTC data broker reports, California CCPA registry, Vermont data broker registry
 */
const DATA_BROKERS: Record<string, { concerns: string[]; aliases: string[] }> = {
  // === Major Data Aggregators ===
  'liveramp': {
    concerns: ['Cross-device identity resolution', 'Offline-to-online data matching', 'Data selling to 500+ partners', 'IdentityLink graph'],
    aliases: ['live ramp', 'liveramp holdings', 'liveramp inc'],
  },
  'acxiom': {
    concerns: ['2.5 billion consumer profiles', 'Data selling', 'Detailed demographic profiles', 'InfoBase database'],
    aliases: ['acxiom llc', 'acxiom corporation', 'acxiom marketing'],
  },
  'oracle data cloud': {
    concerns: ['Massive data aggregation', 'Cross-site tracking', 'Data marketplace', 'Purchases BlueKai, Datalogix, AddThis data'],
    aliases: ['oracle', 'bluekai', 'datalogix', 'oracle advertising', 'oracle moat', 'grapeshot'],
  },
  'experian': {
    concerns: ['Credit bureau data', 'Identity verification tied to tracking', 'Consumer profiling', 'Marketing services'],
    aliases: ['experian marketing', 'experian plc', 'experian marketing services', 'experian audience'],
  },
  'epsilon': {
    concerns: ['Consumer database of 250M+ Americans', 'Email tracking', 'Direct marketing data', 'Conversant ID'],
    aliases: ['epsilon data', 'epsilon digital', 'conversant', 'publicis epsilon'],
  },
  'transunion': {
    concerns: ['Credit data for marketing', 'TruVision data', 'Identity resolution', 'Signal platform'],
    aliases: ['transunion llc', 'transunion marketing', 'signal digital', 'neustar'],
  },
  'equifax': {
    concerns: ['Credit data integration', 'Financial profiling', 'Identity data', 'IXI Services wealth data'],
    aliases: ['equifax inc', 'equifax marketing', 'ixi services'],
  },
  
  // === Data Management Platforms (DMPs) ===
  'lotame': {
    concerns: ['Data management platform', 'Audience segmentation', 'Data selling', 'Panorama ID'],
    aliases: ['lotame solutions', 'lotame inc'],
  },
  'salesforce dmp': {
    concerns: ['Krux data', 'Cross-device tracking', 'CRM data matching', 'Audience Studio'],
    aliases: ['krux', 'salesforce audience studio', 'salesforce cdp'],
  },
  'adobe audience manager': {
    concerns: ['DMP with extensive tracking', 'Cross-device graphs', 'Data co-ops'],
    aliases: ['adobe aam', 'audience manager', 'adobe experience cloud'],
  },
  'nielsen': {
    concerns: ['TV viewing data', 'Cross-platform measurement', 'Demographic profiling', 'Exelate data'],
    aliases: ['nielsen marketing', 'nielsen digital', 'exelate', 'nielsen dmp'],
  },
  'comscore': {
    concerns: ['Web tracking panels', 'Audience measurement', 'Cross-platform tracking', 'Shareablee data'],
    aliases: ['comscore inc', 'comscore networks'],
  },
  
  // === People Search / Public Records ===
  'lexisnexis': {
    concerns: ['Public records aggregation', 'Identity verification', 'Risk assessment data', 'Accurint database'],
    aliases: ['lexis nexis', 'relx', 'lexisnexis risk', 'accurint'],
  },
  'thomson reuters': {
    concerns: ['CLEAR database', 'Public records', 'Identity verification'],
    aliases: ['thomson reuters risk', 'clear investigation'],
  },
  'intelius': {
    concerns: ['People search', 'Background checks', 'Personal data aggregation'],
    aliases: ['intelius inc', 'peopleconnect'],
  },
  'spokeo': {
    concerns: ['People search engine', 'Personal data aggregation', 'Social media scraping'],
    aliases: ['spokeo inc'],
  },
  'whitepages': {
    concerns: ['People search', 'Address history', 'Phone lookups'],
    aliases: ['whitepages inc', 'whitepages pro'],
  },
  'beenverified': {
    concerns: ['Background checks', 'People search', 'Personal data aggregation'],
    aliases: ['been verified'],
  },
  'truthfinder': {
    concerns: ['People search', 'Background checks', 'Public records'],
    aliases: ['truth finder'],
  },
  'instantcheckmate': {
    concerns: ['Background checks', 'Criminal records', 'Personal data'],
    aliases: ['instant checkmate'],
  },
  
  // === Location Data Brokers ===
  'safegraph': {
    concerns: ['Location data selling', 'Foot traffic data', 'POI data', 'Movement patterns'],
    aliases: ['safe graph'],
  },
  'foursquare': {
    concerns: ['Location intelligence', 'Place data', 'Attribution', 'Factual data'],
    aliases: ['foursquare labs', 'factual'],
  },
  'placer.ai': {
    concerns: ['Location analytics', 'Foot traffic', 'Consumer movement'],
    aliases: ['placer ai', 'placer labs'],
  },
  'gravy analytics': {
    concerns: ['Location data', 'Movement tracking', 'Consumer insights'],
    aliases: ['gravy'],
  },
  'cuebiq': {
    concerns: ['Location intelligence', 'Offline attribution', 'Mobility data'],
    aliases: [],
  },
  'x-mode': {
    concerns: ['Location data broker', 'Sold military location data', 'App SDK data'],
    aliases: ['xmode', 'x mode social', 'outlogic'],
  },
  'venntel': {
    concerns: ['Location data to government', 'Phone tracking', 'Movement patterns'],
    aliases: [],
  },
  
  // === Healthcare Data ===
  'iqvia': {
    concerns: ['Healthcare data', 'Prescription data', 'Medical information tracking', 'Patient-level data'],
    aliases: ['ims health', 'quintiles', 'iqvia holdings'],
  },
  'lexishealth': {
    concerns: ['Medical records', 'Healthcare marketing', 'Patient data'],
    aliases: [],
  },
  
  // === Financial Data ===
  'verisk': {
    concerns: ['Insurance data', 'Risk profiling', 'Claims data', 'Jornaya data'],
    aliases: ['verisk analytics', 'jornaya'],
  },
  'corelogic': {
    concerns: ['Property data', 'Real estate records', 'Consumer data'],
    aliases: ['core logic'],
  },
  'moodys': {
    concerns: ['Financial data', 'Credit analysis', 'Business intelligence'],
    aliases: ['moodys analytics', "moody's"],
  },
  
  // === Retail / Purchase Data ===
  'catalina': {
    concerns: ['Purchase data from retailers', 'Shopper marketing', 'Transaction data'],
    aliases: ['catalina marketing'],
  },
  'ibotta': {
    concerns: ['Receipt scanning', 'Purchase data', 'Consumer behavior'],
    aliases: ['ibotta inc'],
  },
  'ncs': {
    concerns: ['Purchase-based targeting', 'Transaction data', 'Consumer purchase history'],
    aliases: ['nielsen catalina', 'ncs solutions'],
  },
  'iri': {
    concerns: ['Purchase data', 'Consumer panel data', 'Retail analytics'],
    aliases: ['iri worldwide', 'information resources'],
  },
  'numerator': {
    concerns: ['Receipt scanning', 'Purchase data', 'Panel data'],
    aliases: ['numerator insights', 'infoscout'],
  },
  
  // === Email / Contact Data ===
  'zoominfo': {
    concerns: ['B2B contact data', 'Email harvesting', 'Company intelligence'],
    aliases: ['zoom info', 'zoominfo technologies'],
  },
  'clearbit': {
    concerns: ['Email enrichment', 'Company data', 'Identity resolution'],
    aliases: ['clearbit inc'],
  },
  'fullcontact': {
    concerns: ['Identity resolution', 'Contact data', 'Social profiles'],
    aliases: ['full contact'],
  },
  'pipl': {
    concerns: ['People search', 'Identity resolution', 'Email lookup'],
    aliases: ['pipl inc'],
  },
  'hunter.io': {
    concerns: ['Email finding', 'Contact scraping', 'Domain search'],
    aliases: ['hunter', 'email hunter'],
  },
  'lusha': {
    concerns: ['Contact data', 'Phone numbers', 'Email addresses'],
    aliases: ['lusha systems'],
  },
  'apollo.io': {
    concerns: ['Sales intelligence', 'Contact database', 'Email sequences'],
    aliases: ['apollo'],
  },
  
  // === Data Cooperatives ===
  'axiom': {
    concerns: ['Data co-op', 'Publisher data sharing', 'First-party data exchange'],
    aliases: [],
  },
  'eyeota': {
    concerns: ['Audience data marketplace', 'Third-party data', 'Cross-border data'],
    aliases: ['eyeota pte'],
  },
  'bombora': {
    concerns: ['B2B intent data', 'Company surge data', 'Content consumption tracking'],
    aliases: ['bombora inc'],
  },
}

/**
 * Identity resolution / Cross-device tracking companies.
 * These link your identity across devices, browsers, and sites.
 * Critical privacy concern as they build persistent identity graphs.
 */
const IDENTITY_TRACKERS: Record<string, { concerns: string[]; aliases: string[] }> = {
  // === Universal ID Providers ===
  'the trade desk': {
    concerns: ['Unified ID 2.0 creator', 'Cross-site tracking', 'Email-based identity', 'Programmatic advertising'],
    aliases: ['thetradedesk', 'trade desk', 'ttd', 'uid2', 'unified id'],
  },
  'id5': {
    concerns: ['Universal ID', 'Cross-site identity', 'Cookie replacement', 'Publisher identity'],
    aliases: ['id5 technology', 'id5.io'],
  },
  'liveramp ats': {
    concerns: ['Authenticated Traffic Solution', 'Email-based tracking', 'Cross-publisher identity'],
    aliases: ['ats', 'authenticated traffic'],
  },
  'digitrust': {
    concerns: ['Universal ID consortium', 'Cross-site identity', 'IAB standard'],
    aliases: ['digi trust'],
  },
  'sharedid': {
    concerns: ['Prebid universal ID', 'First-party cookie ID', 'Cross-site linking'],
    aliases: ['shared id', 'pubcommon'],
  },
  'lotame panorama': {
    concerns: ['People-based identity', 'Cookie-less tracking', 'Cross-device graph'],
    aliases: ['panorama id'],
  },
  'merkle': {
    concerns: ['Merkury identity platform', 'Cross-device resolution', 'CRM onboarding'],
    aliases: ['merkle inc', 'merkury'],
  },
  'infutor': {
    concerns: ['Identity resolution', 'Consumer data', 'Real-time identity'],
    aliases: ['infutor data'],
  },
  
  // === Device Graph Companies ===
  'tapad': {
    concerns: ['Cross-device tracking', 'Device graph with billions of devices', 'Probabilistic matching'],
    aliases: ['tapad inc'],
  },
  'drawbridge': {
    concerns: ['Cross-device identity', 'Probabilistic matching', 'Connected consumer graph'],
    aliases: ['drawbridge inc'],
  },
  'crosswise': {
    concerns: ['Cross-device targeting', 'Oracle owned', 'Device linking'],
    aliases: ['cross wise'],
  },
  'screen6': {
    concerns: ['Cross-device identity', 'Device graphs', 'IPG Mediabrands owned'],
    aliases: ['screen 6'],
  },
  'adbrain': {
    concerns: ['Cross-device tracking', 'Identity graph', 'Machine learning matching'],
    aliases: ['ad brain'],
  },
  
  // === CDP / Identity Platforms ===
  'zeotap': {
    concerns: ['Identity resolution', 'Customer data platform', 'Cross-device matching', 'European focus'],
    aliases: ['zeotap gmbh'],
  },
  'mparticle': {
    concerns: ['Customer data platform', 'Identity resolution', 'Mobile app tracking'],
    aliases: ['m particle'],
  },
  'segment': {
    concerns: ['Customer data platform', 'Event tracking', 'Identity stitching', 'Twilio owned'],
    aliases: ['segment.io', 'twilio segment'],
  },
  'tealium': {
    concerns: ['Customer data platform', 'Tag management', 'Identity resolution'],
    aliases: ['tealium inc'],
  },
  'blueconic': {
    concerns: ['Customer data platform', 'Profile unification', 'Real-time identity'],
    aliases: ['blue conic'],
  },
  'actioniq': {
    concerns: ['Customer data platform', 'Identity resolution', 'Enterprise data'],
    aliases: ['action iq'],
  },
  'amperity': {
    concerns: ['Customer data platform', 'Identity resolution', 'ML-based matching'],
    aliases: ['amperity inc'],
  },
  'treasure data': {
    concerns: ['Customer data platform', 'Identity graphs', 'Enterprise CDP'],
    aliases: ['treasuredata'],
  },
  
  // === Fingerprinting Services ===
  'fingerprintjs': {
    concerns: ['Browser fingerprinting', 'Device identification', 'Fraud detection with tracking'],
    aliases: ['fingerprint.js', 'fpjs', 'fingerprint pro', 'fingerprint.com'],
  },
  'iovation': {
    concerns: ['Device fingerprinting', 'Fraud prevention', 'Device reputation'],
    aliases: ['iovation inc', 'transunion iovation'],
  },
  'threatmetrix': {
    concerns: ['Device fingerprinting', 'Digital identity', 'LexisNexis owned'],
    aliases: ['threat metrix'],
  },
  'forter': {
    concerns: ['Device fingerprinting', 'Fraud prevention', 'Identity network'],
    aliases: ['forter inc'],
  },
  'sift': {
    concerns: ['Device fingerprinting', 'Fraud detection', 'Behavioral analysis'],
    aliases: ['sift science'],
  },
  'kount': {
    concerns: ['Device fingerprinting', 'Identity trust', 'Equifax owned'],
    aliases: ['kount inc'],
  },
  
  // === Mobile Identity ===
  'branch': {
    concerns: ['Mobile attribution', 'Deep linking', 'Cross-platform identity'],
    aliases: ['branch.io', 'branch metrics'],
  },
  'appsflyer': {
    concerns: ['Mobile attribution', 'Cross-device tracking', 'Install tracking'],
    aliases: ['apps flyer'],
  },
  'adjust': {
    concerns: ['Mobile attribution', 'App tracking', 'Cross-device'],
    aliases: ['adjust gmbh'],
  },
  'singular': {
    concerns: ['Mobile attribution', 'Cross-platform measurement', 'Marketing analytics'],
    aliases: ['singular.net'],
  },
  'kochava': {
    concerns: ['Mobile attribution', 'Fraud prevention', 'Cross-device'],
    aliases: ['kochava inc'],
  },
}

/**
 * Major advertising networks - track across many sites for ad targeting.
 * These companies have pixels/tags on millions of websites.
 */
const AD_NETWORKS: Record<string, { concerns: string[]; aliases: string[] }> = {
  // === Big Tech ===
  'google': {
    concerns: ['Tracks across 80%+ of websites', 'Search history', 'YouTube viewing', 'Gmail scanning', 'Android data'],
    aliases: ['google llc', 'google ireland', 'google ads', 'doubleclick', 'google marketing', 'google adsense', 'admob', 'google ad manager'],
  },
  'meta': {
    concerns: ['Facebook pixel on millions of sites', 'Instagram tracking', 'WhatsApp metadata', 'Shadow profiles', 'Off-Facebook activity'],
    aliases: ['facebook', 'meta platforms', 'facebook inc', 'fb', 'instagram', 'facebook pixel', 'meta pixel'],
  },
  'amazon': {
    concerns: ['Purchase history', 'Cross-site advertising', 'Alexa recordings', 'Ring doorbell data', 'AWS tracking'],
    aliases: ['amazon advertising', 'amazon.com', 'amazon ads', 'amazon dsp', 'amazon publisher services'],
  },
  'microsoft': {
    concerns: ['LinkedIn data', 'Bing search tracking', 'Windows telemetry', 'Xbox gaming data', 'Office 365 usage'],
    aliases: ['microsoft advertising', 'microsoft corporation', 'bing ads', 'msn', 'xandr'],
  },
  'apple': {
    concerns: ['App Store data', 'Apple Search Ads', 'First-party tracking', 'SKAdNetwork'],
    aliases: ['apple inc', 'apple advertising', 'apple search ads'],
  },
  
  // === Major DSPs/SSPs ===
  'criteo': {
    concerns: ['Retargeting across millions of sites', 'Behavioral profiling', 'Email matching', 'Shopper graph'],
    aliases: ['criteo sa', 'criteo inc'],
  },
  'xandr': {
    concerns: ['AT&T data', 'Programmatic advertising', 'Cross-device', 'Microsoft owned'],
    aliases: ['appnexus', 'at&t advertising', 'xandr inc'],
  },
  'magnite': {
    concerns: ['Largest independent SSP', 'CTV tracking', 'Real-time bidding'],
    aliases: ['rubicon project', 'telaria', 'spotx', 'springserve'],
  },
  'pubmatic': {
    concerns: ['Ad exchange', 'Real-time bidding', 'Publisher data', 'Identity hub'],
    aliases: ['pubmatic inc'],
  },
  'openx': {
    concerns: ['Ad exchange', 'Header bidding', 'Apollo owned'],
    aliases: ['openx technologies', 'openx software'],
  },
  'index exchange': {
    concerns: ['Ad marketplace', 'Header bidding', 'Publisher exchange'],
    aliases: ['indexexchange', 'casalemedia', 'ix'],
  },
  'sovrn': {
    concerns: ['Publisher monetization', 'Signal data', 'Commerce tracking'],
    aliases: ['sovrn holdings', 'lijit'],
  },
  'triplelift': {
    concerns: ['Native advertising', 'CTV', 'Programmatic'],
    aliases: ['triple lift'],
  },
  'viant': {
    concerns: ['Adelphic DSP', 'Household data', 'CTV'],
    aliases: ['adelphic', 'myspace data'],
  },
  'mediamath': {
    concerns: ['DSP', 'Identity linking', 'Cross-device', 'Bankrupt but data persists'],
    aliases: ['media math'],
  },
  'amobee': {
    concerns: ['DSP', 'TV data', 'Cross-platform', 'Tremor owned'],
    aliases: ['amobee inc', 'turn'],
  },
  'basis': {
    concerns: ['DSP', 'Programmatic', 'Centro platform'],
    aliases: ['basis technologies', 'centro'],
  },
  
  // === Content Recommendation / Native ===
  'taboola': {
    concerns: ['Content recommendation on 9000+ sites', 'Behavioral profiling', 'Click tracking'],
    aliases: ['taboola inc', 'taboola.com'],
  },
  'outbrain': {
    concerns: ['Content recommendation', 'Behavioral tracking', 'Interest profiling'],
    aliases: ['outbrain inc'],
  },
  'revcontent': {
    concerns: ['Content recommendation', 'Native ads', 'Behavioral tracking'],
    aliases: ['rev content'],
  },
  'mgid': {
    concerns: ['Native advertising', 'Content recommendation', 'Global tracking'],
    aliases: ['mgid inc'],
  },
  'nativo': {
    concerns: ['Native advertising', 'Brand content', 'Behavioral data'],
    aliases: ['nativo inc'],
  },
  
  // === Social Media Ad Platforms ===
  'tiktok': {
    concerns: ['Behavioral tracking', 'Video viewing', 'Interest profiling', 'ByteDance data sharing'],
    aliases: ['tiktok inc', 'bytedance', 'tiktok for business', 'tiktok pixel'],
  },
  'twitter': {
    concerns: ['Interest tracking', 'Social graph', 'Tweet engagement', 'Now X Corp'],
    aliases: ['twitter inc', 'x corp', 'twitter ads', 'x ads'],
  },
  'pinterest': {
    concerns: ['Visual interest tracking', 'Shopping behavior', 'Pin engagement', 'Conversion API'],
    aliases: ['pinterest inc'],
  },
  'snap': {
    concerns: ['Location tracking', 'Camera/AR data', 'Social interactions', 'Spectacles data'],
    aliases: ['snapchat', 'snap inc', 'snap pixel'],
  },
  'linkedin': {
    concerns: ['Professional profile data', 'Job interest tracking', 'B2B targeting', 'Microsoft owned'],
    aliases: ['linkedin corporation', 'linkedin ireland', 'linkedin insight tag'],
  },
  'reddit': {
    concerns: ['Interest community data', 'Engagement tracking', 'Conversation API'],
    aliases: ['reddit inc', 'reddit ads'],
  },
  'quora': {
    concerns: ['Interest tracking', 'Question engagement', 'B2B targeting'],
    aliases: ['quora inc', 'quora pixel'],
  },
  
  // === Programmatic / Ad Tech ===
  'tradingdesk': {
    concerns: ['Agency trading desk', 'Programmatic buying', 'Data aggregation'],
    aliases: ['trading desk'],
  },
  'adform': {
    concerns: ['European DSP', 'Cross-device', 'Flow ID'],
    aliases: ['adform a/s'],
  },
  'smartadserver': {
    concerns: ['Ad serving', 'European focus', 'Equativ owned'],
    aliases: ['smart adserver', 'equativ'],
  },
  'sizmek': {
    concerns: ['Ad serving', 'DCO', 'Amazon owned'],
    aliases: ['sizmek inc'],
  },
  'flashtalking': {
    concerns: ['Ad serving', 'DCO', 'Cross-device', 'Mediaocean owned'],
    aliases: ['flash talking'],
  },
  'innovid': {
    concerns: ['CTV advertising', 'Video tracking', 'Cross-platform'],
    aliases: ['innovid inc'],
  },
  'spotx': {
    concerns: ['Video advertising', 'CTV', 'Magnite owned'],
    aliases: ['spot x'],
  },
  'freewheel': {
    concerns: ['TV advertising', 'Video tracking', 'Comcast owned'],
    aliases: ['free wheel', 'freewheel media'],
  },
  
  // === Retail Media ===
  'criteo retail': {
    concerns: ['Retail media', 'Purchase data', 'On-site tracking'],
    aliases: ['criteo retail media'],
  },
  'citrusad': {
    concerns: ['Retail media', 'On-site ads', 'First-party data'],
    aliases: ['citrus ad'],
  },
  'instacart ads': {
    concerns: ['Grocery purchase data', 'Shopping behavior', 'CPG targeting'],
    aliases: ['instacart advertising'],
  },
  'walmart connect': {
    concerns: ['Purchase data', 'Retail media', 'In-store tracking'],
    aliases: ['walmart advertising', 'walmart dsp'],
  },
  
  // === Verification / Viewability ===
  'moat': {
    concerns: ['Ad verification with tracking', 'Viewability', 'Oracle owned'],
    aliases: ['moat analytics', 'oracle moat'],
  },
  'doubleverify': {
    concerns: ['Ad verification', 'Brand safety', 'Attention metrics'],
    aliases: ['double verify', 'dv'],
  },
  'integral ad science': {
    concerns: ['Ad verification', 'Brand safety', 'Context tracking'],
    aliases: ['ias', 'integral ad'],
  },
  
  // === Legacy / Other ===
  'verizon media': {
    concerns: ['Yahoo tracking', 'AOL data', 'Cross-property profiling'],
    aliases: ['oath', 'yahoo', 'aol', 'yahoo advertising', 'yahoo dsp'],
  },
  'sonobi': {
    concerns: ['Header bidding', 'Publisher monetization', 'JetStream'],
    aliases: ['sonobi inc'],
  },
  'sharethrough': {
    concerns: ['Native advertising', 'Header bidding', 'Equativ merged'],
    aliases: ['share through'],
  },
  '33across': {
    concerns: ['Header bidding', 'Publisher identity', 'Lexicon ID'],
    aliases: ['33 across'],
  },
  'gumgum': {
    concerns: ['Contextual advertising', 'Image recognition', 'In-image ads'],
    aliases: ['gum gum'],
  },
  'undertone': {
    concerns: ['High-impact ads', 'Video advertising', 'Perion owned'],
    aliases: ['undertone networks'],
  },
  'vibrant': {
    concerns: ['In-text advertising', 'Contextual', 'Undertone owned'],
    aliases: ['vibrant media'],
  },
  'yieldmo': {
    concerns: ['Mobile advertising', 'Attention analytics', 'Scroll depth'],
    aliases: ['yield mo'],
  },
  'teads': {
    concerns: ['Outstream video', 'Native video', 'Attention metrics'],
    aliases: ['teads sa'],
  },
  'seedtag': {
    concerns: ['Contextual advertising', 'AI targeting', 'Cookieless'],
    aliases: ['seed tag'],
  },
}

/**
 * Session replay / Behavioral analytics - record everything you do.
 * These services capture mouse movements, clicks, scrolls, and form inputs.
 */
const SESSION_REPLAY: Record<string, { concerns: string[]; aliases: string[] }> = {
  // === Major Session Replay ===
  'hotjar': {
    concerns: ['Session recording', 'Mouse tracking', 'Form field capture', 'Heatmaps', 'Survey data'],
    aliases: ['hotjar ltd'],
  },
  'fullstory': {
    concerns: ['Full session replay', 'All clicks/inputs recorded', 'Rage click detection', 'Privacy concerns'],
    aliases: ['fullstory inc'],
  },
  'logrocket': {
    concerns: ['Session replay', 'Console logging', 'Network request capture', 'User identification'],
    aliases: ['logrocket inc'],
  },
  'mouseflow': {
    concerns: ['Mouse tracking', 'Session recording', 'Form analytics', 'Friction detection'],
    aliases: ['mouseflow inc'],
  },
  'clarity': {
    concerns: ['Microsoft session replay', 'Free but Microsoft collects data', 'Heatmaps', 'Click tracking'],
    aliases: ['microsoft clarity', 'clarity.ms'],
  },
  'smartlook': {
    concerns: ['Session recording', 'Event tracking', 'User identification', 'Mobile recording'],
    aliases: ['smartlook.com'],
  },
  'lucky orange': {
    concerns: ['Session recordings', 'Dynamic heatmaps', 'Form analytics', 'Chat integration'],
    aliases: ['luckyorange', 'lucky orange inc'],
  },
  'inspectlet': {
    concerns: ['Session recording', 'Eye tracking heatmaps', 'Form analytics'],
    aliases: ['inspectlet inc'],
  },
  
  // === Product Analytics with Replay ===
  'heap': {
    concerns: ['Auto-capture ALL interactions', 'Retroactive analytics', 'Session replay', 'User tracking'],
    aliases: ['heap inc', 'heap analytics'],
  },
  'amplitude': {
    concerns: ['Product analytics', 'Session replay', 'User behavior', 'Cohort tracking'],
    aliases: ['amplitude inc', 'amplitude analytics'],
  },
  'mixpanel': {
    concerns: ['Event tracking', 'User analytics', 'Session replay add-on', 'Profile tracking'],
    aliases: ['mixpanel inc'],
  },
  'pendo': {
    concerns: ['Product analytics', 'Session replay', 'In-app tracking', 'User identification'],
    aliases: ['pendo.io', 'pendo inc'],
  },
  'gainsight px': {
    concerns: ['Product experience', 'User tracking', 'Session data', 'B2B focus'],
    aliases: ['gainsight', 'aptrinsic'],
  },
  'walkme': {
    concerns: ['Digital adoption', 'User tracking', 'Session data', 'Behavior analysis'],
    aliases: ['walk me'],
  },
  'whatfix': {
    concerns: ['Digital adoption', 'User tracking', 'In-app guidance'],
    aliases: ['what fix'],
  },
  
  // === Feedback / Survey Tools with Tracking ===
  'qualtrics': {
    concerns: ['Survey data', 'Experience tracking', 'Website intercepts', 'SAP owned'],
    aliases: ['qualtrics xm', 'qualtrics inc'],
  },
  'medallia': {
    concerns: ['Experience tracking', 'Customer feedback', 'Session data'],
    aliases: ['medallia inc'],
  },
  'usertesting': {
    concerns: ['User session recording', 'Think-aloud recordings', 'Behavioral observation'],
    aliases: ['user testing'],
  },
  'userzoom': {
    concerns: ['UX research', 'Session recording', 'User tracking'],
    aliases: ['user zoom'],
  },
  
  // === Error Tracking (with session context) ===
  'sentry': {
    concerns: ['Error tracking', 'Session replay', 'Breadcrumbs of user actions'],
    aliases: ['sentry.io', 'getsentry'],
  },
  'bugsnag': {
    concerns: ['Error tracking', 'User data', 'Session breadcrumbs'],
    aliases: ['bug snag'],
  },
  'rollbar': {
    concerns: ['Error tracking', 'User context', 'Session info'],
    aliases: ['rollbar inc'],
  },
  'raygun': {
    concerns: ['Error tracking', 'User tracking', 'Session data'],
    aliases: ['ray gun', 'mindscape'],
  },
  'datadog rum': {
    concerns: ['Real user monitoring', 'Session tracking', 'User journeys'],
    aliases: ['datadog', 'datadog rum'],
  },
  'new relic': {
    concerns: ['APM with user tracking', 'Browser monitoring', 'Session traces'],
    aliases: ['newrelic', 'new relic inc'],
  },
  'dynatrace': {
    concerns: ['APM', 'Real user monitoring', 'Session replay', 'User journey'],
    aliases: ['dynatrace llc'],
  },
  'appdynamics': {
    concerns: ['APM', 'End user monitoring', 'Session data', 'Cisco owned'],
    aliases: ['app dynamics'],
  },
  
  // === A/B Testing (with tracking) ===
  'optimizely': {
    concerns: ['A/B testing', 'User bucketing', 'Behavior tracking', 'Session data'],
    aliases: ['optimizely inc', 'episerver'],
  },
  'vwo': {
    concerns: ['A/B testing', 'Session recording', 'Heatmaps', 'User tracking'],
    aliases: ['visual website optimizer', 'wingify'],
  },
  'abtasty': {
    concerns: ['A/B testing', 'User segmentation', 'Personalization'],
    aliases: ['ab tasty'],
  },
  'kameleoon': {
    concerns: ['A/B testing', 'AI personalization', 'User tracking'],
    aliases: ['kameleoon sas'],
  },
  'convert': {
    concerns: ['A/B testing', 'User bucketing', 'Privacy-focused but tracks'],
    aliases: ['convert.com'],
  },
}

/**
 * Standard Analytics - less invasive than session replay but still track behavior.
 * Medium risk category.
 */
const ANALYTICS_TRACKERS: Record<string, { concerns: string[]; aliases: string[] }> = {
  // === Web Analytics ===
  'google analytics': {
    concerns: ['Page views', 'User journeys', 'Demographics', 'Interests', 'Cross-site with Google signals'],
    aliases: ['ga4', 'universal analytics', 'google analytics 4', 'gtag'],
  },
  'google tag manager': {
    concerns: ['Tag container', 'Script injection', 'Event tracking'],
    aliases: ['gtm'],
  },
  'adobe analytics': {
    concerns: ['Enterprise analytics', 'User tracking', 'Detailed behavioral data'],
    aliases: ['omniture', 'sitecatalyst', 'adobe experience cloud'],
  },
  'matomo': {
    concerns: ['Analytics platform', 'Can be privacy-respecting if self-hosted'],
    aliases: ['piwik', 'matomo analytics'],
  },
  'plausible': {
    concerns: ['Privacy-focused but still collects page views'],
    aliases: ['plausible.io'],
  },
  'fathom': {
    concerns: ['Privacy-focused analytics', 'Aggregate data'],
    aliases: ['fathom analytics', 'usefathom'],
  },
  'simple analytics': {
    concerns: ['Privacy-focused', 'No cookies', 'Still collects referrer data'],
    aliases: ['simpleanalytics'],
  },
  'chartbeat': {
    concerns: ['Real-time analytics', 'Attention tracking', 'Scroll depth'],
    aliases: ['chartbeat inc'],
  },
  'parsely': {
    concerns: ['Content analytics', 'Audience tracking', 'Automattic owned'],
    aliases: ['parse.ly'],
  },
  'piano': {
    concerns: ['Analytics', 'Paywall', 'Subscription tracking', 'User identification'],
    aliases: ['piano.io', 'at internet', 'cxense'],
  },
  
  // === Marketing Analytics ===
  'hubspot': {
    concerns: ['Marketing automation', 'Lead tracking', 'Email tracking', 'CRM integration'],
    aliases: ['hubspot inc'],
  },
  'marketo': {
    concerns: ['Marketing automation', 'Lead scoring', 'Behavioral tracking', 'Adobe owned'],
    aliases: ['marketo inc', 'adobe marketo'],
  },
  'pardot': {
    concerns: ['B2B marketing', 'Lead tracking', 'Email tracking', 'Salesforce owned'],
    aliases: ['salesforce pardot'],
  },
  'eloqua': {
    concerns: ['Marketing automation', 'Lead tracking', 'Oracle owned'],
    aliases: ['oracle eloqua'],
  },
  'mailchimp': {
    concerns: ['Email tracking', 'Open rates', 'Click tracking', 'Audience building'],
    aliases: ['mailchimp inc', 'intuit mailchimp'],
  },
  'klaviyo': {
    concerns: ['Email marketing', 'Customer profiles', 'Behavioral tracking'],
    aliases: ['klaviyo inc'],
  },
  'braze': {
    concerns: ['Customer engagement', 'Push notifications', 'Cross-channel tracking'],
    aliases: ['braze inc', 'appboy'],
  },
  'iterable': {
    concerns: ['Marketing automation', 'Cross-channel', 'User tracking'],
    aliases: ['iterable inc'],
  },
  'customer.io': {
    concerns: ['Marketing automation', 'Behavioral messaging', 'User tracking'],
    aliases: ['customerio'],
  },
  'intercom': {
    concerns: ['Customer messaging', 'User tracking', 'Behavior triggers'],
    aliases: ['intercom inc'],
  },
  'drift': {
    concerns: ['Conversational marketing', 'User tracking', 'Lead identification'],
    aliases: ['drift.com'],
  },
  'zendesk': {
    concerns: ['Customer support tracking', 'User identification', 'Ticket history'],
    aliases: ['zendesk inc'],
  },
  'freshworks': {
    concerns: ['CRM', 'Customer tracking', 'Behavioral data'],
    aliases: ['freshdesk', 'freshsales'],
  },
  
  // === Tag Management ===
  'tealium': {
    concerns: ['Tag management', 'CDP', 'Data layer', 'Identity resolution'],
    aliases: ['tealium inc', 'tealium iq'],
  },
  'ensighten': {
    concerns: ['Tag management', 'Privacy compliance', 'Data collection'],
    aliases: ['ensighten inc'],
  },
  'commanders act': {
    concerns: ['Tag management', 'European focus', 'Server-side tracking'],
    aliases: ['commandersact', 'tagcommander'],
  },
  'signal': {
    concerns: ['Tag management', 'Data onboarding', 'TransUnion owned'],
    aliases: ['signal digital'],
  },
  
  // === Attribution / Measurement ===
  'rockerbox': {
    concerns: ['Marketing attribution', 'Cross-channel measurement', 'User journey'],
    aliases: ['rockerbox inc'],
  },
  'measured': {
    concerns: ['Incrementality testing', 'Attribution', 'Media measurement'],
    aliases: ['measured inc'],
  },
  'neustar marketshare': {
    concerns: ['Marketing mix modeling', 'Attribution', 'TransUnion owned'],
    aliases: ['marketshare'],
  },
  'visual iq': {
    concerns: ['Attribution', 'Cross-channel', 'Nielsen owned'],
    aliases: ['visualiq'],
  },
  'windsor.ai': {
    concerns: ['Marketing attribution', 'Data integration', 'Cross-channel'],
    aliases: ['windsor'],
  },
}

/**
 * Consent Management Platforms - often track consent itself and share with partners.
 */
const CONSENT_PLATFORMS: Record<string, { concerns: string[]; aliases: string[] }> = {
  'onetrust': {
    concerns: ['Consent management', 'Shares consent data with partners', 'Cookie scanning'],
    aliases: ['one trust', 'onetrust llc'],
  },
  'cookiebot': {
    concerns: ['Consent management', 'Cookie scanning', 'Consent data sharing'],
    aliases: ['cybot', 'usercentrics cookiebot'],
  },
  'usercentrics': {
    concerns: ['Consent management', 'German focused', 'CMP'],
    aliases: ['user centrics'],
  },
  'trustarc': {
    concerns: ['Consent management', 'Privacy compliance', 'TrustE'],
    aliases: ['trust arc', 'truste'],
  },
  'quantcast choice': {
    concerns: ['Consent management', 'TCF', 'Part of Quantcast tracking'],
    aliases: ['quantcast cmp'],
  },
  'didomi': {
    concerns: ['Consent management', 'Preference center', 'European focus'],
    aliases: ['didomi inc'],
  },
  'sourcepoint': {
    concerns: ['Consent management', 'Adblock detection', 'Messaging'],
    aliases: ['source point'],
  },
  'termly': {
    concerns: ['Consent management', 'Policy generation', 'Cookie consent'],
    aliases: ['termly inc'],
  },
  'cookiefirst': {
    concerns: ['Consent management', 'Cookie scanning', 'Dutch'],
    aliases: ['cookie first'],
  },
  'consentmanager': {
    concerns: ['Consent management', 'German', 'TCF certified'],
    aliases: ['consent manager'],
  },
  'iubenda': {
    concerns: ['Consent management', 'Policy generation', 'Cookie solution'],
    aliases: ['iubenda srl'],
  },
  'osano': {
    concerns: ['Consent management', 'Data mapping', 'Privacy platform'],
    aliases: ['osano inc'],
  },
}

// ============================================================================
// Classification Functions
// ============================================================================

/**
 * Classify a single partner based on known databases.
 * Synchronous version for quick classification without LLM.
 * Exported for use in enriching consent details.
 */
export function classifyPartnerByPatternSync(partner: ConsentPartner): PartnerClassification | null {
  const nameLower = partner.name.toLowerCase().trim()
  const purposeLower = partner.purpose?.toLowerCase() || ''
  
  // Check data brokers (critical risk)
  for (const [key, data] of Object.entries(DATA_BROKERS)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'critical',
        category: 'data-broker',
        reason: `Known data broker that aggregates and sells personal information`,
        concerns: data.concerns,
        riskScore: 10,
      }
    }
  }
  
  // Check identity resolution (critical risk)
  for (const [key, data] of Object.entries(IDENTITY_TRACKERS)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'critical',
        category: 'identity-resolution',
        reason: `Identity resolution service that links your identity across devices and sites`,
        concerns: data.concerns,
        riskScore: 9,
      }
    }
  }
  
  // Check session replay (high risk)
  for (const [key, data] of Object.entries(SESSION_REPLAY)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'high',
        category: 'cross-site-tracking',
        reason: `Session replay service that records your interactions on the site`,
        concerns: data.concerns,
        riskScore: 8,
      }
    }
  }
  
  // Check ad networks (high risk)
  for (const [key, data] of Object.entries(AD_NETWORKS)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'high',
        category: 'advertising',
        reason: `Major advertising network that tracks across many websites`,
        concerns: data.concerns,
        riskScore: 7,
      }
    }
  }
  
  // Check analytics trackers (medium risk)
  for (const [key, data] of Object.entries(ANALYTICS_TRACKERS)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'medium',
        category: 'analytics',
        reason: `Analytics or marketing platform that collects behavioral data`,
        concerns: data.concerns,
        riskScore: 5,
      }
    }
  }
  
  // Check consent management platforms (medium risk - they share consent data)
  for (const [key, data] of Object.entries(CONSENT_PLATFORMS)) {
    if (nameLower.includes(key) || data.aliases.some(a => nameLower.includes(a))) {
      return {
        name: partner.name,
        riskLevel: 'medium',
        category: 'personalization',
        reason: `Consent management platform that may share consent signals`,
        concerns: data.concerns,
        riskScore: 4,
      }
    }
  }
  
  // Check purpose-based classification
  if (purposeLower.includes('sell') || purposeLower.includes('broker') || purposeLower.includes('data marketplace')) {
    return {
      name: partner.name,
      riskLevel: 'critical',
      category: 'data-broker',
      reason: `Partner purpose indicates data selling or brokering`,
      concerns: ['Data selling disclosed in purpose'],
      riskScore: 9,
    }
  }
  
  if (purposeLower.includes('cross-site') || purposeLower.includes('cross-device') || purposeLower.includes('identity')) {
    return {
      name: partner.name,
      riskLevel: 'high',
      category: 'cross-site-tracking',
      reason: `Partner purpose indicates cross-site or cross-device tracking`,
      concerns: ['Cross-site tracking disclosed'],
      riskScore: 7,
    }
  }
  
  if (purposeLower.includes('advertising') || purposeLower.includes('ads') || purposeLower.includes('marketing')) {
    return {
      name: partner.name,
      riskLevel: 'medium',
      category: 'advertising',
      reason: `Advertising or marketing partner`,
      concerns: ['Behavioral targeting likely'],
      riskScore: 5,
    }
  }
  
  if (purposeLower.includes('analytics') || purposeLower.includes('measurement')) {
    return {
      name: partner.name,
      riskLevel: 'medium',
      category: 'analytics',
      reason: `Analytics or measurement partner`,
      concerns: ['Behavioral data collection'],
      riskScore: 4,
    }
  }
  
  if (purposeLower.includes('fraud') || purposeLower.includes('security') || purposeLower.includes('bot')) {
    return {
      name: partner.name,
      riskLevel: 'low',
      category: 'fraud-prevention',
      reason: `Security or fraud prevention service`,
      concerns: [],
      riskScore: 2,
    }
  }
  
  if (purposeLower.includes('cdn') || purposeLower.includes('content delivery') || purposeLower.includes('hosting')) {
    return {
      name: partner.name,
      riskLevel: 'low',
      category: 'content-delivery',
      reason: `Content delivery or infrastructure partner`,
      concerns: [],
      riskScore: 1,
    }
  }
  
  return null
}

/**
 * Use LLM to classify unknown partners in batch.
 */
async function classifyUnknownPartnersWithLLM(
  partners: ConsentPartner[]
): Promise<Map<string, PartnerClassification>> {
  const results = new Map<string, PartnerClassification>()
  
  if (partners.length === 0) return results
  
  const client = getOpenAIClient()
  if (!client) {
    log.warn('OpenAI not configured, using default classification for unknown partners')
    for (const p of partners) {
      results.set(p.name, {
        name: p.name,
        riskLevel: 'unknown',
        category: 'unknown',
        reason: 'Could not classify - no pattern match',
        concerns: [],
        riskScore: 3, // Default medium-low risk
      })
    }
    return results
  }
  
  const deployment = getDeploymentName()
  
  // Batch partners for efficiency (max 20 at a time)
  const batches: ConsentPartner[][] = []
  for (let i = 0; i < partners.length; i += 20) {
    batches.push(partners.slice(i, i + 20))
  }
  
  for (const batch of batches) {
    const partnerList = batch.map(p => `- "${p.name}": ${p.purpose || 'No purpose specified'}`).join('\n')
    
    try {
      const response = await withRetry(
        () => client.chat.completions.create({
          model: deployment,
          messages: [
            {
              role: 'system',
              content: `You are a privacy expert analyzing data partners from a website's cookie consent dialog.
              
For each partner, classify their privacy risk level and category.

Risk levels:
- critical: Data brokers, identity resolution, companies that sell data
- high: Major ad networks, session replay, cross-device tracking
- medium: Standard advertising, analytics, personalization
- low: CDN, fraud prevention, essential services

Categories: data-broker, advertising, cross-site-tracking, identity-resolution, analytics, social-media, content-delivery, fraud-prevention, personalization, measurement

Respond with JSON array only:
[{"name": "Partner Name", "riskLevel": "high", "category": "advertising", "reason": "Brief reason", "concerns": ["concern1"], "riskScore": 7}]

Risk scores: critical=9-10, high=6-8, medium=4-5, low=1-3`,
            },
            {
              role: 'user',
              content: `Classify these partners:\n${partnerList}`,
            },
          ],
          max_completion_tokens: 1500,
        }),
        { context: 'Partner classification' }
      )
      
      const content = response.choices[0]?.message?.content || '[]'
      let jsonStr = content.trim()
      if (jsonStr.startsWith('```')) {
        jsonStr = jsonStr.replace(/```json?\n?/g, '').replace(/```$/g, '').trim()
      }
      
      const classifications = JSON.parse(jsonStr) as PartnerClassification[]
      for (const c of classifications) {
        results.set(c.name, c)
      }
    } catch (error) {
      log.warn('LLM partner classification failed for batch', { error: getErrorMessage(error) })
      // Fall back to unknown classification
      for (const p of batch) {
        if (!results.has(p.name)) {
          results.set(p.name, {
            name: p.name,
            riskLevel: 'unknown',
            category: 'unknown',
            reason: 'Classification failed',
            concerns: [],
            riskScore: 3,
          })
        }
      }
    }
  }
  
  return results
}

/**
 * Classify all partners from consent details.
 * Uses pattern matching first, then LLM for unknowns.
 */
export async function classifyPartners(
  partners: ConsentPartner[],
  useLLMForUnknowns: boolean = true
): Promise<EnhancedConsentDetails> {
  log.info('Classifying partners', { count: partners.length, useLLM: useLLMForUnknowns })
  
  const classified: PartnerClassification[] = []
  const unknowns: ConsentPartner[] = []
  
  // First pass: pattern matching
  for (const partner of partners) {
    const result = classifyPartnerByPatternSync(partner)
    if (result) {
      classified.push(result)
    } else {
      unknowns.push(partner)
    }
  }
  
  log.info('Pattern matching complete', { classified: classified.length, unknown: unknowns.length })
  
  // Second pass: LLM for unknowns (if enabled and there are unknowns)
  if (useLLMForUnknowns && unknowns.length > 0) {
    log.info('Classifying unknown partners with LLM...')
    const llmResults = await classifyUnknownPartnersWithLLM(unknowns)
    for (const [, classification] of llmResults) {
      classified.push(classification)
    }
  } else {
    // Add unknowns with default classification
    for (const p of unknowns) {
      classified.push({
        name: p.name,
        riskLevel: 'unknown',
        category: 'unknown',
        reason: 'No pattern match found',
        concerns: [],
        riskScore: 3,
      })
    }
  }
  
  // Calculate statistics
  const stats = {
    total: classified.length,
    critical: classified.filter(c => c.riskLevel === 'critical').length,
    high: classified.filter(c => c.riskLevel === 'high').length,
    medium: classified.filter(c => c.riskLevel === 'medium').length,
    low: classified.filter(c => c.riskLevel === 'low').length,
    unknown: classified.filter(c => c.riskLevel === 'unknown').length,
    totalRiskScore: classified.reduce((sum, c) => sum + c.riskScore, 0),
  }
  
  log.success('Partner classification complete', stats)
  
  return {
    partners,
    classifiedPartners: classified,
    partnerStats: stats,
  }
}

/**
 * Get a quick risk summary for partners without full classification.
 * Uses only pattern matching for speed.
 */
export function getPartnerRiskSummary(partners: ConsentPartner[]): {
  criticalCount: number
  highCount: number
  totalRiskScore: number
  worstPartners: string[]
} {
  let criticalCount = 0
  let highCount = 0
  let totalRiskScore = 0
  const worstPartners: string[] = []
  
  for (const partner of partners) {
    const result = classifyPartnerByPatternSync(partner)
    if (result) {
      totalRiskScore += result.riskScore
      if (result.riskLevel === 'critical') {
        criticalCount++
        worstPartners.push(`${partner.name} (${result.category})`)
      } else if (result.riskLevel === 'high') {
        highCount++
        if (worstPartners.length < 5) {
          worstPartners.push(`${partner.name} (${result.category})`)
        }
      }
    } else {
      totalRiskScore += 3 // Default for unknown
    }
  }
  
  return { criticalCount, highCount, totalRiskScore, worstPartners }
}
