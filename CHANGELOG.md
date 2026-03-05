
# Changelog

## 1.7.2

### Fixed
- **Container UI message** - Updated container UI listening message to reflect the correct host.
- **Version number** - Corrected version number to match release version.

## 1.7.1

### Fixed
- **GitHub Actions workflow** - Set provenance: false on the build-push step to prevent untagged attestation manifests being created, and Removed attestations: write and id-token: write permissions, which were only required for provenance signing.

## 1.7.0

### Fixed

- **Unresponsive browser detection and automatic recovery** — When a browser context close times out, the session now signals the shared `PlaywrightManager` via `mark_health_suspect()`. Before the next session is created, a health probe opens and closes a throwaway context within 10 seconds. If the probe fails, the browser is automatically torn down and restarted. This prevents the server from becoming stuck after scanning ad-heavy sites.
- **Session creation timeout** — `create_session()` is now wrapped in a 30-second hard timeout so a completely hung browser can never block the server indefinitely. On timeout, the browser is marked as health-suspect and `TimeoutError` propagates, allowing the next request to start with a fresh browser.
- **ScriptAnalysisAgent fallback on empty responses** — The agent now falls back to the default model when the primary deployment returns an empty or unparseable response, not just on exceptions.
- **Deterministic severity sorting in structured reports** — Privacy risk factors, cookie groups, consent discrepancies, social media risks, and data collection items are now sorted by severity (critical → positive) after LLM generation, so the UI always shows the most important issues first regardless of LLM output order.
- **Summary findings sorted by severity** — Both the structured parse path and the text-fallback path now sort findings by severity (critical first, positive last).

### Changed

- **Per-section LLM context** — The structured report agent now builds tailored context for each of its 9 report sections using a `SectionNeeds` configuration matrix, including only the data blocks each section actually requires. This reduces token usage by 30–90% per section compared to sending the full context every time.
- **Domain breakdown grouped by organization** — Third-party domains and domain breakdowns in the LLM context are now grouped by parent organization (e.g. Google, Meta, Amazon) using the domain classifier, compressing ~40% of context characters.
- **Heavy reference databases removed from tracking analysis context** — The GDPR/TCF reference (~4.5K chars), tracking cookie database (~13K chars), and Disconnect database (~11K chars) are no longer included in the full-context tracking analysis prompt. They are now injected only into the specific report sections that need them.
- **Decoded privacy cookies in analysis context** — Decoded consent signals (USP, GPP, Google Analytics, Facebook, OneTrust, Cookiebot, etc.) are now passed through the pipeline and included in the tracking analysis context.
- **Consent delta in context** — Post-consent changes (new cookies, scripts, and requests that appeared after dismissing the consent dialog) are now computed and included for the privacy-risk and consent-analysis report sections.
- **TC/AC string data in consent analysis** — Decoded TC string details (purpose consents, vendor counts, CMP identity, legitimate interest signals, resolved vendor names, and validation findings) are now included in the consent-analysis section context.
- **Social media tracker classifications in context** — Pre-classified social media trackers from the deterministic pipeline are now passed directly to the social-media-implications report section.
- **Storage summary mode** — Sections that don't need full key-value storage data (tracking-technologies, data-collection) receive a compact grouped summary of storage keys classified by tracking pattern, instead of the full JSON.
- **TrackingAnalysisAgent timeout increased to 90 seconds** — Raised from 60 seconds to accommodate larger prompts on complex sites.
- **TrackingAnalysisAgent max_tokens reduced to 2048** — Halved from 4096 since the agent now produces only the overall risk narrative; detailed per-topic analysis is handled by the structured report agent.
- **SummaryFindingsAgent max_tokens increased to 1024** — Doubled from 500 to accommodate richer findings with consent delta data.
- **Disconnect context grouped by company** — `build_disconnect_context()` now groups domains by company name (with truncation at 3 domains per company) instead of listing each domain–company pair individually.

### Refactored

