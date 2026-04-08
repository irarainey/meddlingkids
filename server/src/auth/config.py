"""OAuth2 configuration from environment variables.

Auth is enabled only when all four required variables are set:
``OAUTH_ISSUER``, ``OAUTH_CLIENT_ID``, ``OAUTH_CLIENT_SECRET``, ``SESSION_SECRET``.

When any of these are absent the entire auth layer is a no-op, allowing
the application to run locally or in a container without authentication.
"""

from __future__ import annotations

import os
import urllib.parse

_REQUIRED_VARS = ("OAUTH_ISSUER", "OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "SESSION_SECRET")


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
    origins = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:4173")
    hosts: set[str] = {"localhost", "127.0.0.1"}
    for origin in origins.split(","):
        origin = origin.strip()
        if origin:
            try:
                parsed = urllib.parse.urlparse(origin)
                if parsed.hostname:
                    hosts.add(parsed.hostname)
            except Exception:
                pass
    return hosts
