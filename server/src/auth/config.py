"""OAuth2 configuration from environment variables.

Auth is enabled only when all four required variables are set:
``OAUTH_ISSUER``, ``OAUTH_CLIENT_ID``, ``OAUTH_CLIENT_SECRET``, ``SESSION_SECRET``.

When any of these are absent the entire auth layer is a no-op, allowing
the application to run locally or in a container without authentication.
"""

from __future__ import annotations

import os
import urllib.parse

from src.utils import logger

log = logger.create_logger("AuthConfig")

_REQUIRED_VARS = ("OAUTH_ISSUER", "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "SESSION_SECRET")

_CORS_DEFAULT = "http://localhost:5173,http://localhost:4173"


def get_allowed_origins() -> list[str]:
    """Parse ``CORS_ALLOWED_ORIGINS`` into a list of origin strings.

    Centralises the parsing so both the CORS middleware and the auth
    trusted-host derivation share the same source of truth.
    """
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", _CORS_DEFAULT)
    return [o.strip() for o in raw.split(",") if o.strip()]


def is_auth_enabled() -> bool:
    """Return True when all required OAuth environment variables are set."""
    return all(os.environ.get(v) for v in _REQUIRED_VARS)


def get_oauth_config() -> dict[str, str]:
    """Read OAuth settings from the environment.

    Only call this when :func:`is_auth_enabled` returns ``True``.
    """
    issuer = os.environ["OAUTH_ISSUER"]
    issuer_base = issuer.rstrip("/")
    return {
        "issuer": issuer,
        "client_id": os.environ["OAUTH_CLIENT_ID"],
        "client_secret": os.environ["OAUTH_CLIENT_SECRET"],
        "session_secret": os.environ["SESSION_SECRET"],
        "audience": os.environ.get("OAUTH_AUDIENCE", ""),
        "scopes": os.environ.get("OAUTH_SCOPES", "openid profile email"),
        "post_logout_redirect_uri": os.environ.get("OAUTH_POST_LOGOUT_REDIRECT_URI", ""),
        "server_metadata_url": f"{issuer_base}/.well-known/openid-configuration",
    }


def get_trusted_hosts() -> set[str]:
    """Return hostnames that are trusted for OAuth redirect construction.

    Derived from ``CORS_ALLOWED_ORIGINS`` plus common local addresses.
    Prevents Host-header injection in redirect_uri and post_logout URIs.
    """
    hosts: set[str] = {"localhost", "127.0.0.1"}
    for origin in get_allowed_origins():
        try:
            parsed = urllib.parse.urlparse(origin)
            if parsed.hostname:
                hosts.add(parsed.hostname)
        except ValueError:
            log.warn("Ignoring malformed CORS origin", {"origin": origin})
    return hosts