- **All LLM system prompts condensed** — Consent detection (−69%), structured report (−51%), summary findings (−68%), and tracking analysis (−65%) prompts rewritten for clarity and reduced token usage. Common directives (plain-text formatting, page-load caveat, partner caveat, factual constraint) extracted into shared constants.
- **Tracking analysis prompt scope narrowed** — The tracking analysis system prompt was reduced from 9 required sections to 3 (Tracking Technologies, Privacy Risk Assessment, Consent Dialog Analysis), each limited to 3–5 sentences. Detailed per-topic analysis is now handled exclusively by the structured report agent.
- **ScriptAnalysisAgent fallback logic flattened** — The nested try/except fallback structure simplified to a linear flow with primary attempt followed by fallback attempt.

## 1.6.3

### Fixed

- **Device emulation user agent bug** — Fixed a critical issue where device emulation (mobile/tablet/desktop) did not apply the intended user agent string. All browser sessions now use the correct `user_agent` for the selected device, ensuring accurate content and consent dialog rendering for mobile and tablet analysis.
- **SSRF redirect bypass in script fetch proxy** — The `POST /api/fetch-script` endpoint now follows up to 3 redirects (previously rejected outright) with SSRF validation on the final resolved URL, preventing open-redirect chains to internal hosts while supporting legitimate CDN redirects.
- **Script fetch truncation detection** — Replaced the unreliable `total_bytes` check with a 1-extra-byte read, so the `truncated` flag is now accurate regardless of `Content-Length` or chunked encoding.
- **Server environment leaked to browser process** — The Chrome launch environment is now restricted to an explicit allowlist of safe variables (`HOME`, `PATH`, `DISPLAY`, etc.) instead of forwarding the entire server environment, preventing accidental exposure of API keys or secrets.
- **Blocking DNS resolution in async context** — `validate_analysis_url()` now uses non-blocking `loop.getaddrinfo()` instead of the synchronous `socket.getaddrinfo()`, avoiding event-loop stalls during SSRF validation.
- **Multicast address bypass in SSRF validation** — Both `validate_analysis_url()` and the fetch-script proxy now reject multicast IP addresses in addition to private, loopback, link-local, and reserved ranges.
- **Malformed JSON returns 500** — Added a global `JSONDecodeError` exception handler so all POST endpoints return a clean `400 Bad Request` instead of an unhandled 500 when the request body contains invalid JSON.
- **Hardcoded TLD list replaced with Public Suffix List** — `get_base_domain()` now uses `tldextract` (backed by the Mozilla Public Suffix List) instead of a 9-entry hardcoded `_TWO_PART_TLDS` set, correctly handling all multi-part TLDs (e.g. `.co.uk`, `.com.au`, `.co.jp`) and newly registered suffixes.
- **Duplicated retry layers in consent extraction agent** — `ConsentExtractionAgent.extract()` and `_text_only_fallback()` had manual retry loops and `asyncio.wait_for` wrappers that duplicated the middleware retry/timeout behaviour. Flattened to single-attempt calls that rely on `RetryChatMiddleware` and `per_call_timeout`.
- **Retry delay logging mismatch in middleware** — `_log_retry()` computed its own jitter independently of `_backoff()`, so the logged delay could differ from the actual sleep duration. Merged into a single `_backoff_and_log()` method that computes jitter once for both logging and sleeping.
- **`api_version` not applied to non-Responses Azure client** — The `AzureOpenAIChatClient` code path in `_create_azure_client()` used `cfg.api_version` directly instead of the local `api_version` variable, which may have been upgraded for Responses API compatibility. Both code paths now use the same local variable.
- **Case-sensitive TC String heuristic skip list** — `_HEURISTIC_SKIP_COOKIE_NAMES` contained mixed-case entries (e.g. `"IDE"`, `"MUID"`, `"NID"`) but was checked with `name.lower()`, so the mixed-case entries never matched. All entries normalised to lowercase and the redundant `name in ...` fallback removed.
- **Deprecated `asyncio.get_event_loop()` usage** — Two calls in `stream.py` replaced with `asyncio.get_running_loop()` to avoid the deprecation warning and ensure correctness when no current event loop is set.
- **Internal script fetch truncation undetected** — `_fetch_script_content()` in the script analysis pipeline silently discarded content beyond `_MAX_SCRIPT_BYTES` without logging. Added a 1-extra-byte probe so truncation is detected and logged at DEBUG level.
- **Non-script files appearing in Scripts panel** — The browser session now filters out URLs with non-script file extensions (`.json`, `.css`, `.html`, `.xml`, `.svg`, fonts, images) even when the browser tags them as `resource_type == "script"`, preventing false entries in the script analysis results.

