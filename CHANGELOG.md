
# Changelog

## 1.6.3

### Fixed

- **Device emulation user agent bug** — Fixed a critical issue where device emulation (mobile/tablet/desktop) did not apply the intended user agent string. All browser sessions now use the correct `user_agent` for the selected device, ensuring accurate content and consent dialog rendering for mobile and tablet analysis.

## 1.6.2

### Added

- **JSON-wrapped TC/AC String extraction** — new 5-tier consent string discovery
  cascade. Tier 3 uses regex-based patterns to extract TC/AC strings from
  JSON-structured localStorage values (e.g. Sourcepoint
  `_sp_user_consent_{propertyId}` → `gdpr.euconsent`). Tier 5 adds a heuristic
  JSON scanner that searches all JSON storage values for well-known field names
  (`euconsent`, `tcString`, `addtlConsent`, etc.) up to 3 levels deep.
- **CMP profile `storage_key_patterns`** — Sourcepoint profile now includes
  regex+JSON-path patterns for TC String extraction from localStorage, enabling
  TC/AC decoding on all Sourcepoint-powered sites (Guardian, Reach, FT, JPI
  Media, etc.) where the consent string is stored in JSON rather than a cookie.
- **Amazon Publisher Services (APS) storage pattern** — `aps:` prefixed
  localStorage keys are now recognised as APS header bidding vendor enablement
  data in the tracking storage database.
- **Standard consent keys in localStorage** — `euconsent-v2` and
  `addtl_consent` added to the tier 1 named localStorage lookup, covering CMPs
  (e.g. Didomi) that mirror the standard cookie names to localStorage.
- **CMP node colour in network graph** — consent management platform domains
  (Sourcepoint, Cookiebot, Didomi, TrustArc, Usercentrics, consentmanager, etc.)
  are now classified as "Consent Management" in the tracker network graph and
  rendered in cyan (`#06b6d4`), making CMP traffic visually distinct from other
  third-party categories.
- **Session replay node colour in network graph** — session replay and
  experience-analytics domains (Hotjar, FullStory, Microsoft Clarity, LogRocket,
  Mouseflow, Smartlook, Contentsquare, Crazy Egg, etc.) are now classified as
  "Session Replay" and rendered in pink (`#ec4899`), distinguishing them from
  regular analytics nodes.
- **Clickable category legend in network graph** — legend items are now
  single-select filter buttons. Click a category to isolate it plus the full
  path chain back to the origin (e.g. clicking "Social" reveals
  origin → advertising → social chains). Click again or press "Show all" to
  reset. The origin node is always visible and cannot be toggled off.
- **Enhanced domain classification to reduce "other" nodes** — three-tier
  server-side pipeline (Disconnect list → partner databases → domain keyword
  heuristics) replaces the previous two-tier approach. Disconnect
  Email/EmailAggressive categories are now classified as advertising instead of
  "other", and a new regex-based keyword heuristic catches domains with obvious
  keywords (adserver, analytics, metrics, fingerprint, etc.) that aren't in any
  curated database. Client-side `lookupCategory()` also now checks domain
  keyword patterns before falling back to "other".
- **First-party node classification in network graph** — domains sharing the
  same base domain as the analysed URL (including two-part TLDs like `.co.uk`)
  are now classified as "First Party" and rendered in light green (`#86efac`),
  distinguishing site-owned resources from third-party trackers.
- **First-party domain aliases** — configurable alias map
  (`FIRST_PARTY_ALIASES`) allows related domains to be recognised as first-party
  (e.g. `theguardian.com` → `guim.co.uk`, `guardianapis.com`;
  `bbc.co.uk` → `bbci.co.uk`).
- **CDN / Infrastructure category in network graph** — content delivery and
  infrastructure domains (~70 patterns including Google CDN, Cloudflare,
  Akamai, Fastly, AWS, Azure, etc.) are now classified as "CDN /
  Infrastructure" and rendered in teal (`#14b8a6`), reducing noise in the
  "other" category.
- **Subdomain prefix heuristic** — when a domain falls through all
  classification tiers, the leftmost subdomain label is checked against known
  CDN prefixes (cdn, static, assets, fonts, etc.), advertising prefixes (ad,
  ads, pixel, tag, etc.), and analytics prefixes (analytics, tracking, metrics,
  etc.) before falling back to "other".
- **Disconnect classification overrides** — `_DISCONNECT_OVERRIDES` map in
  `domain_classifier.py` corrects known Disconnect misclassifications (e.g.
  `dotmetrics.net` reclassified from advertising to analytics — it is Ipsos Iris
  audience measurement).
