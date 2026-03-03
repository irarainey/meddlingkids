# Changelog

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