### Changed

- **Script preview limit increased to 4096 KB** — The `POST /api/fetch-script` proxy cap raised from 512 KB to 4096 KB, allowing larger bundled scripts to be viewed in full in the script source dialog.
- **Script viewer dialog shows short URL** — The dialog link now displays `origin + pathname` (without query string or fragment) for readability, with the full URL available in the tooltip.
- **Truncation notice directs user to original script** — The truncation warning in the script viewer dialog now reads "Click the link above to view the full script" instead of the generic "The full file may be larger".
- **Dead code removed** — Removed the unused `llm_failures` counter and its `nonlocal` declaration from `_analyze_unknowns()`, the redundant `ConnectionResetError` entry from `_is_retryable()` (already covered by its parent `ConnectionError`), and an unused `import re` from `url.py`.
- **Multi-part SSE completion events** — The monolithic `complete` SSE event is split into three separate events (`completeTracking`, `completeScripts`, `complete`) so no single data line exceeds browser or proxy size limits. Sites like Bristol Post with 1900+ network requests, 167 cookies, and 83 storage items now deliver all data without truncation.
- **GZip compression for SSE stream** — Added `GZipMiddleware` to compress all HTTP responses ≥ 500 bytes. JSON payloads compress 85–90 %, so even the largest tracking events stay well under 100 KB on the wire. The browser decompresses transparently via `Content-Encoding: gzip`.
- **Debug log tab removed** — Removed the `?debug=true` client-side debug log tab, the `completeDebug` SSE event, the in-memory log buffer (`_log_buffer_var`) that accumulated a stripped copy of every log line, and the `_sanitize_log_buffer` filter. Server logs remain available in stderr and the log files under `.output/logs/`.
- **`orjson` for SSE serialization** — Replaced `json.dumps()` with `orjson` (C extension) in `format_sse_event()` for 3–10× faster JSON serialization of large SSE payloads.
- **`uvloop` and `httptools`** — Switched to `uvicorn[standard]` which auto-enables `uvloop` (2–4× faster async event loop) and `httptools` (C-based HTTP parser) with zero code changes.

### Refactored

