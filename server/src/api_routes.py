"""API route handlers for the Meddling Kids server.

All ``/api/*`` endpoints live here, keeping ``main.py`` focused on
app creation, middleware wiring, and static-file serving.
"""

from __future__ import annotations

import asyncio
import urllib.parse

import aiohttp
import aiohttp.abc
import fastapi
import pydantic
from starlette import responses

from src import agents
from src.analysis import cookie_lookup, storage_lookup, tc_string, tcf_lookup
from src.data import loader
from src.pipeline import stream
from src.utils import cache, logger
from src.utils import url as url_mod

log = logger.create_logger("Routes")

router = fastapi.APIRouter()


# ── Request models ─────────────────────────────────────────────────────--


class DomainInfoRequest(pydantic.BaseModel):
    domains: list[str] = pydantic.Field(..., min_length=1)


class StorageKeyInfoRequest(pydantic.BaseModel):
    keys: list[str] = pydantic.Field(..., min_length=1)


class CookieInfoRequest(pydantic.BaseModel):
    name: str = pydantic.Field(..., min_length=1)
    domain: str = ""
    value: str = ""


class StorageInfoRequest(pydantic.BaseModel):
    key: str = pydantic.Field(..., min_length=1)
    storage_type: str = pydantic.Field("localStorage", alias="storageType")
    value: str = ""

    model_config = pydantic.ConfigDict(populate_by_name=True)


class TcfPurposesRequest(pydantic.BaseModel):
    purposes: list[str] = pydantic.Field(default_factory=list)


class TcStringDecodeRequest(pydantic.BaseModel):
    tc_string: str = pydantic.Field("", alias="tcString")

    model_config = pydantic.ConfigDict(populate_by_name=True)


class FetchScriptRequest(pydantic.BaseModel):
    url: str = pydantic.Field(..., min_length=1)


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/api/clear-cache")
async def clear_cache_endpoint() -> dict[str, object]:
    """Delete all cached data (domain, overlay, scripts)."""
    removed = cache.clear_all()
    log.success("Cache cleared via API", {"filesRemoved": removed})
    return {"success": True, "filesRemoved": removed}


@router.post("/api/domain-info")
async def domain_info_endpoint(
    body: DomainInfoRequest,
) -> dict[str, dict[str, str | None]]:
    """Look up tracker/company info for one or more domains.

    Fast deterministic lookup — no LLM calls.  Checks the
    Disconnect services database, partner databases, and
    tracker-domains list to build a one-line description.

    DNS-based geolocation runs in a thread pool to avoid
    blocking the async event loop.

    Accepts ``{"domains": ["example.com", ...]}`` and returns
    a map of domain → ``{company, description}``.
    """
    cleaned = [d.strip() for d in body.domains if d.strip()]

    def _lookup() -> dict[str, dict[str, str | None]]:
        return {d: loader.get_domain_description(d) for d in cleaned}

    return await asyncio.to_thread(_lookup)


@router.post("/api/storage-key-info")
async def storage_key_info_endpoint(
    body: StorageKeyInfoRequest,
) -> dict[str, dict[str, str | None]]:
    """Look up known descriptions for storage key names.

    Fast deterministic lookup — no LLM calls.  Matches keys
    against the tracking-storage pattern database.

    Accepts ``{"keys": ["_ga", ...]}`` and returns a map of
    key → ``{setBy, description}``.
    """
    result: dict[str, dict[str, str | None]] = {}
    for key in body.keys:
        k = key.strip()
        if k:
            result[k] = loader.get_storage_key_hint(k)
    return result


@router.post("/api/cookie-info")
async def cookie_info_endpoint(
    body: CookieInfoRequest,
) -> dict[str, object]:
    """Look up information about a specific cookie.

    Checks known databases first and falls back to LLM for
    unrecognised cookies.
    """
    agent = agents.get_cookie_info_agent()
    result = await cookie_lookup.get_cookie_info(body.name, body.domain, body.value, agent)

    return result.model_dump(by_alias=True)


@router.post("/api/storage-info")
async def storage_info_endpoint(
    body: StorageInfoRequest,
) -> dict[str, object]:
    """Look up information about a specific storage key.

    Checks known databases first and falls back to LLM for
    unrecognised keys.
    """
    agent = agents.get_storage_info_agent()
    result = await storage_lookup.get_storage_info(body.key, body.storage_type, body.value, agent)

    return result.model_dump(by_alias=True)


@router.post("/api/tcf-purposes")
async def tcf_purposes_endpoint(
    body: TcfPurposesRequest,
) -> dict[str, object]:
    """Map consent purpose strings to IAB TCF v2.2 purposes.

    Accepts a list of purpose strings and returns matched TCF
    purposes with full metadata (description, risk level, lawful
    bases, notes) and any unmatched strings.  Matching is purely
    deterministic — no LLM calls.
    """
    if not body.purposes:
        return {"matched": [], "unmatched": []}

    result = tcf_lookup.lookup_purposes(body.purposes)
    return result.model_dump(by_alias=True)


