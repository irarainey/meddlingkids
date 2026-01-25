/**
 * @fileoverview Script analysis service using LLM.
 * Analyzes JavaScript files to determine their purpose.
 */

import { getOpenAIClient, getDeploymentName } from './openai.js'
import { SCRIPT_ANALYSIS_SYSTEM_PROMPT, buildScriptAnalysisUserPrompt } from '../prompts/index.js'
import type { TrackedScript } from '../types.js'

/** Maximum script content length to send to LLM (in characters) */
const MAX_SCRIPT_LENGTH = 30000

/**
 * Known TRACKING scripts - these collect user data and should be highlighted.
 * Maps URL patterns to descriptions with behavioral details.
 */
const TRACKING_SCRIPTS: Array<{ pattern: RegExp; description: string }> = [
  // ============================================================================
  // ANALYTICS & MEASUREMENT
  // ============================================================================
  
  // Google
  { pattern: /google-analytics\.com|googletagmanager\.com\/gtag/, description: 'Google Analytics: Tracks page views, user sessions, demographics, and browsing behavior. Sends data to Google servers.' },
  { pattern: /googletagmanager\.com\/gtm/, description: 'Google Tag Manager: Container script that loads and manages other tracking scripts. Can inject any third-party code.' },
  { pattern: /googlesyndication\.com|googleadservices\.com|doubleclick\.net/, description: 'Google Ads: Displays targeted advertisements and tracks ad clicks and conversions across the Google ad network.' },
  { pattern: /google\.com\/recaptcha\/enterprise/, description: 'Google reCAPTCHA Enterprise: Bot detection that also collects behavioral signals and risk scores.' },
  
  // Meta/Facebook
  { pattern: /facebook\.net\/.*fbevents|connect\.facebook\.net/, description: 'Facebook Pixel: Tracks page visits, button clicks, and conversions. Enables ad retargeting across Facebook/Instagram.' },
  { pattern: /connect\.facebook\.net.*sdk/, description: 'Facebook SDK: Social plugins for likes, shares, and comments. Tracks logged-in Facebook users across the web.' },
  { pattern: /facebook\.com\/tr/, description: 'Facebook Tracking Pixel: Image-based tracker for conversion tracking and retargeting.' },
  
  // Microsoft
  { pattern: /clarity\.ms/, description: 'Microsoft Clarity: Records mouse movements, clicks, and scrolling. Creates session replays and heatmaps.' },
  { pattern: /bat\.bing\.com|bing\.com\/bat/, description: 'Microsoft Advertising (Bing Ads): Tracks conversions and enables ad targeting on Microsoft properties.' },
  
  // Other Major Analytics
  { pattern: /cdn\.amplitude\.com|amplitude\.com/, description: 'Amplitude: Product analytics tracking user actions, feature usage, and conversion paths.' },
  { pattern: /cdn\.mxpnl\.com|mixpanel\.com/, description: 'Mixpanel: Tracks user events, funnels, and retention. Builds user profiles from behavior data.' },
  { pattern: /cdn\.segment\.com|api\.segment\.io|segment\.com/, description: 'Segment: Customer data platform that collects events and routes them to multiple analytics/marketing tools.' },
  { pattern: /heap\.io|heapanalytics|cdn\.heapanalytics/, description: 'Heap Analytics: Auto-captures all user interactions including clicks, form submissions, and page views.' },
  { pattern: /static\.hotjar\.com|hotjar\.com/, description: 'Hotjar: Records mouse movements, clicks, scrolling, and form interactions. Creates session replay videos and heatmaps.' },
  { pattern: /fullstory\.com|fs\.js/, description: 'FullStory: Records complete user sessions including clicks, scrolls, and form inputs. Captures DOM snapshots for replay.' },
  { pattern: /plausible\.io/, description: 'Plausible: Privacy-focused analytics. Collects page views without cookies (but still tracks).' },
  { pattern: /matomo\.(js|php)|piwik/, description: 'Matomo/Piwik: Analytics tracking page views, events, and goals. Data sent to server.' },
  { pattern: /kissmetrics\.com|km\.js/, description: 'Kissmetrics: Behavioral analytics tracking individual user journeys and conversion funnels.' },
  { pattern: /woopra\.com/, description: 'Woopra: Real-time customer analytics tracking user behavior across devices.' },
  { pattern: /gauges\.com/, description: 'Gauges: Real-time web analytics tracking page views and visitor information.' },
  { pattern: /chartbeat\.com|static\.chartbeat/, description: 'Chartbeat: Real-time content analytics tracking reader engagement and scroll depth.' },
  { pattern: /parsely\.com|cdn\.parsely/, description: 'Parse.ly: Content analytics tracking article views, engagement, and reader behavior.' },
  { pattern: /clicky\.com/, description: 'Clicky: Real-time analytics tracking visitors, actions, and heatmaps.' },
  { pattern: /statcounter\.com/, description: 'StatCounter: Web analytics tracking visits, page views, and visitor details.' },
  { pattern: /getclicky\.com/, description: 'Clicky Analytics: Real-time visitor tracking with heatmaps and uptime monitoring.' },
  { pattern: /simpleanalytics\.com/, description: 'Simple Analytics: Analytics tracking page views (privacy-focused but still tracking).' },
  { pattern: /fathom\.com|usefathom/, description: 'Fathom Analytics: Privacy-focused analytics (still collects page view data).' },
  { pattern: /goatcounter\.com/, description: 'GoatCounter: Simple analytics tracking page views and referrers.' },
  { pattern: /umami\.is/, description: 'Umami: Self-hosted analytics tracking page views and events.' },
  { pattern: /splitbee\.io/, description: 'Splitbee: Analytics and A/B testing tracking user behavior and conversions.' },
  { pattern: /pirsch\.io/, description: 'Pirsch: Privacy-friendly analytics tracking page views and events.' },
  { pattern: /counter\.dev/, description: 'Counter.dev: Simple analytics tracking visitor counts and page views.' },
  
  // ============================================================================
  // SESSION RECORDING & HEATMAPS
  // ============================================================================
  { pattern: /mouseflow\.com/, description: 'Mouseflow: Records mouse movements, clicks, scrolls, and keystrokes. Creates session replays and heatmaps.' },
  { pattern: /luckyorange\.com|cdn\.luckyorange/, description: 'Lucky Orange: Records sessions, tracks mouse movements, creates heatmaps, and captures form analytics.' },
  { pattern: /crazyegg\.com|script\.crazyegg/, description: 'Crazy Egg: Creates heatmaps, scrollmaps, and session recordings of user behavior.' },
  { pattern: /logrocket\.com|cdn\.logrocket/, description: 'LogRocket: Session replay capturing user interactions, network requests, console logs, and Redux state.' },
  { pattern: /smartlook\.com|rec\.smartlook/, description: 'Smartlook: Session recording with heatmaps, event tracking, and funnel analysis.' },
  { pattern: /inspectlet\.com/, description: 'Inspectlet: Session recording capturing mouse movements, scrolls, clicks, and form interactions.' },
  { pattern: /sessioncam\.com/, description: 'SessionCam: Session replay with heatmaps, form analytics, and struggle detection.' },
  { pattern: /decibelinsight\.com|cdn\.decibelinsight/, description: 'Decibel (Medallia): Session replay and digital experience analytics.' },
  { pattern: /contentsquare\.com|cdn\.contentsquare/, description: 'Contentsquare: Digital experience analytics with session replay and zone-based heatmaps.' },
  { pattern: /glassbox\.com/, description: 'Glassbox: Session replay capturing every user interaction for experience analytics.' },
  { pattern: /quantum\.com|quantummetric/, description: 'Quantum Metric: Continuous product design capturing sessions and behavioral data.' },
  { pattern: /uxcam\.com/, description: 'UXCam: Mobile session recording capturing touches, gestures, and screen recordings.' },
  { pattern: /usertesting\.com/, description: 'UserTesting: Records user sessions for UX research and testing.' },
  { pattern: /userlytics\.com/, description: 'Userlytics: Remote user testing capturing screen recordings and interactions.' },
  
  // ============================================================================
  // ADVERTISING & AD TECH
  // ============================================================================
  
  // Major Ad Networks
  { pattern: /amazon-adsystem\.com/, description: 'Amazon Advertising: Serves targeted ads and tracks conversions for Amazon\'s advertising platform.' },
  { pattern: /adsrvr\.org|thetradedesk/, description: 'The Trade Desk: Programmatic advertising platform for real-time ad bidding and cross-device targeting.' },
  { pattern: /criteo\.com|criteo\.net/, description: 'Criteo: Retargeting ads based on browsing history. Tracks product views for personalized ad recommendations.' },
  { pattern: /adnxs\.com|appnexus/, description: 'Xandr/AppNexus: Ad exchange for real-time bidding. Tracks user behavior for ad targeting.' },
  { pattern: /rubiconproject\.com|magnite\.com/, description: 'Magnite/Rubicon: Ad exchange connecting publishers with advertisers through real-time bidding.' },
  { pattern: /pubmatic\.com/, description: 'PubMatic: Programmatic advertising platform for ad serving and real-time bidding.' },
  { pattern: /openx\.net|openx\.com/, description: 'OpenX: Ad exchange for programmatic advertising and real-time bidding.' },
  { pattern: /bidswitch\.net/, description: 'Bidswitch: Ad exchange routing bids between demand and supply platforms.' },
  { pattern: /casalemedia\.com|indexexchange/, description: 'Index Exchange: Programmatic advertising marketplace for real-time bidding.' },
  { pattern: /spotxchange\.com|spotx\.tv/, description: 'SpotX: Video advertising platform for programmatic ad serving.' },
  { pattern: /springserve\.com/, description: 'SpringServe: Video ad server tracking impressions and engagement.' },
  { pattern: /yieldmo\.com/, description: 'Yieldmo: Mobile advertising platform tracking ad engagement.' },
  
  // Social/Native Advertising
  { pattern: /outbrain\.com/, description: 'Outbrain: Content recommendation widgets showing sponsored articles based on user interests.' },
  { pattern: /taboola\.com/, description: 'Taboola: Content recommendation platform displaying sponsored links based on browsing behavior.' },
  { pattern: /sharethrough\.com/, description: 'Sharethrough: Native advertising platform that tracks engagement with sponsored content.' },
  { pattern: /revcontent\.com/, description: 'RevContent: Content recommendation network tracking clicks and engagement.' },
  { pattern: /mgid\.com/, description: 'MGID: Native advertising platform serving recommended content based on behavior.' },
  { pattern: /content\.ad/, description: 'Content.ad: Native advertising network tracking content engagement.' },
  { pattern: /zergnet\.com/, description: 'ZergNet: Content recommendation tracking article clicks and engagement.' },
  
  // Video Advertising
  { pattern: /teads\.tv|teads\.com/, description: 'Teads: Video advertising platform tracking video views and engagement.' },
  { pattern: /jwpltx\.com|jwplayer\.com.*advertising/, description: 'JW Player Advertising: Video ad serving and tracking.' },
  { pattern: /imasdk\.googleapis\.com/, description: 'Google IMA SDK: Video ad insertion tracking ad views and interactions.' },
  { pattern: /innovid\.com/, description: 'Innovid: Connected TV and video advertising platform.' },
  { pattern: /extreme-reach\.com|extremereach/, description: 'Extreme Reach: Video ad serving and creative distribution.' },
  
  // Demand Side Platforms (DSPs)
  { pattern: /mediamath\.com/, description: 'MediaMath: Demand-side platform for programmatic ad buying with user tracking.' },
  { pattern: /turn\.com/, description: 'Amobee (Turn): DSP for cross-channel advertising and audience targeting.' },
  { pattern: /dataxu\.com/, description: 'Roku/DataXu: DSP for TV and digital advertising with audience data.' },
  { pattern: /bidtellect\.com/, description: 'Bidtellect: Native advertising DSP tracking content engagement.' },
  { pattern: /simpli\.fi/, description: 'Simpli.fi: Localized programmatic advertising platform.' },
  { pattern: /centro\.net|basis\.net/, description: 'Basis (Centro): Programmatic advertising platform.' },
  
  // Supply Side Platforms (SSPs)
  { pattern: /sovrn\.com/, description: 'Sovrn: Publisher monetization tracking ad impressions and revenue.' },
  { pattern: /rhythmone\.com|unruly/, description: 'RhythmOne/Unruly: Video advertising SSP tracking engagement.' },
  { pattern: /freewheel\.com|freewheel\.tv/, description: 'FreeWheel: Video ad management platform for publishers.' },
  { pattern: /smartadserver\.com/, description: 'Smart AdServer: Ad serving platform tracking impressions and clicks.' },
  { pattern: /gumgum\.com/, description: 'GumGum: Contextual advertising using computer vision to analyze page content.' },
  { pattern: /33across\.com/, description: '33Across: Attention-based advertising measuring viewability.' },
  { pattern: /triplelift\.com/, description: 'TripleLift: Native programmatic advertising platform.' },
  { pattern: /kargo\.com/, description: 'Kargo: Mobile advertising platform tracking ad engagement.' },
  { pattern: /nativo\.com/, description: 'Nativo: Native advertising platform tracking content performance.' },
  
  // Ad Verification & Viewability
  { pattern: /moat\.com|moatads/, description: 'Moat (Oracle): Ad verification measuring viewability, attention, and brand safety.' },
  { pattern: /doubleverify\.com/, description: 'DoubleVerify: Ad verification tracking viewability, fraud, and brand safety.' },
  { pattern: /adsafeprotected\.com|integral-ad-science|iasds01/, description: 'Integral Ad Science: Ad verification measuring viewability and brand safety.' },
  { pattern: /meetrics\.com/, description: 'Meetrics: Ad verification tracking viewability in European markets.' },
  { pattern: /adloox\.com/, description: 'Adloox: Ad verification for fraud prevention and viewability.' },
  { pattern: /comscore\.com|scorecardresearch/, description: 'Comscore: Digital measurement tracking audiences, ads, and content consumption.' },
  { pattern: /nielsen\.com|imrworldwide/, description: 'Nielsen: Audience measurement tracking media consumption and demographics.' },
  
  // Retargeting & Remarketing
  { pattern: /adroll\.com/, description: 'AdRoll: Retargeting platform tracking site visitors for ad targeting across the web.' },
  { pattern: /perfectaudience\.com/, description: 'Perfect Audience: Retargeting platform tracking users for display and social ads.' },
  { pattern: /steelhouse\.com/, description: 'SteelHouse: Retargeting and performance advertising platform.' },
  { pattern: /retargeter\.com/, description: 'ReTargeter: Display retargeting tracking site visitors.' },
  { pattern: /fetchback\.com/, description: 'Fetchback: Retargeting platform for display advertising.' },
  { pattern: /triggit\.com/, description: 'Triggit: Retargeting and social advertising platform.' },
  
  // ============================================================================
  // SOCIAL MEDIA TRACKING
  // ============================================================================
  { pattern: /analytics\.tiktok\.com|tiktok\.com\/i18n\/pixel/, description: 'TikTok Pixel: Tracks user actions for ad attribution and retargeting on TikTok platform.' },
  { pattern: /snap\.licdn\.com|linkedin\.com\/.*insight/, description: 'LinkedIn Insight Tag: Tracks page visits and conversions. Enables B2B ad targeting based on company and job data.' },
  { pattern: /ads\.linkedin\.com/, description: 'LinkedIn Ads: Conversion tracking for LinkedIn advertising campaigns.' },
  { pattern: /platform\.twitter\.com|cdn\.syndication\.twimg|ads-twitter\.com/, description: 'Twitter/X Tracking: Tracks page visits and conversions for Twitter\'s ad platform.' },
  { pattern: /sc-static\.net|snapchat\.com.*pixel/, description: 'Snapchat Pixel: Tracks conversions and enables retargeting on Snapchat.' },
  { pattern: /platform\.instagram\.com/, description: 'Instagram Embeds: Displays Instagram content while sending viewing data to Meta.' },
  { pattern: /pinterest\.com\/(js|tag)/, description: 'Pinterest Tag: Tracks page visits and conversions for Pinterest advertising.' },
  { pattern: /reddit\.com\/pixel|redditmedia\.com/, description: 'Reddit Pixel: Tracks conversions for Reddit advertising campaigns.' },
  { pattern: /quora\.com\/_\/ad/, description: 'Quora Pixel: Tracks conversions for Quora advertising.' },
  { pattern: /addthis\.com/, description: 'AddThis: Social sharing buttons that track user behavior across sites for ad targeting.' },
  { pattern: /sharethis\.com/, description: 'ShareThis: Social sharing buttons with cross-site tracking for audience insights.' },
  { pattern: /addtoany\.com/, description: 'AddToAny: Social sharing buttons tracking share events and referrals.' },
  { pattern: /sumo\.com|sumome/, description: 'Sumo: Email capture and social sharing tools tracking visitor behavior.' },
  
  // ============================================================================
  // CUSTOMER DATA PLATFORMS & DATA MANAGEMENT
  // ============================================================================
  { pattern: /mparticle\.com/, description: 'mParticle: Customer data platform collecting and routing user data to marketing tools.' },
  { pattern: /rudderstack\.com/, description: 'RudderStack: Customer data platform collecting events and syncing to warehouses.' },
  { pattern: /tealium\.com|tags\.tiqcdn/, description: 'Tealium: Tag management and customer data platform collecting user data.' },
  { pattern: /ensighten\.com/, description: 'Ensighten: Tag management platform controlling third-party tracking scripts.' },
  { pattern: /signal\.co|signalco/, description: 'Signal: Customer identity platform tracking users across channels.' },
  { pattern: /lytics\.io|lytics\.com/, description: 'Lytics: Customer data platform building profiles from behavioral data.' },
  { pattern: /blueconic\.com/, description: 'BlueConic: Customer data platform creating unified profiles from interactions.' },
  { pattern: /zaius\.com/, description: 'Zaius (Optimizely): B2C customer data platform tracking purchase behavior.' },
  { pattern: /arm\.com\/treasure-data|treasuredata/, description: 'Treasure Data: Enterprise customer data platform aggregating user data.' },
  { pattern: /bluekai\.com/, description: 'Oracle BlueKai: Data management platform for audience targeting.' },
  { pattern: /krux\.com|salesforce\.com\/dmp/, description: 'Salesforce DMP (Krux): Data management platform for audience segmentation.' },
  { pattern: /lotame\.com/, description: 'Lotame: Data management platform for audience data and targeting.' },
  { pattern: /eyeota\.com/, description: 'Eyeota: Audience data marketplace for ad targeting.' },
  { pattern: /bombora\.com/, description: 'Bombora: B2B intent data tracking business research behavior.' },
  { pattern: /clearbit\.com/, description: 'Clearbit: B2B data enrichment identifying visitors by company.' },
  { pattern: /demandbase\.com/, description: 'Demandbase: B2B account identification tracking company visitors.' },
  { pattern: /6sense\.com/, description: '6sense: B2B intent data tracking buyer research signals.' },
  { pattern: /zoominfo\.com/, description: 'ZoomInfo: B2B data platform tracking company and contact information.' },
  { pattern: /leadfeeder\.com/, description: 'Leadfeeder: B2B lead generation identifying companies visiting your site.' },
  { pattern: /albacross\.com/, description: 'Albacross: B2B lead generation tracking company visitors.' },
  
  // ============================================================================
  // MARKETING AUTOMATION & EMAIL
  // ============================================================================
  { pattern: /hubspot\.com|hs-scripts|hs-analytics/, description: 'HubSpot: Marketing automation tracking page views, form submissions, and email engagement.' },
  { pattern: /marketo\.com|munchkin\.js|marketo\.net/, description: 'Marketo: Marketing automation tracking web activity and email engagement for lead scoring.' },
  { pattern: /pardot\.com|pi\.pardot/, description: 'Pardot (Salesforce): B2B marketing automation tracking visitor behavior and email engagement.' },
  { pattern: /eloqua\.com/, description: 'Oracle Eloqua: Marketing automation tracking digital body language across channels.' },
  { pattern: /act-on\.com/, description: 'Act-On: Marketing automation tracking website visits and email engagement.' },
  { pattern: /mailchimp\.com|chimpstatic|list-manage/, description: 'Mailchimp: Email marketing tracking opens, clicks, and website activity.' },
  { pattern: /klaviyo\.com/, description: 'Klaviyo: E-commerce email marketing tracking purchase behavior and browsing.' },
  { pattern: /sendinblue\.com|sibautomation/, description: 'Brevo (Sendinblue): Email marketing tracking opens, clicks, and site activity.' },
  { pattern: /constantcontact\.com/, description: 'Constant Contact: Email marketing tracking engagement metrics.' },
  { pattern: /activecampaign\.com/, description: 'ActiveCampaign: Marketing automation tracking email and site behavior.' },
  { pattern: /drip\.com/, description: 'Drip: E-commerce marketing automation tracking customer behavior.' },
  { pattern: /getresponse\.com/, description: 'GetResponse: Email marketing tracking engagement and conversions.' },
  { pattern: /convertkit\.com/, description: 'ConvertKit: Creator email marketing tracking subscriber behavior.' },
  { pattern: /aweber\.com/, description: 'AWeber: Email marketing tracking opens, clicks, and engagement.' },
  { pattern: /infusionsoft\.com|keap\.com/, description: 'Keap (Infusionsoft): CRM and marketing automation tracking contacts.' },
  { pattern: /ontraport\.com/, description: 'Ontraport: Marketing automation tracking leads and customer behavior.' },
  { pattern: /sharpspring\.com/, description: 'SharpSpring: Marketing automation tracking web and email engagement.' },
  { pattern: /customer\.io/, description: 'Customer.io: Messaging platform tracking user behavior for triggered campaigns.' },
  { pattern: /iterable\.com/, description: 'Iterable: Cross-channel marketing tracking user engagement.' },
  { pattern: /braze\.com|appboy/, description: 'Braze: Customer engagement platform tracking behavior across channels.' },
  { pattern: /leanplum\.com/, description: 'Leanplum: Mobile marketing automation tracking in-app behavior.' },
  { pattern: /onesignal\.com/, description: 'OneSignal: Push notification service tracking user engagement and devices.' },
  { pattern: /pushwoosh\.com/, description: 'Pushwoosh: Push notifications tracking user engagement and device tokens.' },
  { pattern: /airship\.com|urbanairship/, description: 'Airship: Mobile engagement tracking push notifications and in-app behavior.' },
  
  // ============================================================================
  // CONSENT MANAGEMENT (logs consent choices)
  // ============================================================================
  { pattern: /onetrust\.com|cookielaw\.org|optanon/, description: 'OneTrust: Consent management platform logging user consent choices and preferences.' },
  { pattern: /cookiebot\.com|consent\.cookiebot/, description: 'Cookiebot: Cookie consent platform scanning cookies and logging consent decisions.' },
  { pattern: /trustarc\.com|truste\.com/, description: 'TrustArc: Privacy compliance platform managing and logging consent preferences.' },
  { pattern: /quantcast\.com.*choice|quantcast\.mgr/, description: 'Quantcast Choice: Consent management with audience measurement and tracking.' },
  { pattern: /sourcepoint\.com|cdn\.privacy-mgmt/, description: 'Sourcepoint: Consent management platform logging user privacy decisions.' },
  { pattern: /didomi\.io/, description: 'Didomi: Consent management platform collecting and storing user privacy preferences.' },
  { pattern: /iubenda\.com/, description: 'Iubenda: Privacy and cookie compliance platform logging consent.' },
  { pattern: /termly\.io/, description: 'Termly: Consent management logging cookie preferences.' },
  { pattern: /osano\.com/, description: 'Osano: Data privacy platform tracking consent across properties.' },
  { pattern: /securiti\.ai/, description: 'Securiti: Privacy management platform with consent tracking.' },
  { pattern: /consentmanager\.net/, description: 'Consentmanager: CMP logging user consent preferences.' },
  { pattern: /usercentrics\.eu|usercentrics\.com/, description: 'Usercentrics: Consent management platform logging privacy preferences.' },
  
  // ============================================================================
  // A/B TESTING & PERSONALIZATION
  // ============================================================================
  { pattern: /optimizely\.com/, description: 'Optimizely: A/B testing platform modifying page content and tracking conversion rates.' },
  { pattern: /cdn\.vwo\.com|visualwebsiteoptimizer/, description: 'VWO: A/B testing tool changing page elements and measuring conversion impact.' },
  { pattern: /cdn\.ab-tasty\.com|abtasty/, description: 'AB Tasty: Experimentation platform for A/B tests, personalization, and feature flags.' },
  { pattern: /launchdarkly\.com/, description: 'LaunchDarkly: Feature flag platform tracking feature usage and user segments.' },
  { pattern: /split\.io/, description: 'Split.io: Feature flag and experimentation platform tracking feature performance.' },
  { pattern: /kameleoon\.com/, description: 'Kameleoon: A/B testing and personalization tracking user segments.' },
  { pattern: /conductrics\.com/, description: 'Conductrics: Machine learning optimization tracking user behavior.' },
  { pattern: /evergage\.com/, description: 'Evergage (Salesforce): Real-time personalization tracking visitor behavior.' },
  { pattern: /monetate\.com|monetate\.net/, description: 'Monetate: Personalization platform tracking behavior for targeted experiences.' },
  { pattern: /dynamicyield\.com/, description: 'Dynamic Yield: Personalization engine tracking behavior for recommendations.' },
  { pattern: /qubit\.com/, description: 'Qubit: Personalization platform tracking customer behavior.' },
  { pattern: /certona\.com/, description: 'Certona (Kibo): Personalization tracking behavior for product recommendations.' },
  { pattern: /barilliance\.com/, description: 'Barilliance: E-commerce personalization tracking shopping behavior.' },
  { pattern: /nosto\.com/, description: 'Nosto: E-commerce personalization tracking browsing and purchase behavior.' },
  
  // ============================================================================
  // CUSTOMER SUPPORT & CHAT (track user identity)
  // ============================================================================
  { pattern: /intercom\.io|intercomcdn/, description: 'Intercom: Live chat tracking user identity, page views, and enabling targeted messaging.' },
  { pattern: /zendesk\.com|zdassets\.com/, description: 'Zendesk: Customer support widget tracking visitor information and behavior.' },
  { pattern: /drift\.com/, description: 'Drift: Conversational marketing chat tracking visitors and qualifying leads.' },
  { pattern: /crisp\.chat/, description: 'Crisp: Live chat with visitor tracking, co-browsing, and session recording.' },
  { pattern: /livechat\.com|livechatinc/, description: 'LiveChat: Chat widget tracking visitor information and browsing behavior.' },
  { pattern: /tawk\.to/, description: 'Tawk.to: Chat widget tracking visitor location, pages viewed, and device info.' },
  { pattern: /olark\.com/, description: 'Olark: Chat widget with visitor tracking and CRM integration.' },
  { pattern: /freshdesk\.com|freshchat/, description: 'Freshchat: Customer messaging tracking visitor data and behavior.' },
  { pattern: /helpscout\.com|helpscout\.net/, description: 'Help Scout: Customer support tracking visitor and conversation data.' },
  { pattern: /gorgias\.com/, description: 'Gorgias: E-commerce support tracking customer data and order history.' },
  { pattern: /tidio\.com/, description: 'Tidio: Chat and bot platform tracking visitor behavior.' },
  { pattern: /chatra\.io/, description: 'Chatra: Live chat tracking visitor information and behavior.' },
  { pattern: /userlike\.com/, description: 'Userlike: Chat software tracking visitor data across channels.' },
  { pattern: /comm100\.com/, description: 'Comm100: Omnichannel support tracking visitor interactions.' },
  { pattern: /podium\.com/, description: 'Podium: Messaging platform tracking customer interactions.' },
  { pattern: /qualified\.com/, description: 'Qualified: B2B chat identifying and tracking company visitors.' },
  
  // ============================================================================
  // PERFORMANCE & ERROR MONITORING (collects session data)
  // ============================================================================
  { pattern: /newrelic\.com|nr-data\.net/, description: 'New Relic: Application monitoring tracking page loads, errors, and user sessions with device info.' },
  { pattern: /sentry\.io|browser\.sentry-cdn/, description: 'Sentry: Error tracking capturing exceptions with user context, device info, and breadcrumbs.' },
  { pattern: /datadoghq\.com|dd-rum/, description: 'Datadog RUM: Real user monitoring tracking page performance, errors, and user sessions.' },
  { pattern: /raygun\.io/, description: 'Raygun: Crash reporting capturing errors with user and device information.' },
  { pattern: /bugsnag\.com/, description: 'Bugsnag: Error monitoring capturing exceptions with user context and session data.' },
  { pattern: /rollbar\.com/, description: 'Rollbar: Error tracking capturing exceptions with user and deployment context.' },
  { pattern: /trackjs\.com/, description: 'TrackJS: JavaScript error tracking with user context and session timeline.' },
  { pattern: /airbrake\.io/, description: 'Airbrake: Error monitoring capturing exceptions with user and environment data.' },
  { pattern: /appdynamics\.com/, description: 'AppDynamics: Application performance monitoring tracking user sessions and errors.' },
  { pattern: /dynatrace\.com/, description: 'Dynatrace: Full-stack monitoring tracking real user sessions and behavior.' },
  { pattern: /speedcurve\.com/, description: 'SpeedCurve: Performance monitoring tracking page speed and user experience.' },
  { pattern: /pingdom\.com/, description: 'Pingdom: Website monitoring tracking uptime and real user performance.' },
  { pattern: /catchpoint\.com/, description: 'Catchpoint: Digital experience monitoring tracking performance globally.' },
  { pattern: /calibreapp\.com/, description: 'Calibre: Performance monitoring tracking page speed and core web vitals.' },
  { pattern: /webpagetest\.org\/beacon/, description: 'WebPageTest: Performance testing with real user monitoring.' },
  { pattern: /tracekit|stacktrace\.js/, description: 'TraceKit/StackTrace.js: Error capturing library sending stack traces to servers.' },
  
  // ============================================================================
  // FINGERPRINTING & IDENTITY RESOLUTION
  // ============================================================================
  { pattern: /fingerprintjs|fpjs\.io/, description: 'FingerprintJS: Creates unique device fingerprints from browser attributes for user identification.' },
  { pattern: /iovation\.com/, description: 'Iovation: Device fingerprinting and fraud detection using browser and device attributes.' },
  { pattern: /threatmetrix\.com|lexisnexis.*threatmetrix/, description: 'ThreatMetrix: Device fingerprinting for fraud prevention using behavioral biometrics.' },
  { pattern: /seon\.io/, description: 'SEON: Fraud prevention using device fingerprinting and email/phone analysis.' },
  { pattern: /castle\.io/, description: 'Castle: Account security using device fingerprinting and behavioral analysis.' },
  { pattern: /forter\.com/, description: 'Forter: Fraud prevention tracking device and behavioral signals.' },
  { pattern: /riskified\.com/, description: 'Riskified: E-commerce fraud prevention using device and behavioral fingerprinting.' },
  { pattern: /signifyd\.com/, description: 'Signifyd: Fraud protection using device intelligence and behavioral analysis.' },
  { pattern: /kount\.com/, description: 'Kount: Fraud prevention using device fingerprinting and AI risk scoring.' },
  { pattern: /socure\.com/, description: 'Socure: Identity verification using device and behavioral analysis.' },
  { pattern: /liveramp\.com|rlcdn\.com/, description: 'LiveRamp: Identity resolution connecting user data across platforms and devices.' },
  { pattern: /tapad\.com/, description: 'Tapad: Cross-device identity graph linking users across devices.' },
  { pattern: /drawbridge\.com/, description: 'Drawbridge: Cross-device identity resolution for advertising.' },
  { pattern: /crosswise\.com/, description: 'Crosswise (Oracle): Device graph connecting users across devices.' },
  { pattern: /id5\.io|id5-sync/, description: 'ID5: Universal ID solution for cross-site user identification.' },
  { pattern: /theadex\.com/, description: 'The Adex: Identity resolution for programmatic advertising.' },
  { pattern: /zeotap\.com/, description: 'Zeotap: Identity resolution and data platform.' },
  
  // ============================================================================
  // SURVEYS, FEEDBACK & USER RESEARCH
  // ============================================================================
  { pattern: /qualtrics\.com/, description: 'Qualtrics: Survey platform tracking responses and user feedback with targeting.' },
  { pattern: /surveymonkey\.com|surveymonkey\.net/, description: 'SurveyMonkey: Survey tool collecting responses and tracking completion.' },
  { pattern: /typeform\.com/, description: 'Typeform: Interactive surveys tracking responses and completion rates.' },
  { pattern: /hotjar\.com.*feedback|usabilla/, description: 'Usabilla: Feedback collection tracking user sentiment and page context.' },
  { pattern: /medallia\.com/, description: 'Medallia: Experience management capturing feedback across touchpoints.' },
  { pattern: /getfeedback\.com/, description: 'GetFeedback: Survey platform collecting responses in-context.' },
  { pattern: /satismeter\.com/, description: 'Satismeter: NPS surveys tracking customer satisfaction.' },
  { pattern: /wootric\.com/, description: 'Wootric: NPS and customer feedback tracking satisfaction scores.' },
  { pattern: /delighted\.com/, description: 'Delighted: NPS surveys collecting and tracking customer feedback.' },
  { pattern: /nicereply\.com/, description: 'Nicereply: Customer satisfaction surveys tracking support ratings.' },
  { pattern: /promoter\.io/, description: 'Promoter.io: NPS platform tracking customer loyalty scores.' },
  { pattern: /survicate\.com/, description: 'Survicate: Survey platform with targeting based on behavior.' },
  { pattern: /refiner\.io/, description: 'Refiner: In-product surveys tracking user feedback and segments.' },
  { pattern: /uservoice\.com/, description: 'UserVoice: Feedback platform tracking feature requests and votes.' },
  { pattern: /canny\.io/, description: 'Canny: Feature request tracking and user feedback collection.' },
  
  // ============================================================================
  // E-COMMERCE & CONVERSION TRACKING
  // ============================================================================
  { pattern: /shopify\.com.*analytics|shopifycloud.*monorail/, description: 'Shopify Analytics: E-commerce tracking capturing purchases and shopping behavior.' },
  { pattern: /yotpo\.com/, description: 'Yotpo: Reviews and UGC platform tracking purchases and customer behavior.' },
  { pattern: /trustpilot\.com/, description: 'Trustpilot: Reviews platform tracking purchases for review invitations.' },
  { pattern: /bazaarvoice\.com/, description: 'Bazaarvoice: Reviews and UGC tracking product interactions.' },
  { pattern: /powerreviews\.com/, description: 'PowerReviews: Reviews platform tracking purchase behavior.' },
  { pattern: /okendo\.io/, description: 'Okendo: Reviews platform tracking customer purchases.' },
  { pattern: /stamped\.io/, description: 'Stamped: Reviews and loyalty tracking customer behavior.' },
  { pattern: /judge\.me/, description: 'Judge.me: Product reviews tracking purchases.' },
  { pattern: /loox\.io/, description: 'Loox: Photo reviews tracking purchase behavior.' },
  { pattern: /aftership\.com/, description: 'AfterShip: Shipment tracking collecting delivery data.' },
  { pattern: /attentivemobile\.com|attn\.tv/, description: 'Attentive: SMS marketing tracking subscriber behavior and purchases.' },
  { pattern: /postscript\.io/, description: 'Postscript: SMS marketing tracking shopping behavior.' },
  { pattern: /sms bump|yotpo.*sms/, description: 'SMSBump/Yotpo SMS: SMS marketing tracking customer behavior.' },
  { pattern: /recharge\.com|rechargepayments/, description: 'ReCharge: Subscription platform tracking recurring purchases.' },
  { pattern: /bold\.com|boldcommerce/, description: 'Bold Commerce: E-commerce apps tracking purchase behavior.' },
  { pattern: /privy\.com/, description: 'Privy: Email popups tracking visitor behavior for capture.' },
  { pattern: /justuno\.com/, description: 'Justuno: Conversion popups tracking visitor behavior.' },
  { pattern: /optinmonster\.com/, description: 'OptinMonster: Lead capture tracking visitor behavior for popups.' },
  { pattern: /wisepops\.com/, description: 'Wisepops: Popup builder tracking visitor targeting and conversions.' },
  { pattern: /popupsmart\.com/, description: 'Popupsmart: Popup platform tracking visitor behavior.' },
  { pattern: /sleeknote\.com/, description: 'Sleeknote: Popup platform tracking visitor engagement.' },
  
  // ============================================================================
  // AFFILIATE & REFERRAL TRACKING
  // ============================================================================
  { pattern: /impact\.com|impactradius/, description: 'Impact: Affiliate tracking platform monitoring referrals and conversions.' },
  { pattern: /partnerstack\.com/, description: 'PartnerStack: Partner tracking monitoring referrals and revenue.' },
  { pattern: /shareasale\.com/, description: 'ShareASale: Affiliate network tracking referrals and sales.' },
  { pattern: /cj\.com|commission-junction/, description: 'CJ Affiliate: Affiliate tracking monitoring clicks and conversions.' },
  { pattern: /rakuten.*advertising|linksynergy/, description: 'Rakuten Advertising: Affiliate tracking for conversions.' },
  { pattern: /awin\.com|zanox/, description: 'Awin: Affiliate network tracking referrals and sales.' },
  { pattern: /pepperjam\.com/, description: 'Pepperjam: Affiliate tracking for e-commerce.' },
  { pattern: /refersion\.com/, description: 'Refersion: Affiliate and influencer tracking.' },
  { pattern: /rewardful\.com/, description: 'Rewardful: Affiliate tracking for SaaS referrals.' },
  { pattern: /leaddyno\.com/, description: 'LeadDyno: Affiliate tracking for referral programs.' },
  { pattern: /tapfiliate\.com/, description: 'Tapfiliate: Affiliate tracking and management.' },
  { pattern: /referralcandy\.com/, description: 'ReferralCandy: Referral program tracking.' },
  { pattern: /mention-me\.com/, description: 'Mention Me: Referral tracking and advocacy.' },
  { pattern: /friendbuy\.com/, description: 'Friendbuy: Referral program tracking conversions.' },
  { pattern: /extole\.com/, description: 'Extole: Referral marketing tracking shares and conversions.' },
  
  // ============================================================================
  // ATTRIBUTION & MEASUREMENT
  // ============================================================================
  { pattern: /branch\.io/, description: 'Branch: Mobile attribution tracking app installs and deep links.' },
  { pattern: /appsflyer\.com/, description: 'AppsFlyer: Mobile attribution tracking installs, events, and ad spend.' },
  { pattern: /adjust\.com/, description: 'Adjust: Mobile attribution tracking installs and in-app events.' },
  { pattern: /kochava\.com/, description: 'Kochava: Mobile attribution and measurement platform.' },
  { pattern: /singular\.net/, description: 'Singular: Marketing analytics and attribution platform.' },
  { pattern: /tenjin\.io/, description: 'Tenjin: Mobile attribution and analytics.' },
  { pattern: /attribution\.com|convertro/, description: 'Attribution (Singular): Multi-touch attribution tracking.' },
  { pattern: /rockerbox\.com/, description: 'Rockerbox: Marketing attribution across channels.' },
  { pattern: /measured\.com/, description: 'Measured: Marketing measurement and attribution.' },
  { pattern: /northbeam\.io/, description: 'Northbeam: E-commerce attribution tracking.' },
  { pattern: /triplewhale\.com/, description: 'Triple Whale: E-commerce attribution and analytics.' },
  { pattern: /leadsrx\.com/, description: 'LeadsRx: Marketing attribution platform.' },
  { pattern: /wicked-reports|wickedreports/, description: 'Wicked Reports: Marketing attribution for e-commerce.' },
  { pattern: /windsor\.io/, description: 'Windsor.ai: Marketing attribution aggregating ad data.' },
]

