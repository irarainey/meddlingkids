"""Authentication middleware — enforces login when OAuth is enabled.

When auth is disabled this middleware is never registered, so there is
zero overhead on the request path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import fastapi
from starlette import requests, responses

RequestResponseEndpoint = Callable[[requests.Request], Awaitable[fastapi.Response]]


async def auth_guard(request: requests.Request, call_next: RequestResponseEndpoint) -> fastapi.Response:
    """Block unauthenticated requests.

    Pass-through paths (always allowed):
      ``/auth/*``   — the login / callback / logout flow
      ``/assets/*`` — static assets (JS, CSS, images)

    Protected paths:
      ``/api/*``    — returns 401 JSON so the SPA can react
      ``/*``        — redirects the browser to ``/auth/login``
    """
    path = request.url.path

    if path.startswith("/auth") or path.startswith("/assets"):
        return await call_next(request)

    user = request.session.get("user")
    if user:
        return await call_next(request)

    # Not authenticated
    if path.startswith("/api"):
        return responses.JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return responses.RedirectResponse(url="/auth/login", status_code=302)
