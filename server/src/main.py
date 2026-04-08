"""
Server entry point — FastAPI app setup and route configuration.
Sets up the FastAPI server with CORS, static file serving, and all API routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
from collections.abc import AsyncGenerator

import aiohttp
import dotenv
import fastapi
import pydantic
from fastapi import staticfiles
from fastapi.middleware import cors, gzip
from starlette import responses
from starlette.middleware import sessions

from src.agents import get_cookie_info_agent, get_storage_info_agent, observability_setup
from src.analysis import cookie_lookup, storage_lookup, tc_string, tcf_lookup
from src.auth import config, middleware, routes
from src.browser import manager
from src.data import loader
from src.pipeline import stream
from src.utils import cache, logger
from src.utils.url import UnsafeURLError, resolve_and_validate, validate_analysis_url


def _bootstrap() -> None:
    """Load environment and configure observability (called once at startup)."""
    dotenv.load_dotenv()
    observability_setup.setup()


_bootstrap()

log = logger.create_logger("Server")

SHOW_UI = os.environ.get("SHOW_UI", "false").lower() == "true"


@contextlib.asynccontextmanager
async def lifespan(_app: fastapi.FastAPI) -> AsyncGenerator[None]:
    """Start shared browser on startup, stop on shutdown."""
    log.section("Meddling Kids Server Started")
    log.info(
        "Configuration",
        {
            "showUi": SHOW_UI,
            "corsOrigins": _ALLOWED_ORIGINS,
            "authEnabled": config.is_auth_enabled(),
        },
    )

    # Start the shared Playwright + Chrome instance once.
    # All analysis requests will reuse this browser and
    # create lightweight, isolated contexts per scan.
    pw_manager = manager.PlaywrightManager.get_instance()
    await pw_manager.start()

    yield

    # Graceful shutdown: close the shared browser + Playwright.
    await pw_manager.stop()


app = fastapi.FastAPI(title="Meddling Kids Python Server", lifespan=lifespan)


@app.exception_handler(json.JSONDecodeError)
async def _json_decode_error_handler(
    _request: fastapi.Request,
    _exc: json.JSONDecodeError,
) -> fastapi.responses.JSONResponse:
    """Return 400 for malformed JSON request bodies."""
    return fastapi.responses.JSONResponse(
        status_code=400,
        content={"detail": "Invalid JSON in request body"},
    )


# ============================================================================
# Middleware
# ============================================================================

_ALLOWED_ORIGINS = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:4173",
).split(",")

app.add_middleware(
    cors.CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=config.is_auth_enabled(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip-compress responses above 500 bytes.  SSE tracking events
# (JSON arrays of cookies/requests) compress ~85-90 %, keeping
# even extreme sites well under browser EventSource limits.
app.add_middleware(gzip.GZipMiddleware, minimum_size=500)


# ── Optional OAuth2 authentication ─────────────────────────────────────
# Enabled only when OAUTH_ISSUER, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET,
# and SESSION_SECRET are all set in the environment.
if config.is_auth_enabled():
    _auth_cfg = config.get_oauth_config()

    @app.middleware("http")
    async def _auth_guard_middleware(
        request: fastapi.Request,
        call_next,  # type: ignore[no-untyped-def]
    ) -> fastapi.Response:
        return await middleware.auth_guard(request, call_next)

    # SessionMiddleware must be added AFTER the auth guard so it is the
    # outermost layer (Starlette uses LIFO ordering).  This ensures the
    # session cookie is decoded before the guard reads request.session.

    app.add_middleware(
        sessions.SessionMiddleware,
        secret_key=_auth_cfg["session_secret"],
        session_cookie="mk_session",
        max_age=24 * 60 * 60,  # 24 hours
        same_site="lax",
        https_only=os.environ.get("SESSION_SECURE", "").lower() == "true",
    )

    log.info("OAuth2 authentication enabled", {"issuer": _auth_cfg["issuer"]})


# Auth routes are always registered so /auth/me can report "disabled"
# instead of being swallowed by the SPA catch-all.
app.include_router(routes.router)


@app.middleware("http")
async def disable_static_cache(
    request: fastapi.Request,
    call_next,
) -> fastapi.Response:
    """Prevent browsers from serving stale static assets from the Docker build."""
    response: fastapi.Response = await call_next(request)
    if request.url.path.startswith("/assets"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ============================================================================
# API Routes
# ============================================================================


# ── Request models ───────────────────────────────────────────────────────


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


@app.post("/api/clear-cache")
async def clear_cache_endpoint() -> dict[str, object]:
    """Delete all cached data (domain, overlay, scripts)."""
    removed = cache.clear_all()
    log.success("Cache cleared via API", {"filesRemoved": removed})
    return {"success": True, "filesRemoved": removed}


@app.post("/api/domain-info")
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


@app.post("/api/storage-key-info")
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


@app.post("/api/cookie-info")
async def cookie_info_endpoint(
    body: CookieInfoRequest,
) -> dict[str, object]:
    """Look up information about a specific cookie.

    Checks known databases first and falls back to LLM for
    unrecognised cookies.
    """
    agent = get_cookie_info_agent()
    result = await cookie_lookup.get_cookie_info(body.name, body.domain, body.value, agent)

    return result.model_dump(by_alias=True)


@app.post("/api/storage-info")
async def storage_info_endpoint(
    body: StorageInfoRequest,
) -> dict[str, object]:
    """Look up information about a specific storage key.

    Checks known databases first and falls back to LLM for
    unrecognised keys.
    """
    agent = get_storage_info_agent()
    result = await storage_lookup.get_storage_info(body.key, body.storage_type, body.value, agent)

    return result.model_dump(by_alias=True)


@app.post("/api/tcf-purposes")
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


@app.post("/api/tc-string-decode")
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


@app.post("/api/fetch-script")
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

    try:
        resolved = await resolve_and_validate(url)
    except UnsafeURLError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc

    # Pin aiohttp to the pre-validated IP addresses so a DNS
    # rebinding attack cannot redirect the connection after
    # validation.
    class _PinnedResolver(aiohttp.abc.AbstractResolver):
        async def resolve(
            self,
            host: str,
            port: int = 0,
            family: int = 0,
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
            # Validate the final URL after redirects to prevent
            # SSRF via an open-redirect chain.
            final_url = str(resp.url) if resp.url is not None else url
            if final_url != url:
                try:
                    await validate_analysis_url(final_url)
                except UnsafeURLError:
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


@app.get("/api/open-browser-stream")
async def analyze_endpoint(
    url: str = fastapi.Query(..., description="The URL to analyze"),
    device: str = fastapi.Query("ipad", description="Device type to emulate"),
    clear_cache: bool = fastapi.Query(False, alias="clear-cache", description="Clear all caches before analysis"),
) -> responses.StreamingResponse:
    """
    Analyze tracking on a URL with streaming progress via SSE.
    """
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


# ============================================================================
# Static File Serving (Production)
# ============================================================================

dist_path = pathlib.Path(__file__).resolve().parent.parent.parent / "dist"

if SHOW_UI and dist_path.exists():
    log.info("Serving static files", {"path": str(dist_path)})
    app.mount("/assets", staticfiles.StaticFiles(directory=str(dist_path / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> responses.FileResponse:
        """SPA fallback - serve index.html for all non-API routes."""
        file_path = (dist_path / full_path).resolve()
        if file_path.is_relative_to(dist_path) and file_path.exists() and file_path.is_file():
            return responses.FileResponse(str(file_path))
        return responses.FileResponse(str(dist_path / "index.html"))