/**
 * Benign scripts that don't collect user data - skip LLM analysis for these.
 * We'll give them a simple description and move on.
 */
const BENIGN_SCRIPTS: Array<{ pattern: RegExp; description: string }> = [
  // Common Libraries/Frameworks
  { pattern: /jquery([\.-]|\/)/, description: 'jQuery library - does not track users' },
  { pattern: /react[\.-]|react-dom|reactjs/, description: 'React framework - does not track users' },
  { pattern: /angular[\.-]|angularjs/, description: 'Angular framework - does not track users' },
  { pattern: /vue[\.-]|vue\.js|vuejs/, description: 'Vue.js framework - does not track users' },
  { pattern: /lodash[\.-]/, description: 'Lodash utility library - does not track users' },
  { pattern: /moment[\.-]|momentjs/, description: 'Moment.js date library - does not track users' },
  { pattern: /bootstrap[\.-]/, description: 'Bootstrap UI framework - does not track users' },
  { pattern: /popper[\.-]/, description: 'Popper.js positioning library - does not track users' },
  { pattern: /axios[\.-]/, description: 'Axios HTTP client - does not track users' },
  { pattern: /underscore[\.-]/, description: 'Underscore.js utility library - does not track users' },
  { pattern: /backbone[\.-]/, description: 'Backbone.js framework - does not track users' },
  { pattern: /ember[\.-]/, description: 'Ember.js framework - does not track users' },
  { pattern: /svelte[\.-]/, description: 'Svelte framework - does not track users' },
  { pattern: /preact[\.-]/, description: 'Preact framework - does not track users' },
  { pattern: /d3[\.-]|d3js/, description: 'D3.js visualization library - does not track users' },
  { pattern: /chart[\.-]|chartjs/, description: 'Chart.js visualization library - does not track users' },
  { pattern: /three[\.-]|threejs/, description: 'Three.js 3D library - does not track users' },
  { pattern: /gsap[\.-]|greensock/, description: 'GSAP animation library - does not track users' },
  { pattern: /anime[\.-]|animejs/, description: 'Anime.js animation library - does not track users' },
  { pattern: /swiper[\.-]/, description: 'Swiper slider library - does not track users' },
  { pattern: /slick[\.-]/, description: 'Slick carousel library - does not track users' },
  { pattern: /owl[\.-]carousel/, description: 'Owl Carousel library - does not track users' },
  { pattern: /lazysizes|lazyload/, description: 'Lazy loading library - does not track users' },
  { pattern: /polyfill|core-js|babel/, description: 'Browser compatibility polyfill - does not track users' },
  { pattern: /modernizr/, description: 'Modernizr feature detection - does not track users' },
  { pattern: /normalize/, description: 'Normalize.css helper - does not track users' },
  { pattern: /tailwind/, description: 'Tailwind CSS framework - does not track users' },
  { pattern: /fontawesome|fa-/, description: 'Font Awesome icons - does not track users' },
  { pattern: /material[\.-]ui|mui/, description: 'Material UI components - does not track users' },
  { pattern: /ant[\.-]design|antd/, description: 'Ant Design components - does not track users' },
  { pattern: /semantic[\.-]ui/, description: 'Semantic UI framework - does not track users' },
  
  // CDNs hosting libraries (generic)
  { pattern: /cdnjs\.cloudflare\.com/, description: 'Cloudflare CDN library - likely benign utility code' },
  { pattern: /unpkg\.com/, description: 'unpkg CDN package - likely benign utility code' },
  { pattern: /jsdelivr\.net/, description: 'jsDelivr CDN library - likely benign utility code' },
  { pattern: /ajax\.googleapis\.com/, description: 'Google CDN hosted library - likely benign utility code' },
  { pattern: /code\.jquery\.com/, description: 'jQuery CDN - does not track users' },
  { pattern: /stackpath\.bootstrapcdn/, description: 'Bootstrap CDN - does not track users' },
  { pattern: /maxcdn\.bootstrapcdn/, description: 'Bootstrap CDN - does not track users' },
  
  // Common site functionality
  { pattern: /recaptcha|grecaptcha/, description: 'Google reCAPTCHA - bot detection (not user tracking)' },
  { pattern: /hcaptcha/, description: 'hCaptcha - bot detection (not user tracking)' },
  { pattern: /turnstile/, description: 'Cloudflare Turnstile - bot detection (not user tracking)' },
  { pattern: /stripe\.com|stripe\.js/, description: 'Stripe payments - processes payments (PCI compliant)' },
  { pattern: /paypal\.com/, description: 'PayPal payments - processes payments securely' },
  { pattern: /braintree/, description: 'Braintree payments - processes payments securely' },
  { pattern: /maps\.google|maps-api/, description: 'Google Maps - displays maps (minimal tracking)' },
  { pattern: /mapbox/, description: 'Mapbox - displays maps (minimal tracking)' },
  { pattern: /youtube\.com\/iframe_api|youtube\.com\/player/, description: 'YouTube player - video playback' },
  { pattern: /vimeo\.com\/player|player\.vimeo/, description: 'Vimeo player - video playback' },
  { pattern: /jwplayer/, description: 'JW Player - video playback' },
  { pattern: /videojs|video\.js/, description: 'Video.js player - does not track users' },
  { pattern: /plyr/, description: 'Plyr video player - does not track users' },
]

