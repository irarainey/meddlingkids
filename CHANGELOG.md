
# Changelog

## 1.8.3

### Changed

- **MAF structured output simplified** — Agent `response_format` now passes Pydantic model classes directly to the MAF + OpenAI SDK instead of manually building strict-mode JSON schemas. The `_prepare_strict_schema` workaround and `copy.deepcopy` patching have been removed. Response parsing uses `response.value` (native MAF structured output) with a `response.text` fallback.
- **MAF built-in telemetry enabled** — `observability.enable_instrumentation()` is now called during setup, activating MAF's `AgentTelemetryLayer` and `ChatTelemetryLayer` for automatic OpenTelemetry spans and metrics on every agent and chat-client call. The custom `TimingChatMiddleware` no longer writes to `context.metadata["timing"]` (superseded by the built-in layers) and focuses on human-readable log output.
- **MAF Agent reuse** — The framework `Agent` is now built once in `initialise()` and stored on the instance, rather than being constructed and torn down on every LLM call. Per-call overrides (instructions, response format, max tokens) are passed via `agent.run(options=...)`. Fallback activation rebuilds the agent with the new client.
- **MAF ContextProvider for GDPR reference** — A new `GdprReferenceProvider` injects cached GDPR/TCF regulatory reference text as supplementary system instructions via the MAF `before_run` hook, gated by a session-state flag. Added to all agents via `_create_agent()`.
- **MAF WorkflowBuilder for report generation** — The `StructuredReportAgent`'s 10-section `asyncio.gather()` has been replaced with a MAF `Workflow` using `WorkflowBuilder.add_fan_out_edges()` / `add_fan_in_edges()`. Ten `SectionExecutor` instances run concurrently with typed edges, convergence detection, and a `MergeExecutor` that collects results. Conditional section skipping (consent sections without consent data) is handled via executor-level `skip_condition` callbacks. Each executor fires its `on_section_done` progress callback immediately on completion, streaming real-time updates to the client instead of batching them after the workflow finishes.
- **MAF `@executor` pipeline wrappers** — Script analysis and tracking analysis pipeline steps are now wrapped as MAF `FunctionExecutor` instances via the `@executor` decorator, providing typed input/output contracts for workflow composition.
- **Default Azure API version updated to `2025-04-01-preview`** — The previous default (`2024-12-01-preview`) is no longer supported by Azure OpenAI. The `.env.example` and config default have been updated accordingly.
- **Responses API no longer passes explicit `api_version`** — The MAF `OpenAIChatClient` (Responses API) internally uses the versionless `/openai/v1/` endpoint. Passing an explicit `api_version` caused the underlying `AsyncAzureOpenAI` client to append a `?api-version=` query parameter that the v1 endpoint rejects. The `api_version` parameter and the `_MIN_RESPONSES_API_VERSION` auto-upgrade logic have been removed for Responses API clients.
- **Upfront LLM connectivity check removed** — The `verify_connectivity()` pre-flight check (which made a throwaway LLM call before every analysis) has been removed. Connection errors are now caught at the point of real LLM calls by the retry middleware, which wraps them in `LLMConnectionError` with diagnostic messages (auth failures, DNS errors, timeouts, etc.).
- **Explicit OIDC ID token validation** — The OAuth callback now passes explicit `claims_options` to authlib's `authorize_access_token()`, making the token validation requirements visible in code: `iss` must match the configured issuer, `sub` must be present, `aud` must match the client ID, and `exp` must not be expired. Clock-skew leeway tightened from 120s to 30s.
- **Summary agent runs concurrently with report** — The `SummaryFindingsAgent` is now launched as a 4th concurrent task chained after tracking analysis, rather than running sequentially after all concurrent tasks complete. This overlaps the summary LLM call with any still-in-flight report sections, saving ~5–10s on typical runs.
- **Async geo resolution in analysis pipeline** — Domain geolocation (DNS → IP → country lookup) now uses the async `resolve_domains_countries()` function with `run_in_executor`, instead of the synchronous `_resolve_geo_countries()` which blocked the event loop for 5–10s while resolving every domain. Geo resolution runs concurrently with scoring and domain-knowledge lookup.
- **Analysis-phase rotating status messages** — The client now cycles through contextual progress messages (e.g. "Examining cookie behavior...", "Cross-referencing tracker databases...") every 3.5s during the AI analysis phase (76–95%) when no real server progress event arrives, keeping the UI responsive during long LLM calls.