- **Shared LLM context builder** — Extracted `build_analysis_context()` into a new `context_builder` module. Both `TrackingAnalysisAgent` and `StructuredReportAgent` now delegate prompt assembly to this single function, eliminating ~150 lines of duplicated summary-stats, consent, score, GDPR-reference, and tracking-database sections.
- **`ItemInfoResult` base model** — Cookie and storage info agent response models (`CookieInfoResult`, `StorageInfoResult`) now inherit from a shared `ItemInfoResult` base in `models/item_info.py`, removing duplicated field definitions and `model_config`.
- **`CamelCaseModel` base class** — All 18 Pydantic models in `models/report.py` now inherit from a single `CamelCaseModel` base that carries the shared `model_config`, replacing 19 identical `model_config = ConfigDict(...)` declarations.
- **Consent-string discovery cascade** — The identical 5-tier TC and AC string discovery cascades in `stream.py` are consolidated into a generic `_discover_consent_string()` function parameterised by a `_ConsentStringTiers` dataclass, reducing ~70 lines of copy-pasted tier logic to two one-line calls.
- **`_find_button_by_patterns()` helper** — The structurally identical `find_accept_button()` and `find_reject_button()` functions in `platform_detection.py` now delegate to a shared `_find_button_by_patterns()` helper, differing only in the pattern list and log label.
- **Shared `attach_vendor_metadata()` helper** — Cookie and storage lookup modules now call a generic `attach_vendor_metadata()` function in `models/item_info.py` instead of maintaining separate but identical vendor-enrichment loops.
- **Domain and ANSI text utilities** — Extracted `strip_ansi()` and `sanitize_domain()` into a new `utils/text.py` module, replacing six inline `re.sub()` calls and two duplicated domain-truncation blocks in `logger.py`.
- **Magic numbers promoted to named constants** — Hardcoded thresholds and truncation limits across `risk.py`, `cookie_decoders.py`, `tracking_summary.py`, `data_collection.py`, `script_cache.py`, `browser_phases.py`, and `tc_validation.py` replaced with descriptive module-level constants (e.g. `CRITICAL_THRESHOLD`, `_RAW_VALUE_PREVIEW_LIMIT`, `_BEACON_URL_LENGTH_THRESHOLD`).
- **Cached pattern and domain lookups** — `get_tracking_cookie_patterns()` and `get_tracking_storage_patterns()` in `loader.py` now use `@functools.cache` for zero-cost repeated calls; `get_domain_description()` pre-builds an O(1) domain index instead of scanning the partner databases linearly on every lookup.
- **Lazy global caches replaced with `@functools.cache`** — The manual `None`-sentinel / `global` cache patterns in `vendor_lookup.py` (3 indexes) and `tcf_lookup.py` (1 index) are replaced with `@functools.cache`-decorated builder functions, eliminating mutable module-level state.
- **`_run_phase_4_overlays` split into helpers** — The ~350-line Phase 4 method in `stream.py` is split into three focused functions: `_decode_consent_strings()` (TC/AC string discovery, decoding, vendor resolution, validation), `_decode_privacy_cookies()` (USP/GPP/GA/OneTrust/Cookiebot signal decoding), and `_handle_overlay_failure()` (overlay failure check with abort). The main method now delegates to these via simple for-loops over their returned event lists.
- **`loader.py` split into feature-specific modules** — The 861-line monolithic data loader is split into `_base.py` (shared JSON helpers), `tracker_loader.py` (scripts, cookies, storage, domains, CNAME, Disconnect), `partner_loader.py` (partner databases, category config), `consent_loader.py` (TCF, GVL, GDPR, ATP, consent platforms), `media_loader.py` (media group profiles, LLM context), and `domain_info.py` (cross-category domain descriptions, storage key hints). `loader.py` is now a thin re-export facade — all existing `from src.data import loader` call-sites work unchanged.
- **`ConsentPlatformProfile` moved to shared types** — Moved the class from `platform_detection.py` to `models/consent.py` to break the circular import between `loader.py` and `platform_detection.py`. The original module re-exports the class for backward compatibility.
- **`__BREAK__` sentinel replaced with typed `BreakSignal`** — The magic string sentinel in `overlay_pipeline.py` is replaced with a frozen `@dataclass` `BreakSignal`, and the async generator return type updated to `str | BreakSignal`. Consumer code uses `isinstance()` for type-safe narrowing.
- **Table-driven scoring thresholds** — 20 multi-tier if/elif threshold chains across 7 scoring modules (`consent.py`, `cookies.py`, `data_collection.py`, `third_party.py`, `sensitive_data.py`, `fingerprinting.py`) are replaced with declarative tier-table constants and a shared `score_by_tiers()` helper in `scoring/_tiers.py`. Tiers are `(threshold, points, issue_template)` tuples checked in descending order, reducing ~200 lines of repetitive branching to concise table lookups.
- **`CookieLike` and `StorageItemLike` protocols** — Two `@runtime_checkable` protocols in `models/tracking_data.py` replace 28 `Sequence[object]` parameter types across `cookie_decoders.py` and `tc_string.py` with precise structural contracts (`CookieLike | Mapping[str, str]` for cookies, `StorageItemLike | Mapping[str, str]` for storage items).

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