/**
 * Check if a script is a known tracking script.
 * @returns Description if it's a tracking script, null otherwise
 */
function identifyTrackingScript(url: string): string | null {
  for (const { pattern, description } of TRACKING_SCRIPTS) {
    if (pattern.test(url)) {
      return description
    }
  }
  return null
}

/**
 * Check if a script is a known benign script (should skip LLM analysis).
 * @returns Description if it's benign, null otherwise
 */
function identifyBenignScript(url: string): string | null {
  for (const { pattern, description } of BENIGN_SCRIPTS) {
    if (pattern.test(url)) {
      return description
    }
  }
  return null
}

/**
 * Fetch a script's content for analysis.
 * 
 * @param url - The script URL
 * @returns The script content or null if fetch failed
 */
async function fetchScriptContent(url: string): Promise<string | null> {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000) // 5 second timeout
    
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (compatible; SecurityAnalyzer/1.0)',
      },
    })
    
    clearTimeout(timeoutId)
    
    if (!response.ok) {
      return null
    }
    
    const content = await response.text()
    return content
  } catch {
    return null
  }
}

/**
 * Analyze a single script using LLM.
 * 
 * @param scriptContent - The JavaScript content (will be truncated if too long)
 * @param url - The script URL for context
 * @returns A short description of the script's purpose
 */