### Added

- **Auth guard security tests** — New `tests/auth/test_auth_guard.py` with 12 tests covering: unauthenticated access blocked (401 for API, redirect for pages), pass-through for `/auth/*` and `/assets/*`, valid session access, tampered cookies (wrong secret, corrupted payload, modified data, empty session), and expired session rejection.

### Fixed

- **LLM calls use `max_completion_tokens`** — The OpenAI SDK parameter was updated from the deprecated `max_tokens` to `max_completion_tokens`, which newer models require.
- **Script analysis fallback on API version rejection** — `_is_model_error` now recognises `"API version not supported"` responses, allowing the `ScriptAnalysisAgent` to correctly fall back to the default ChatCompletion deployment instead of silently failing.
- **Logo overlap on mobile with auth enabled** — Added conditional `logo--auth` class that applies `margin-top: 1rem` to the header logo only when OAuth is enabled, preventing the sign-out link from overlapping the logo on small screens.

## 1.8.2

### Fixed

- **OAuth logout redirect method** — Fixed logout failing on Auth0 (and potentially other providers) with a "Not Found" error. The `POST /auth/logout` handler was returning a 307 redirect, which preserves the HTTP method — causing the browser to POST to the provider's logout endpoint instead of GET. All logout redirects now use 303 (See Other) to correctly convert to GET.
- **Auth0 logout endpoint modernised** — The Auth0-specific fallback now uses the OIDC-compliant `/oidc/logout` endpoint with `post_logout_redirect_uri` instead of the legacy `/v2/logout` with `returnTo`. This aligns the fallback with the standard `end_session_endpoint` code path.

## 1.8.1

### Fixed

- **OAuth redirect URI scheme on HTTPS** — Fixed the OAuth `redirect_uri` (and post-logout redirect) using `http://` instead of `https://` when the server runs behind a TLS-terminating reverse proxy. The `_get_trusted_base_url` helper now honours the `X-Forwarded-Proto` header to reconstruct the correct scheme.

## 1.8.0

### Added

- **Optional OAuth2 authentication** — The application now supports OAuth2 Authorization Code + PKCE authentication via any OIDC-compliant provider (e.g. Auth0, Entra ID, Google, Keycloak). Authentication is entirely optional and gated by four environment variables (`OAUTH_ISSUER`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `SESSION_SECRET`). When absent, the app runs without authentication as before.
- **Server-side BFF (Backend for Frontend) pattern** — Tokens (access, refresh, ID) stay server-side in signed session cookies. The SPA never handles tokens directly, which also avoids issues with SSE `EventSource` not supporting custom `Authorization` headers.
- **Auth module (`server/src/auth/`)** — New module with config, routes, and middleware:
  - `GET /auth/login` — generates PKCE code challenge, redirects to provider
  - `GET /auth/callback` — exchanges authorization code for tokens, creates session
  - `GET /auth/me` — returns user info or `{"enabled": false}` when auth disabled
  - `POST /auth/logout` — clears session, redirects to provider logout (OIDC `end_session_endpoint` or `/oidc/logout` fallback)
  - Auth guard middleware blocks unauthenticated requests: 401 for `/api/*`, redirect to login for page requests, pass-through for `/auth/*` and `/assets/*`
