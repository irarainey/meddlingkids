"""Tests for the FastAPI server routes — src.main.

Uses FastAPI TestClient for synchronous route testing.
Skips lifespan (no browser needed for API route tests).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    """Create a test client without triggering lifespan.

    When OAuth is enabled (env vars present), injects a valid session
    cookie so existing API tests are not blocked by the auth middleware.
    """
    from src.main import app

    c = TestClient(app, raise_server_exceptions=False)

    from src.auth.config import is_auth_enabled

    if is_auth_enabled():
        import base64
        import json
        import os

        from itsdangerous import TimestampSigner

        signer = TimestampSigner(os.environ["SESSION_SECRET"])
        session = {"user": {"sub": "test", "name": "Test User", "email": "test@example.com", "picture": ""}}
        data = base64.b64encode(json.dumps(session).encode("utf-8"))
        c.cookies.set("mk_session", signer.sign(data).decode("utf-8"))

    return c


class TestClearCacheEndpoint:
    """Tests for POST /api/clear-cache."""

    def test_clear_cache(self, client: TestClient) -> None:
        response = client.post("/api/clear-cache")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert "filesRemoved" in data


class TestDomainInfoEndpoint:
    """Tests for POST /api/domain-info."""

    def test_with_domains(self, client: TestClient) -> None:
        response = client.post(
            "/api/domain-info",
            json={"domains": ["google.com", "facebook.com"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "google.com" in data
        assert "facebook.com" in data

    def test_empty_domains(self, client: TestClient) -> None:
        response = client.post("/api/domain-info", json={"domains": []})
        assert response.status_code == 400

    def test_missing_domains_key(self, client: TestClient) -> None:
        response = client.post("/api/domain-info", json={})
        assert response.status_code == 400


class TestStorageKeyInfoEndpoint:
    """Tests for POST /api/storage-key-info."""

    def test_with_keys(self, client: TestClient) -> None:
        response = client.post(
            "/api/storage-key-info",
            json={"keys": ["_ga", "amplitude_id"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_empty_keys(self, client: TestClient) -> None:
        response = client.post("/api/storage-key-info", json={"keys": []})
        assert response.status_code == 400


class TestTcfPurposesEndpoint:
    """Tests for POST /api/tcf-purposes."""

    def test_with_purposes(self, client: TestClient) -> None:
        response = client.post(
            "/api/tcf-purposes",
            json={"purposes": ["Analytics", "Advertising"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "matched" in data or "unmatched" in data

    def test_empty_purposes(self, client: TestClient) -> None:
        response = client.post("/api/tcf-purposes", json={"purposes": []})
        assert response.status_code == 200
        data = response.json()
        assert data == {"matched": [], "unmatched": []}


class TestTcStringDecodeEndpoint:
    """Tests for POST /api/tc-string-decode."""

    def test_empty_tc_string(self, client: TestClient) -> None:
        response = client.post("/api/tc-string-decode", json={"tcString": ""})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    def test_invalid_tc_string(self, client: TestClient) -> None:
        response = client.post("/api/tc-string-decode", json={"tcString": "invalid"})
        assert response.status_code == 200
        data = response.json()
        assert "error" in data


class TestFetchScriptEndpoint:
    """Tests for POST /api/fetch-script."""

    def test_missing_url(self, client: TestClient) -> None:
        response = client.post("/api/fetch-script", json={"url": ""})
        assert response.status_code == 400

    def test_non_http_url(self, client: TestClient) -> None:
        response = client.post("/api/fetch-script", json={"url": "ftp://example.com/file"})
        assert response.status_code == 400

    def test_private_ip_rejected(self, client: TestClient) -> None:
        response = client.post("/api/fetch-script", json={"url": "http://127.0.0.1/script.js"})
        assert response.status_code == 400


class TestCookieInfoEndpoint:
    """Tests for POST /api/cookie-info."""

    def test_missing_name(self, client: TestClient) -> None:
        response = client.post("/api/cookie-info", json={"name": ""})
        assert response.status_code == 400


class TestStorageInfoEndpoint:
    """Tests for POST /api/storage-info."""

    def test_missing_key(self, client: TestClient) -> None:
        response = client.post("/api/storage-info", json={"key": ""})
        assert response.status_code == 400


class TestJsonDecodeError:
    """Tests for malformed JSON error handler."""

    def test_malformed_json(self, client: TestClient) -> None:
        response = client.post(
            "/api/domain-info",
            content=b"not json {{",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400 or response.status_code == 422


class TestAnalyzeEndpoint:
    """Tests for GET /api/open-browser-stream."""

    def test_missing_url(self, client: TestClient) -> None:
        response = client.get("/api/open-browser-stream")
        assert response.status_code == 422  # Missing required query parameter

    def test_returns_event_stream(self, client: TestClient) -> None:
        # Mock the stream to avoid needing a real browser
        async def mock_stream(*args, **kwargs):
            yield 'event: progress\ndata: {"step":"init"}\n\n'
            yield "event: complete\ndata: {}\n\n"

        with patch("src.pipeline.stream.analyze_url_stream", mock_stream):
            response = client.get(
                "/api/open-browser-stream",
                params={"url": "https://example.com"},
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
