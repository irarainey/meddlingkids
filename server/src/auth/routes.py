"""OAuth2 authentication routes (login, callback, logout, user info).

These routes are always registered, but return safe no-op responses when
authentication is disabled.  This prevents the SPA catch-all route from
swallowing ``/auth/*`` requests and returning ``index.html``.
"""

from __future__ import annotations

import urllib.parse

import fastapi
from authlib.integrations import starlette_client
from starlette import requests, responses

from src.auth import config
from src.utils import logger

router = fastapi.APIRouter(prefix="/auth", tags=["auth"])

log = logger.create_logger("Auth")

_oauth: starlette_client.OAuth | None = None


def _get_oauth() -> starlette_client.OAuth:
    """Lazily initialise the authlib OAuth client."""
    global _oauth
    if _oauth is None:
        cfg = config.get_oauth_config()
        _oauth = starlette_client.OAuth()
        _oauth.register(
            name="provider",
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            server_metadata_url=cfg["server_metadata_url"],
            client_kwargs={
                "scope": cfg["scopes"],
                "code_challenge_method": "S256",
            },
        )
    return _oauth


def _get_trusted_base_url(request: requests.Request) -> str:
    """Return the request's base URL after validating the Host header.

    Prevents Host-header injection attacks that could redirect OAuth
    callbacks or post-logout URIs to an attacker-controlled domain.

    Raises:
        HTTPException: 400 if the Host header is not in the trusted set.
    """
    hostname = request.base_url.hostname or ""
    if hostname not in config.get_trusted_hosts():
        raise fastapi.HTTPException(status_code=400, detail="Untrusted host")
    return str(request.base_url).rstrip("/")


# ── Login ────────────────────────────────────────────────────────────────


@router.get("/login")
async def auth_login(request: requests.Request) -> responses.RedirectResponse:
    """Redirect to the OAuth2 provider's authorization endpoint."""
    if not config.is_auth_enabled():
        return responses.RedirectResponse(url="/")

    oauth = _get_oauth()
    cfg = config.get_oauth_config()
    base_url = _get_trusted_base_url(request)
    redirect_uri = base_url + "/auth/callback"

    extra: dict[str, str] = {}
    if cfg["audience"]:
        extra["audience"] = cfg["audience"]

    return await oauth.provider.authorize_redirect(request, redirect_uri, **extra)  # type: ignore[no-any-return]


# ── Callback ─────────────────────────────────────────────────────────────


@router.get("/callback")
async def auth_callback(request: requests.Request) -> responses.RedirectResponse:
    """Exchange the authorisation code for tokens and create a session."""
    if not config.is_auth_enabled():
        return responses.RedirectResponse(url="/")

    oauth = _get_oauth()
    try:
        token = await oauth.provider.authorize_access_token(request)
    except starlette_client.OAuthError as exc:
        log.error("OAuth token exchange failed", {"error": exc.description})
        raise fastapi.HTTPException(
            status_code=401,
            detail="Authentication failed. Please try again.",
        ) from exc

    userinfo: dict | None = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.provider.userinfo(token=token)

    if not userinfo:
        raise fastapi.HTTPException(status_code=401, detail="Could not retrieve user information")

    request.session["user"] = {
        "sub": userinfo.get("sub", ""),
        "name": userinfo.get("name", ""),
        "email": userinfo.get("email", ""),
        "picture": userinfo.get("picture", ""),
    }

    return responses.RedirectResponse(url="/")


# ── User info ────────────────────────────────────────────────────────────


@router.get("/me")
async def auth_me(request: requests.Request) -> dict[str, object]:
    """Return the current user's profile, or signal that auth is disabled.

    Responses:
      * Auth disabled → ``{"enabled": false}``
      * Authenticated → ``{"enabled": true, "sub": …, "name": …, …}``
      * Not authenticated → HTTP 401
    """
    if not config.is_auth_enabled():
        return {"enabled": False}

    user = request.session.get("user")
    if not user:
        raise fastapi.HTTPException(status_code=401, detail="Not authenticated")

    return {"enabled": True, **user}


# ── Logout ───────────────────────────────────────────────────────────────


@router.post("/logout")
async def auth_logout(request: requests.Request) -> responses.RedirectResponse:
    """Clear the session and redirect to the provider's logout endpoint.

    Uses POST to prevent CSRF-based forced logout via ``<img>`` or link tags.
    ``SameSite=lax`` cookies are not sent on cross-origin POST submissions,
    so an attacker's page cannot include the victim's session cookie.
    """
    if not config.is_auth_enabled():
        return responses.RedirectResponse(url="/")

    cfg = config.get_oauth_config()
    request.session.clear()

    # Where to land after provider-side logout.  Prefer the explicit
    # env var; fall back to the validated request base URL.
    base_url = _get_trusted_base_url(request)
    post_logout = cfg["post_logout_redirect_uri"] or base_url

    # Use the standard OIDC end_session_endpoint when available
    oauth = _get_oauth()
    try:
        metadata = await oauth.provider.load_server_metadata()
    except Exception:
        metadata = {}

    end_session = metadata.get("end_session_endpoint")
    if end_session:
        params = urllib.parse.urlencode(
            {
                "client_id": cfg["client_id"],
                "post_logout_redirect_uri": post_logout,
            }
        )
        return responses.RedirectResponse(url=f"{end_session}?{params}")

    # Fallback for providers (e.g. Auth0) that don't advertise
    # end_session_endpoint but do support /v2/logout.
    issuer = cfg["issuer"]
    params = urllib.parse.urlencode(
        {
            "client_id": cfg["client_id"],
            "returnTo": post_logout,
        }
    )
    return responses.RedirectResponse(url=f"{issuer}/v2/logout?{params}")