- **Client auth composable (`useAuth.ts`)** — Checks `/auth/me` on app mount. When authenticated, shows an unobtrusive logout button in the header. When unauthenticated, redirects to the server-side login flow.
- **Host header validation** — OAuth redirect URIs are validated against `CORS_ALLOWED_ORIGINS` to prevent Host-header injection attacks.
- **New dependencies** — `authlib` (OIDC client + PKCE), `httpx` (promoted from dev to runtime for authlib's async HTTP), `itsdangerous` (session cookie signing).

### Changed

- **CORS `allow_credentials`** — Automatically set to `true` when OAuth is enabled so session cookies work correctly with cross-origin requests.
- **Vite dev proxy** — Added `/auth` proxy alongside the existing `/api` proxy for seamless development with authentication enabled.
- **Test fixture** — The test client now injects a signed session cookie when OAuth env vars are present, ensuring existing API tests pass through the auth middleware.

## 1.7.8

### Changed

- **`agent-framework-core` upgraded to 1.0.0 GA** — Migrated from `1.0.0rc5` (pre-release) to the `1.0.0` stable release. This is a breaking change in the upstream package that required updating all agent code:
  - `AzureOpenAIResponsesClient` → `OpenAIChatClient` (from `agent_framework.openai`, with `azure_endpoint=` parameter)
  - `AzureOpenAIChatClient` → `OpenAIChatCompletionClient` (from `agent_framework.openai`, with `azure_endpoint=` parameter)
  - `OpenAIChatClient` (standard OpenAI) → `OpenAIChatCompletionClient`
  - `deployment_name` parameter → `model`
  - `model_id` parameter → `model`
  - `Message(role=..., text=...)` → `Message(role=..., contents=[...])`
  - `response.model_id` → `response.model`
  - Removed `agent_framework.azure` import (Azure OpenAI clients now live in `agent_framework.openai`)
  - The GA release trimmed transitive dependencies (`openai`, `httpx`, `mcp`, `azure-ai-projects`, etc.), resulting in a leaner install
- **`agent-framework-openai` added as explicit dependency** — The GA release split the OpenAI/Azure OpenAI client classes (`OpenAIChatClient`, `OpenAIChatCompletionClient`) into a separate `agent-framework-openai` package. Previously bundled inside `agent-framework-core` during the RC phase.
- **Dependency version bumps** — Updated minimum version floors and lock file for all dependencies with available updates:
  - `fastapi` 0.129.0 → 0.135.3
  - `uvicorn` 0.41.0 → 0.42.0
  - `azure-monitor-opentelemetry-exporter` 1.0.0b48 → 1.0.0b50
  - `python-dotenv` 1.2.1 → 1.2.2
  - `aiohttp` 3.13.3 → 3.13.5
  - `pillow` 12.1.1 → 12.2.0
  - `orjson` 3.10.18 → 3.11.8
  - `poethepoet` (dev) 0.41.0 → 0.42.1
  - `mypy` (dev) 1.19.1 → 1.20.0
  - `ruff` (dev) 0.15.2 → 0.15.9
- **`httpx` added as explicit dev dependency** — Previously a transitive dependency via `openai` (which the GA `agent-framework-core` no longer pulls). Required by `fastapi.testclient` / `starlette.testclient` for integration tests. Pinned to `>=0.28.0,<1.0` to avoid the incompatible 1.0 pre-release.

## 1.7.7

### Added

- **Azure Managed Identity authentication** — Azure OpenAI now supports authenticating via `DefaultAzureCredential` as an alternative to API keys. Set `AZURE_USE_MANAGED_IDENTITY=true` to enable. Works with system-assigned and user-assigned managed identities (via `AZURE_CLIENT_ID`), Azure CLI, and other credential sources supported by the Azure Identity SDK. API key authentication remains the default and continues to work unchanged.
- **`azure-identity` added as explicit dependency** — Previously only a transitive dependency; now declared directly in `pyproject.toml`.

### Fixed

- **Country flags not appearing on Network, Scripts, and Graph tabs** — The `/api/domain-info` endpoint performed synchronous DNS lookups on the async event loop, blocking all other requests for 10–20 seconds when resolving hundreds of domains. Moved the blocking work to a thread pool via `asyncio.to_thread()`.
- **Progressive domain info loading** — The Network and Tracker Graph tabs now fetch domain info in batches of 30 instead of sending all domains in a single request. Flags and company info appear progressively within ~1 second instead of waiting for the entire list to resolve.
- **Partner database cache mutation** — `get_domain_description()` was mutating cached dictionaries from the partner domain index when adding the `country` field, which could cause inconsistent results under concurrent access. Fixed by copying the dict before modification.

## 1.7.6

### Changed

- **GeoIP database bundled in repository** — The DB-IP Lite country database (~3.8 MB compressed) is now committed to the repo as a `.csv.gz` file and loaded directly at runtime, eliminating the fragile download-on-startup approach. The loader reads the compressed file in-memory (`gzip.open`) without decompressing to disk. Use `scripts/update-geo-db.sh` to refresh to a newer month's database.
- **GeoIP loader simplified** — Removed all download, retry, and symlink logic from `geo_loader.py`. The loader now finds the newest `dbip-country-lite-*.csv.gz` in the `geo/` directory and parses it on first use. Failed loads (missing file) are not cached so the database is re-checked on each call.
- **`agent-framework-core` updated to 1.0.0rc5** — Bumped from rc3 to rc5 (also pulls `azure-ai-projects` 2.0.0b4 → 2.0.1 GA as a transitive dependency).

## 1.7.5

### Added

- **IP geolocation for third-party domains** — Domains on the Network, Scripts, and Tracker Graph tabs now display a country flag icon showing where the domain's IP address is registered. Hovering over the flag shows the full country name. Uses the [DB-IP Lite](https://db-ip.com/db/lite.php) database (CC BY 4.0, ~600k IP ranges) with O(log n) binary search lookups.
- **Country flags on tracker graph** — The interactive network graph now shows country flag icons on hover tooltips, the selected-node detail panel (with full country name), and connection list items.
- **Geo disclaimer on Network and Scripts tabs** — A subtle note below the Analysis heading explains that flags show where an IP address is registered, not necessarily where the server is physically located, since CDN-fronted services may show a different country.
- **`/api/domain-info` enriched with `country` field** — The domain info API now returns an ISO 3166-1 alpha-2 country code alongside company, description, and URL. Geolocation uses DNS resolution followed by IP-to-country lookup.
- **`scripts/update-geo-db.sh`** — Shell script to download and update the bundled DB-IP database to a newer month's release.
- **Debug logging for geo lookups** — Each domain→IP→country resolution is logged at debug level for troubleshooting.

### Changed

- **`agent-framework-core` updated to 1.0.0rc3** — Bumped from rc2 to rc3 (also pulls `azure-ai-projects` b3→b4 as a transitive dependency).



## 1.7.4

### Added

- **URL input validation** — The URL text field now validates input as the user types, highlighting the border in red and displaying a hint message when the value is not a valid URL. The Unmask button is disabled until a valid URL is entered. A server-side guard in the composable also rejects invalid URLs before starting analysis.
- **URL input trim on blur** — Leading and trailing whitespace is automatically stripped from the URL input when the field loses focus.
- **"What You Agreed To" plain-language consent digest** — A new LLM-generated summary explains in 2–3 simple sentences what the user agreed to by clicking Accept on a site's consent dialog. Written at a reading age of ~12, it highlights how many companies can track the user, what data is collected, and whether data brokers are involved. Displayed as a visually distinct callout in the Consent tab, above the existing technical AI summary. Inspired by Pew Research finding that 56% of users click "agree" without reading consent dialogs.
- **"Your Rights" privacy rights note** — When TCF infrastructure or a consent management platform is detected, a deterministic (no LLM) callout in the Consent tab explains the user's rights under GDPR, including the right to withdraw consent, practical instructions for finding cookie settings, and key data subject rights (access, erasure, objection). Inspired by Cisco's 2024 Consumer Privacy Survey finding that consumers aware of privacy laws are nearly twice as likely to feel they can protect their data.

### Changed

- **Mobile responsive layout fixes** — Added `max-width: 100%` and `box-sizing: border-box` to the URL input and device select to prevent horizontal overflow on narrow screens. Prevented horizontal page scroll with `overflow-x: hidden` on the html element.
- **Summary tab mobile overflow fixes** — Added `flex-wrap` to score headings, section headings, risk factor rows, and data card headers. Added `overflow-wrap: anywhere` to factor text and tracker domain lists to prevent long text from breaking the page width.
- **Score dialog mobile layout** — Added `box-sizing: border-box` to the dialog overlay and content. On screens ≤480px, reduced overlay padding, scaled down exclamation text, and tightened content padding so the dialog fits within the viewport.
- **Progress bar visible on scan start** — The page now scrolls to show the progress banner with padding below when the scan begins, ensuring it is visible without sitting flush against the bottom of the viewport.
- **Progress bar prioritised over screenshots on scroll** — When the first screenshot arrives, the page scrolls to the progress banner rather than the gallery, keeping the progress bar visible on mobile.
- **View Full Report scroll offset** — Clicking "View Full Report" on the score dialog now scrolls to 32px above the report tabs for visual breathing room.

### Removed

- **Dead code cleanup** — Removed unused `formatMarkdown()` utility, dead `TrackerCategorySection.vue` component, orphaned `ScriptViewerDialog` barrel export, unused `.error` and `.app-footer .version` CSS rules, a no-op `highlight` class binding, and the uncalled `find_reject_button()` function from the server.

## 1.7.3

### Changed

- **Tracker domain database expanded from 4,644 to 19,099 domains** — Integrated 14,455 new domains from Peter Lowe's Ad Servers List (curated since 2003) and EasyPrivacy (Firebog-curated subset of EasyList/EasyPrivacy). All new entries classified as `block`. Source attribution added to `_sources` metadata.
- **8 new tracking script patterns** — Added detection patterns for Pendo (product analytics), Piano (publisher analytics/paywall), Exponea/Bloomreach (CDP), WalkMe (digital adoption), Baremetrics (SaaS analytics), Insider (personalisation), and Branch.io (deep linking/attribution). Consolidated duplicate Adjust patterns into a single comprehensive entry.
- **48 new tracking cookie definitions** — Added cookie patterns for Pendo, VWO (Visual Website Optimizer), Inspectlet, Tealium, Branch.io, Quantcast, LogRocket, Akamai Bot Manager, Leadfeeder, Evidon/Crownpeak, Intercom, Mixpanel, Adjust, Piano, WalkMe, and Exponea/Bloomreach with descriptions, set-by information, and purpose categories.
- **20 new tracking storage key definitions** — Added localStorage patterns for Pendo, VWO, Inspectlet, ContentSquare, Branch.io, Qualtrics, WalkMe, Tealium, Exponea/Bloomreach, Adjust, and Quantcast.
- **17 new vendor profiles in cookie database** — Added vendor metadata (category, URL, privacy concerns) for Pendo, VWO, Inspectlet, Tealium, Branch.io, Quantcast, LogRocket, Akamai, Leadfeeder, Evidon/Crownpeak, Intercom, Adjust, Piano, WalkMe, Exponea/Bloomreach, Baremetrics, and Insider.
- **11 new vendor profiles in storage database** — Added vendor metadata for Pendo, VWO, Inspectlet, ContentSquare, Branch.io, Qualtrics, WalkMe, Tealium, Exponea/Bloomreach, Adjust, and Quantcast.
- **Screenshot gallery auto-scrolls to latest screenshot** — On small screens (e.g. phone in portrait mode), the screenshot thumbnail row now smoothly scrolls to the rightmost thumbnail when a new screenshot is added, ensuring the latest capture is always visible.
- **Data loader switched from stdlib `json` to `orjson`** — The shared `_load_json()` helper now uses `orjson` (C extension, already a project dependency) for parsing all data files, reducing JSON deserialization time by ~1.4x across 8 MB of reference data.
- **URL input widened by 25%** — The URL entry field increased from 400px to 500px for easier editing of long URLs.
- **Tagline rendered on a single line** — Removed the `max-width` constraint on the intro paragraph so it no longer wraps onto two lines on wide screens.
- **Combined regex fast-paths in cookie lookup** — Cookie consent, tracking, and fingerprint pattern checks in `cookie_lookup.py` now use pre-compiled combined alternation regexes instead of iterating individual patterns sequentially, reducing per-cookie regex tests by ~70%.
- **Script classification short-circuit** — `build_pre_consent_stats()` now tests the fast combined URL tracker regex before iterating 499 individual script patterns, short-circuiting immediately for known trackers.
- **Partner database URL normalization cached** — The 5-step string manipulation chain for partner entry URLs is now cached via `@functools.lru_cache`, running at most once per unique URL instead of once per domain per entry per request.
- **Domain keyword classifier fast-fail** — Added a combined alternation regex for the 5 domain keyword classifiers. Domains that match no keyword (the majority) now fail in one regex test instead of five.
- **Script grouping fast-fail** — Added a combined alternation regex for the 8 groupable script patterns. Non-matching URLs now exit in one test instead of eight.
- **Network graph entrance animations faster** — Node stagger delay reduced to 3ms per node (150ms duration), edges fade in after 80ms (150ms), and labels after 120ms (150ms) for a snappier initial render.
- **Network graph overlays made transparent** — The statistics overlay, hover tooltip, and selected-node detail panel all use 90% transparent backgrounds with backdrop blur, reducing visual obstruction of the graph.
- **Selected-node detail panel shown as overlay** — The detail panel is now positioned as an overlay inside the graph container instead of below it, so selecting a node no longer resizes the graph.
- **Click background to deselect node** — Clicking on the graph background now clears the selected node and restores the default view.
- **Filter changes dismiss selected node** — Changing the view mode or category filter now automatically deselects any selected node and resets the highlight.
- **Network graph performance optimizations** — Third-party filter uses a pre-built Set for O(1) lookups instead of O(n) `find()` per edge. Hover handlers operate directly on the hovered element via `select(this)` instead of re-querying all circles. Force simulation parameters adapt to graph size (weaker charge, shorter links, faster decay for 100+ nodes). Minimap rendering throttled to every 3rd tick for large graphs, with node drawing batched by colour to reduce canvas state changes. Highlight restore computes the stroke scale once outside the per-edge callback.
- **Pan to selected node when off-screen** — Clicking a node that is outside the visible viewport now smoothly pans the graph to centre it on screen.
- **Domain links use company URLs from local database** — Domain names in the Network tab are now clickable links to the company's website (from partner databases) instead of the tracking endpoint URL. Disconnect entries no longer fabricate URLs from the tracker domain.
- **Post data sanitization** — Network request payloads now strip non-printable control characters that can appear from binary payloads or chunked transfer encoding artifacts captured by Playwright.
- **Collapsible URL parameters and POST payloads in Network tab** — Long GET URLs now display only the path, with a toggle button to expand query parameters as a key-value list. POST payloads (form-encoded and JSON) use the same collapsible display. Only one section can be expanded at a time.

### Fixed

- **Pre-consent edges not fading on node selection** — Dotted pre-consent lines now fade correctly when a node is selected, using `stroke-opacity` and hiding arrow markers on dimmed edges.

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