async function analyzeScriptWithLLM(scriptContent: string, url: string): Promise<string> {
  const client = getOpenAIClient()
  if (!client) {
    return 'Analysis unavailable - OpenAI not configured'
  }

  const deployment = getDeploymentName()
  
  // Truncate content if too long
  const truncatedContent = scriptContent.length > MAX_SCRIPT_LENGTH
    ? scriptContent.substring(0, MAX_SCRIPT_LENGTH) + '\n... [truncated]'
    : scriptContent

  try {
    const response = await client.chat.completions.create({
      model: deployment,
      messages: [
        { role: 'system', content: SCRIPT_ANALYSIS_SYSTEM_PROMPT },
        { role: 'user', content: buildScriptAnalysisUserPrompt(url, truncatedContent) },
      ],
      max_completion_tokens: 150,
      temperature: 0.3, // Lower temperature for more consistent results
    })

    const description = response.choices[0]?.message?.content?.trim() || 'Purpose unclear'
    return description
  } catch (error) {
    console.error('Script analysis error:', error)
    return 'Analysis failed'
  }
}

/**
 * Progress callback for script analysis.
 */
export type ScriptAnalysisProgressCallback = (current: number, total: number) => void

/**
 * Analyze multiple scripts to determine their purposes.
 * Uses pattern matching for known tracking/benign scripts and LLM for unknown ones.
 * Only analyzes unknown scripts with LLM - skips benign libraries/frameworks.
 * 
 * @param scripts - Array of tracked scripts to analyze
 * @param maxLLMAnalyses - Maximum number of scripts to analyze with LLM (default: 20)
 * @param onProgress - Optional callback for progress updates
 * @returns Scripts with descriptions added
 */