@router.post("/api/tc-string-decode")
async def tc_string_decode_endpoint(
    body: TcStringDecodeRequest,
) -> dict[str, object]:
    """Decode an IAB TCF v2 TC String.

    Accepts a raw TC String (Base64url-encoded, as stored in
    the ``euconsent-v2`` cookie) and returns decoded metadata,
    purpose consents, vendor consents, and legitimate interest
    signals.  Purely deterministic — no LLM calls.
    """
    if not body.tc_string:
        raise fastapi.HTTPException(status_code=400, detail="No tcString provided")

    decoded = tc_string.decode_tc_string(body.tc_string)
    if decoded is None:
        raise fastapi.HTTPException(status_code=400, detail="Failed to decode TC string")

    return decoded.model_dump(by_alias=True)


# Maximum bytes to fetch for script preview (4096 KB).
_MAX_PREVIEW_BYTES = 4096 * 1024

# Hosts that are allowed for script fetching to avoid full SSRF.
# Adjust this list as appropriate for the deployment environment.
_ALLOWED_SCRIPT_HOSTS: set[str] = set()


@router.post("/api/fetch-script")
async def fetch_script_endpoint(
    body: FetchScriptRequest,
) -> dict[str, object]:
    """Fetch the source content of a remote JavaScript file.

    Acts as a same-origin proxy so the client can display
    syntax-highlighted script source without CORS restrictions.
    Only HTTP(S) URLs are accepted and the response is capped
    at 4096 KB to prevent abuse.

    DNS is resolved once and pinned to the validated addresses
    to prevent DNS rebinding (TOCTOU) attacks.
    """
    url = body.url.strip()

    # Basic surface validation to constrain the URL and reduce SSRF risk
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        raise fastapi.HTTPException(status_code=400, detail="Invalid URL format") from exc

    if parsed.scheme not in ("http", "https"):
        raise fastapi.HTTPException(status_code=400, detail="Only http and https URLs are allowed")

    # If an allowlist of hosts is configured, enforce it here.
    if _ALLOWED_SCRIPT_HOSTS and (parsed.hostname not in _ALLOWED_SCRIPT_HOSTS):
        raise fastapi.HTTPException(status_code=400, detail="Host is not allowed for script fetching")

    try:
        resolved = await url_mod.resolve_and_validate(url)
    except url_mod.UnsafeURLError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc

    # Pin aiohttp to the pre-validated IP addresses so a DNS
    # rebinding attack cannot redirect the connection after
    # validation.
    class _PinnedResolver(aiohttp.abc.AbstractResolver):
        async def resolve(
            self,
            _host: str,
            _port: int = 0,
            _family: int = 0,
        ) -> list[aiohttp.abc.ResolveResult]:
            return resolved  # type: ignore[return-value]

        async def close(self) -> None:
            pass

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        connector = aiohttp.TCPConnector(resolver=_PinnedResolver())
        async with (
            aiohttp.ClientSession(timeout=timeout, connector=connector) as session,
            session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; MeddlingKids/1.0)"},
                max_redirects=3,
            ) as resp,
        ):
            # Validate the redirect URL's scheme and hostname without
            # re-resolving DNS — the pinned resolver already guarantees
            # traffic goes to the validated IPs.  A fresh DNS lookup
            # here would create a TOCTOU window.
            final_url = str(resp.url) if resp.url is not None else url
            if final_url != url:
                try:
                    url_mod.validate_url_surface(final_url)
                except url_mod.UnsafeURLError:
                    return {"error": "Redirect target points to a disallowed host", "content": None}
            if resp.status >= 400:
                return {"error": f"HTTP {resp.status}", "content": None}
            raw = await resp.content.read(_MAX_PREVIEW_BYTES)
            extra = await resp.content.read(1)
            content = raw.decode("utf-8", errors="replace")
            truncated = len(extra) > 0
            return {"content": content, "truncated": truncated}
    except TimeoutError:
        return {"error": "Request timed out", "content": None}
    except Exception as exc:
        log.debug("Script fetch proxy error", {"url": url, "error": str(exc)})
        return {"error": "Unexpected error fetching script", "content": None}


@router.get("/api/open-browser-stream")
async def analyze_endpoint(
    url: str = fastapi.Query(..., description="The URL to analyze"),
    device: str = fastapi.Query("ipad", description="Device type to emulate"),
    clear_cache: bool = fastapi.Query(False, alias="clear-cache", description="Clear all caches before analysis"),
) -> responses.StreamingResponse:
    """Analyze tracking on a URL with streaming progress via SSE."""
    log.info("Incoming analysis request", {"url": url, "device": device, "clearCache": clear_cache})

    async def event_generator():
        async for event_str in stream.analyze_url_stream(url, device, clear_cache=clear_cache):
            yield event_str

    return responses.StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