- **Script source viewer** — clicking any script URL in the Scripts tab opens
  a fullscreen dialog showing the script's source code with syntax highlighting
  (highlight.js) and automatic formatting of minified code (js-beautify). The
  dialog displays the AI-generated script description, a copy-to-clipboard
  button, and a link to the original URL. Scripts are fetched via a server-side
  proxy (`POST /api/fetch-script`) to avoid CORS restrictions.
- **Script fetch proxy endpoint** — new `POST /api/fetch-script` server
  endpoint that fetches remote JavaScript content on behalf of the client,
  capped at 512 KB with a 10-second timeout.

### Fixed

- **Network graph minimap not updating on zoom/pan** — the minimap viewport
  rectangle now redraws on every zoom and pan event, not only during simulation
  ticks, so it correctly tracks the visible area after the force layout settles.
- **Network graph not resizing when closing fullscreen notes** — the graph
  container now uses flex-based layout (`flex: 1 1 0`) instead of a fixed
  `calc(100vh - 200px)` height, so it properly fills the available space when
  the notes panel is toggled.
- **Category filter buttons not working with new categories** — first-party
  nodes were unconditionally added to the reachable set, bypassing the BFS
  filter. First-party is now an interactive toggle like all other categories.
- **Empty category buttons visible in legend** — category buttons in the graph
  legend are now hidden when no nodes of that type exist in the current graph
  data.

### Changed

- **TC/AC discovery cascade expanded from 3 tiers to 5** — the existing named
  lookup → CMP-aware → heuristic pipeline now includes JSON-wrapped storage
  (tier 3) and JSON heuristic scan (tier 5) stages, ensuring consent strings
  embedded inside JSON localStorage values are found.

## 1.6.1

### Added

- **Deterministic domain classifier** — new `domain_classifier` module classifies
  network graph domains using the Disconnect and partner databases before
  resorting to an LLM call, reducing token usage and ensuring the tracking
  technologies section is populated even when the LLM fails.
- **Token estimation logging** — `TimingChatMiddleware` now logs an approximate
  input token count at INFO level before every LLM call for request-size
  visibility.
- **`OutputTruncatedError`** — new non-retryable subclass of `EmptyResponseError`
  raised when the LLM returns `finish_reason=length` with no usable text,
  preventing pointless retry loops.
- **Responses API support** — `llm_client.get_chat_client()` accepts a
  `use_responses_api` flag to create an `AzureOpenAIResponsesClient` instead of
  `AzureOpenAIChatClient`, required for models (e.g. codex) that do not support
  the Chat Completions endpoint.
- **`use_responses_api` agent attribute** — `BaseAgent` exposes a class-level
  flag so individual agents can opt into the Responses API for their override
  deployment.

### Changed

- **Reduced LLM context size** — removed JSON pretty-printing (`indent=None`),
  enabled `exclude_defaults=True` on `DomainBreakdown` serialisation, and trimmed
  verbose instructional prose in context builder functions.
- **Raised `max_tokens`** — structured report sections increased from 2048 to
  4096; `ScriptAnalysisAgent` increased from 200 to 500, eliminating silent
  output truncation on Azure OpenAI structured output calls.
- **`ScriptAnalysisAgent` uses Responses API** — the codex override deployment
  now uses `AzureOpenAIResponsesClient`, avoiding a guaranteed
  `OperationNotSupported` 400 error on every script analysis call.

### Fixed

- **Responses API version auto-upgrade** — when the configured Azure API version
  is older than `2025-03-01-preview`, the Responses client automatically upgrades
  to the minimum required version, preventing immediate 400 errors.
- **`ScriptAnalysisAgent` concurrent fallback race condition** — when multiple
  scripts run via `asyncio.gather()`, only the first failure activated the
  fallback; subsequent concurrent failures incorrectly gave up. The agent now
  detects that another call already activated the fallback and retries with the
  current (already-swapped) client.
- **Broadened `_is_model_error` detection** — now also matches API-version
  incompatibility errors (`is enabled only for api-version`), ensuring the
  fallback activates for these failures as a safety net.
- **`finish_reason=length` detection** — `_check_empty_response` now raises
  `OutputTruncatedError` (non-retryable) when the LLM truncates output, with a
  WARN-level log including deployment metadata.
- **Section parse failure logging** — structured report section failures now log
  LLM response metadata (model, finish reason, token counts) for diagnostics.