export async function analyzeScripts(
  scripts: TrackedScript[],
  maxLLMAnalyses: number = 20,
  onProgress?: ScriptAnalysisProgressCallback
): Promise<TrackedScript[]> {
  const results: TrackedScript[] = []
  const unknownScripts: Array<{ script: TrackedScript; index: number }> = []

  // First pass: identify known scripts by URL pattern
  for (let i = 0; i < scripts.length; i++) {
    const script = scripts[i]
    
    // Check if it's a known tracking script
    const trackingDescription = identifyTrackingScript(script.url)
    if (trackingDescription) {
      results.push({ ...script, description: trackingDescription })
      continue
    }
    
    // Check if it's a known benign script (skip LLM analysis)
    const benignDescription = identifyBenignScript(script.url)
    if (benignDescription) {
      results.push({ ...script, description: benignDescription })
      continue
    }
    
    // Unknown script - queue for LLM analysis
    results.push({ ...script, description: 'Analyzing...' })
    unknownScripts.push({ script, index: i })
  }

  // Second pass: analyze unknown scripts with LLM (limited to maxLLMAnalyses)
  const scriptsToAnalyze = unknownScripts.slice(0, maxLLMAnalyses)
  const totalToAnalyze = scriptsToAnalyze.length
  let analyzedCount = 0
  
  if (scriptsToAnalyze.length > 0) {
    console.log(`Analyzing ${scriptsToAnalyze.length} unknown scripts with LLM (skipped ${scripts.length - unknownScripts.length} known scripts)...`)
    
    // Process in parallel (batches of 5 to avoid rate limits)
    const batchSize = 5
    for (let i = 0; i < scriptsToAnalyze.length; i += batchSize) {
      const batch = scriptsToAnalyze.slice(i, i + batchSize)
      
      const analysisPromises = batch.map(async ({ script, index }) => {
        // Try to fetch script content
        const content = await fetchScriptContent(script.url)
        
        if (content) {
          const description = await analyzeScriptWithLLM(content, script.url)
          results[index] = { ...results[index], description }
        } else {
          // Couldn't fetch content - try to infer from URL
          results[index] = { ...results[index], description: inferFromUrl(script.url) }
        }
        
        // Update progress
        analyzedCount++
        if (onProgress) {
          onProgress(analyzedCount, totalToAnalyze)
        }
      })
      
      await Promise.all(analysisPromises)
    }
  } else {
    console.log('All scripts identified from known patterns, no LLM analysis needed')
  }

  // Mark remaining unknown scripts (beyond maxLLMAnalyses)
  for (let i = maxLLMAnalyses; i < unknownScripts.length; i++) {
    const { index, script } = unknownScripts[i]
    results[index] = { ...results[index], description: inferFromUrl(script.url) }
  }

  return results
}

