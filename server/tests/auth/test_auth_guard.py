"""Tests for the auth guard middleware — session cookie security.

Validates that the auth middleware correctly blocks unauthenticated
requests, allows valid sessions through, and rejects tampered or
expired session cookies.

Uses a minimal FastAPI app with the auth guard and session middleware
rather than the real app, avoiding module-reload side effects.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Generator
from unittest import mock

import fastapi
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from starlette.middleware import sessions

from src.auth import auth_routes, middleware

_TEST_SECRET = "test-session-secret-for-auth-guard-tests"

_VALID_USER = {
    "user": {
        "sub": "user-123",
        "name": "Test User",
        "email": "test@example.com",
        "picture": "",
    }
}


def _sign_session(session: dict, secret: str = _TEST_SECRET) -> str:
    """Create a signed session cookie value."""
    signer = TimestampSigner(secret)
    data = base64.b64encode(json.dumps(session).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


def _build_auth_app() -> fastapi.FastAPI:
    """Build a minimal app with auth guard + session middleware."""
    app = fastapi.FastAPI()

    @app.post("/api/test")
    async def api_test() -> dict:
        return {"ok": True}

    @app.get("/page")
    async def page() -> dict:
        return {"page": True}

    @app.get("/assets/test.js")
    async def assets_test() -> dict:
        return {"asset": True}

    @app.middleware("http")
    async def _guard(request: fastapi.Request, call_next) -> fastapi.Response:  # type: ignore[no-untyped-def]
        return await middleware.auth_guard(request, call_next)

    # SessionMiddleware must be added AFTER the guard (LIFO ordering).
    app.add_middleware(
        sessions.SessionMiddleware,
        secret_key=_TEST_SECRET,
        session_cookie="mk_session",
        max_age=24 * 60 * 60,
        same_site="lax",
    )

    app.include_router(auth_routes.router)
    return app


@pytest.fixture()
def auth_client() -> Generator[TestClient]:
    """Test client with auth enabled but no session cookie."""
    env = {
        "OAUTH_ISSUER": "https://issuer.example.com",
        "OAUTH_CLIENT_ID": "test-client-id",
        "OAUTH_CLIENT_SECRET": "test-client-secret",
        "SESSION_SECRET": _TEST_SECRET,
    }
    with mock.patch.dict("os.environ", env):
        app = _build_auth_app()
        yield TestClient(app, raise_server_exceptions=False)


class TestUnauthenticatedAccess:
    """Requests without a session cookie must be blocked."""

    def test_api_returns_401(self, auth_client: TestClient) -> None:
        """API endpoints return 401 JSON for unauthenticated requests."""
        response = auth_client.post("/api/test")
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    def test_page_redirects_to_login(self, auth_client: TestClient) -> None:
        """Non-API page requests redirect to /auth/login."""
        response = auth_client.get("/page", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/auth/login"

    def test_auth_me_returns_401(self, auth_client: TestClient) -> None:
        """/auth/me without session returns 401."""
        response = auth_client.get("/auth/me")
        assert response.status_code == 401


class TestPassThroughPaths:
    """Certain paths must always be accessible without auth."""

    def test_auth_paths_not_redirected(self, auth_client: TestClient) -> None:
        """/auth/* endpoints reach the handler, not the login redirect."""
        response = auth_client.get("/auth/me")
        # Should reach the handler (401 from the route, not 302 from guard).
        assert response.status_code == 401

    def test_assets_paths_allowed(self, auth_client: TestClient) -> None:
        """/assets/* static files are not blocked."""
        response = auth_client.get("/assets/test.js")
        assert response.status_code == 200


class TestValidSession:
    """A valid signed session cookie must grant access."""

    def test_api_accessible_with_valid_session(self, auth_client: TestClient) -> None:
        auth_client.cookies.set("mk_session", _sign_session(_VALID_USER))
        response = auth_client.post("/api/test")
        assert response.status_code == 200

    def test_auth_me_returns_user(self, auth_client: TestClient) -> None:
        auth_client.cookies.set("mk_session", _sign_session(_VALID_USER))
        response = auth_client.get("/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["sub"] == "user-123"


class TestTamperedSession:
    """Tampered or invalid session cookies must be rejected."""

    def test_wrong_secret_rejected(self, auth_client: TestClient) -> None:
        """A cookie signed with a different secret must not authenticate."""
        bad_cookie = _sign_session(_VALID_USER, secret="wrong-secret")
        auth_client.cookies.set("mk_session", bad_cookie)
        response = auth_client.post("/api/test")
        assert response.status_code == 401

    def test_corrupted_cookie_rejected(self, auth_client: TestClient) -> None:
        """A garbled cookie value must not authenticate."""
        auth_client.cookies.set("mk_session", "not-a-valid-signed-value")
        response = auth_client.post("/api/test")
        assert response.status_code == 401

    def test_modified_payload_rejected(self, auth_client: TestClient) -> None:
        """Modifying the payload after signing must fail verification."""
        valid = _sign_session(_VALID_USER)
        parts = valid.split(".")
        payload = list(parts[0])
        payload[5] = "X" if payload[5] != "X" else "Y"
        parts[0] = "".join(payload)
        tampered = ".".join(parts)
        auth_client.cookies.set("mk_session", tampered)
        response = auth_client.post("/api/test")
        assert response.status_code == 401

    def test_empty_session_rejected(self, auth_client: TestClient) -> None:
        """A validly signed but empty session (no user) must not authenticate."""
        empty_cookie = _sign_session({})
        auth_client.cookies.set("mk_session", empty_cookie)
        response = auth_client.post("/api/test")
        assert response.status_code == 401


class TestExpiredSession:
    """Session cookies beyond max_age must be rejected."""

    def test_expired_cookie_rejected(self, auth_client: TestClient) -> None:
        """A cookie older than max_age (24h) must not authenticate."""
        signer = TimestampSigner(_TEST_SECRET)
        data = base64.b64encode(json.dumps(_VALID_USER).encode("utf-8"))
        signed = signer.sign(data).decode("utf-8")

        original_time = time.time
        with mock.patch("time.time", return_value=original_time() + 25 * 3600):
            auth_client.cookies.set("mk_session", signed)
            response = auth_client.post("/api/test")
            assert response.status_code == 401
