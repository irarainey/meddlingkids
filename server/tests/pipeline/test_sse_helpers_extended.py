"""Tests for src.pipeline.sse_helpers — extended SSE serialization."""

from __future__ import annotations

import json

from src.models import analysis, consent
from src.pipeline.sse_helpers import (
    format_screenshot_update_event,
    serialize_consent_details,
    serialize_score_breakdown,
)


class TestFormatScreenshotUpdateEvent:
    """Tests for format_screenshot_update_event()."""

    def test_event_type(self) -> None:
        result = format_screenshot_update_event("data:image/jpeg;base64,abc")
        assert result.startswith("event: screenshotUpdate\n")

    def test_contains_screenshot(self) -> None:
        result = format_screenshot_update_event("data:image/jpeg;base64,abc")
        payload = json.loads(result.split("\n")[1][len("data: ") :])
        assert payload["screenshot"] == "data:image/jpeg;base64,abc"

    def test_ends_with_double_newline(self) -> None:
        result = format_screenshot_update_event("img")
        assert result.endswith("\n\n")


class TestSerializeConsentDetailsExtended:
    """Extended tests for serialize_consent_details()."""

    def test_categories_serialized(self) -> None:
        details = consent.ConsentDetails(
            has_manage_options=True,
            categories=[
                consent.ConsentCategory(
                    name="Analytics",
                    description="Help us understand usage",
                    required=False,
                ),
            ],
            partners=[],
            purposes=["Analytics"],
            raw_text="We use cookies",
        )
        result = serialize_consent_details(details)
        assert "categories" in result
        assert len(result["categories"]) == 1

    def test_partners_serialized(self) -> None:
        details = consent.ConsentDetails(
            has_manage_options=True,
            categories=[],
            partners=[
                consent.ConsentPartner(
                    name="Google",
                    purpose="Analytics",
                    data_collected=["pageviews"],
                ),
            ],
            purposes=[],
            raw_text="",
        )
        result = serialize_consent_details(details)
        assert "partners" in result
        assert len(result["partners"]) == 1

    def test_claimed_partner_count_camel_case(self) -> None:
        details = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="",
            claimed_partner_count=42,
        )
        result = serialize_consent_details(details)
        assert "claimedPartnerCount" in result
        assert result["claimedPartnerCount"] == 42


class TestSerializeScoreBreakdownExtended:
    """Extended tests for serialize_score_breakdown()."""

    def test_categories_serialized(self) -> None:
        sb = analysis.ScoreBreakdown(
            total_score=65,
            factors=["many cookies"],
            categories={
                "cookies": analysis.CategoryScore(points=10, max_points=22, issues=["20 cookies"]),
            },
        )
        result = serialize_score_breakdown(sb)
        assert "totalScore" in result
        assert result["totalScore"] == 65
        assert "categories" in result
        assert "cookies" in result["categories"]

    def test_empty_breakdown(self) -> None:
        sb = analysis.ScoreBreakdown()
        result = serialize_score_breakdown(sb)
        assert result["totalScore"] == 0
        assert result["factors"] == []