/**
 * Infer a script's purpose from its URL when content is unavailable.
 * 
 * @param url - The script URL
 * @returns A best-guess description
 */
function inferFromUrl(url: string): string {
  const urlLower = url.toLowerCase()
  
  // Check filename patterns
  if (urlLower.includes('analytics')) return 'Analytics script'
  if (urlLower.includes('tracking') || urlLower.includes('tracker')) return 'Tracking script'
  if (urlLower.includes('pixel')) return 'Tracking pixel'
  if (urlLower.includes('consent') || urlLower.includes('gdpr') || urlLower.includes('privacy')) return 'Consent/privacy related'
  if (urlLower.includes('chat') || urlLower.includes('widget')) return 'Chat or widget script'
  if (urlLower.includes('ads') || urlLower.includes('advert')) return 'Advertising script'
  if (urlLower.includes('social') || urlLower.includes('share')) return 'Social sharing script'
  if (urlLower.includes('vendor') || urlLower.includes('third-party')) return 'Third-party vendor script'
  if (urlLower.includes('polyfill')) return 'Browser compatibility polyfill'
  if (urlLower.includes('main') || urlLower.includes('app') || urlLower.includes('bundle')) return 'Application bundle'
  if (urlLower.includes('chunk')) return 'Code-split chunk'
  
  return 'Third-party script'
}
