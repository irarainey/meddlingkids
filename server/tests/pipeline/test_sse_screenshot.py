"""Tests for src.pipeline.sse_helpers — build_screenshot_event with mock session."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.models.tracking_data import (
    CapturedStorage,
    NetworkRequest,
    StorageItem,
    TrackedCookie,
    TrackedScript,
)
from src.pipeline.sse_helpers import build_screenshot_event


class TestBuildScreenshotEvent:
    """Tests for build_screenshot_event() with mocked session."""

    def test_basic_event(self) -> None:
        session = MagicMock()
        session.get_tracked_cookies.return_value = [
            TrackedCookie(
                name="_ga",
                value="v",
                domain="example.com",
                path="/",
                expires=0,
                http_only=False,
                secure=False,
                same_site="None",
                timestamp="t",
            ),
        ]
        session.get_tracked_scripts.return_value = [
            TrackedScript(url="https://example.com/app.js", domain="example.com"),
        ]
        session.get_tracked_network_requests.return_value = [
            NetworkRequest(
                url="https://example.com/api",
                domain="example.com",
                method="GET",
                resource_type="xhr",
                is_third_party=False,
                timestamp="t",
            ),
        ]
        storage = CapturedStorage(
            local_storage=[StorageItem(key="k", value="v", timestamp="t")],
        )

        result = build_screenshot_event(session, "data:image/jpeg;base64,abc", storage)
        assert result.startswith("event: screenshot\n")
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["screenshot"] == "data:image/jpeg;base64,abc"
        assert len(payload["cookies"]) == 1
        assert len(payload["scripts"]) == 1
        assert len(payload["networkRequests"]) == 1
        assert len(payload["localStorage"]) == 1

    def test_with_extra_fields(self) -> None:
        session = MagicMock()
        session.get_tracked_cookies.return_value = []
        session.get_tracked_scripts.return_value = []
        session.get_tracked_network_requests.return_value = []
        storage = CapturedStorage()

        result = build_screenshot_event(
            session,
            "img",
            storage,
            extra={"consentDetected": True, "overlayType": "cookie-consent"},
        )
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["consentDetected"] is True
        assert payload["overlayType"] == "cookie-consent"

    def test_empty_data(self) -> None:
        session = MagicMock()
        session.get_tracked_cookies.return_value = []
        session.get_tracked_scripts.return_value = []
        session.get_tracked_network_requests.return_value = []
        storage = CapturedStorage()

        result = build_screenshot_event(session, "", storage)
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["cookies"] == []
        assert payload["scripts"] == []
