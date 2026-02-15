"""Tests for src.pipeline.sse_helpers — SSE formatting utilities."""

from __future__ import annotations

import json

from src.models import analysis, consent, tracking_data
from src.pipeline.sse_helpers import (
    format_progress_event,
    format_sse_event,
    serialize_consent_details,
    serialize_score_breakdown,
    to_camel_case_dict,
)


class TestFormatSseEvent:
    def test_basic_event(self) -> None:
        result = format_sse_event("progress", {"step": "init"})
        assert result.startswith("event: progress\n")
        assert result.endswith("\n\n")
        data_line = result.split("\n")[1]
        assert data_line.startswith("data: ")
        payload = json.loads(data_line[len("data: ") :])
        assert payload == {"step": "init"}

    def test_complex_data(self) -> None:
        data = {"a": [1, 2], "b": {"nested": True}}
        result = format_sse_event("test", data)
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["a"] == [1, 2]
        assert payload["b"]["nested"] is True


class TestFormatProgressEvent:
    def test_progress_event(self) -> None:
        result = format_progress_event("loading", "Loading page", 50)
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["step"] == "loading"
        assert payload["message"] == "Loading page"
        assert payload["progress"] == 50


class TestToCamelCaseDict:
    def test_converts_keys(self) -> None:
        item = tracking_data.StorageItem(key="k", value="v", timestamp="t")
        result = to_camel_case_dict(item)
        assert "key" in result
        assert "value" in result
        assert "timestamp" in result

    def test_snake_case_converted(self) -> None:
        cookie = tracking_data.TrackedCookie(
            name="a",
            value="b",
            domain="d",
            path="/",
            expires=0,
            http_only=True,
            secure=True,
            same_site="Lax",
            timestamp="t",
        )
        result = to_camel_case_dict(cookie)
        assert "httpOnly" in result
        assert "sameSite" in result


class TestSerializeConsentDetails:
    def test_excludes_raw_text(self) -> None:
        details = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="Secret internal text",
        )
        result = serialize_consent_details(details)
        assert "rawText" not in result
        assert "raw_text" not in result

    def test_camel_case_keys(self) -> None:
        details = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="text",
            claimed_partner_count=5,
        )
        result = serialize_consent_details(details)
        assert "hasManageOptions" in result
        assert "claimedPartnerCount" in result


class TestSerializeScoreBreakdown:
    def test_camel_case(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=75,
            factors=["factor1"],
            summary="test",
        )
        result = serialize_score_breakdown(sb)
        assert "totalScore" in result
        assert "factors" in result
        assert "summary" in result
