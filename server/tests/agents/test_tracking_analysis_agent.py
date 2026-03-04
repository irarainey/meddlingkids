"""Tests for TrackingAnalysisAgent structured output and timeout defaults.

Validates that ``analyze()`` returns a typed
``TrackingAnalysisResult`` from structured JSON, falls
back gracefully on parse failures, and that call-timeout
defaults are set to expected values across agents.
"""

from __future__ import annotations

import json
from unittest import mock

import agent_framework
import pytest

from src.agents import base, consent_detection_agent, structured_report_agent, tracking_analysis_agent
from src.models import analysis


def _empty_summary() -> analysis.TrackingSummary:
    """Minimal TrackingSummary for testing."""
    return analysis.TrackingSummary(
        analyzed_url="https://example.com",
        total_cookies=0,
        total_scripts=0,
        total_network_requests=0,
        local_storage_items=0,
        session_storage_items=0,
        third_party_domains=[],
        domain_breakdown=[],
        local_storage=[],
        session_storage=[],
    )


def _make_response(
    text: str,
) -> agent_framework.AgentResponse:
    """Build a minimal AgentResponse for testing.

    Args:
        text: Raw response text.
    """
    return agent_framework.AgentResponse(
        messages=[agent_framework.Message(role="assistant", text=text)],
    )


def _make_agent() -> tracking_analysis_agent.TrackingAnalysisAgent:
    """Create a bare TrackingAnalysisAgent for unit tests."""
    agent = tracking_analysis_agent.TrackingAnalysisAgent.__new__(
        tracking_analysis_agent.TrackingAnalysisAgent,
    )
    agent.agent_name = "TrackingAnalysisAgent"
    agent.max_tokens = 4096
    agent.max_retries = 5
    agent.call_timeout = 60
    return agent


class TestTrackingAnalysisStructuredOutput:
    """Tests for the structured (non-streaming) TrackingAnalysisAgent."""

    @pytest.mark.asyncio
    async def test_structured_parse_success(self) -> None:
        """Agent returns TrackingAnalysisResult on successful parse."""
        parsed = tracking_analysis_agent._TrackingAnalysisResponse(
            risk_level="high",
            risk_summary="Lots of trackers.",
            sections=[
                analysis.TrackingAnalysisSection(
                    heading="Tracking Technologies Identified",
                    content="Google Analytics detected.",
                ),
            ],
        )
        resp = _make_response(
            text=json.dumps(parsed.model_dump()),
        )
        agent = _make_agent()

        with mock.patch.object(agent, "_complete", return_value=resp):
            result = await agent.analyze(_empty_summary())

        assert isinstance(result, analysis.TrackingAnalysisResult)
        assert result.risk_level == "high"
        assert result.risk_summary == "Lots of trackers."
        assert len(result.sections) == 1
        assert result.sections[0].heading == "Tracking Technologies Identified"

    @pytest.mark.asyncio
    async def test_text_fallback_on_parse_failure(self) -> None:
        """Agent falls back to JSON text parsing when structured parse fails."""
        json_body = {
            "risk_level": "low",
            "risk_summary": "Clean site.",
            "sections": [
                {"heading": "Cookie Analysis", "content": "No cookies."},
            ],
        }
        resp = _make_response(text=json.dumps(json_body))

        agent = _make_agent()

        with (
            mock.patch.object(agent, "_complete", return_value=resp),
            # _parse_response returns None (structured parse fails)
            mock.patch.object(agent, "_parse_response", return_value=None),
        ):
            result = await agent.analyze(_empty_summary())

        assert isinstance(result, analysis.TrackingAnalysisResult)
        assert result.risk_level == "low"
        assert result.sections[0].heading == "Cookie Analysis"

    @pytest.mark.asyncio
    async def test_raw_text_fallback(self) -> None:
        """Agent wraps raw text when all parsing fails."""
        resp = _make_response(text="Some unparseable markdown text.")

        agent = _make_agent()

        with (
            mock.patch.object(agent, "_complete", return_value=resp),
            mock.patch.object(agent, "_parse_response", return_value=None),
        ):
            result = await agent.analyze(_empty_summary())

        assert isinstance(result, analysis.TrackingAnalysisResult)
        assert result.risk_level == "medium"
        assert len(result.sections) == 1
        assert result.sections[0].heading == "Raw Analysis"
        assert "unparseable" in result.sections[0].content

    @pytest.mark.asyncio
    async def test_to_text_serialization(self) -> None:
        """TrackingAnalysisResult.to_text() produces readable output."""
        result = analysis.TrackingAnalysisResult(
            risk_level="high",
            risk_summary="Many trackers found.",
            sections=[
                analysis.TrackingAnalysisSection(
                    heading="Tracking Technologies",
                    content="Google Analytics, Facebook Pixel.",
                ),
                analysis.TrackingAnalysisSection(
                    heading="Recommendations",
                    content="Use a content blocker.",
                ),
            ],
        )
        text = result.to_text()
        assert "Risk Level: high" in text
        assert "## Tracking Technologies" in text
        assert "Google Analytics, Facebook Pixel." in text
        assert "## Recommendations" in text

    @pytest.mark.asyncio
    async def test_code_fence_fallback(self) -> None:
        """Agent handles LLM responses wrapped in code fences."""
        json_body = {
            "risk_level": "medium",
            "risk_summary": "Moderate tracking.",
            "sections": [],
        }
        fenced = f"```json\n{json.dumps(json_body)}\n```"
        resp = _make_response(text=fenced)

        agent = _make_agent()

        with (
            mock.patch.object(agent, "_complete", return_value=resp),
            mock.patch.object(agent, "_parse_response", return_value=None),
        ):
            result = await agent.analyze(_empty_summary())

        assert result.risk_level == "medium"
        assert result.risk_summary == "Moderate tracking."


class TestDefaultTimeoutValues:
    """Verify default timeout settings are at the expected values."""

    def test_base_agent_default_timeout(self) -> None:
        assert base.BaseAgent.call_timeout == 30

    def test_consent_detection_timeout(self) -> None:
        assert consent_detection_agent.ConsentDetectionAgent.call_timeout == 30

    def test_structured_report_timeout(self) -> None:
        assert structured_report_agent.StructuredReportAgent.call_timeout == 60

    def test_tracking_analysis_timeout(self) -> None:
        assert tracking_analysis_agent.TrackingAnalysisAgent.call_timeout == 90

    def test_tracking_analysis_uses_structured_output(self) -> None:
        """TrackingAnalysisAgent has a response_model set."""
        assert tracking_analysis_agent.TrackingAnalysisAgent.response_model is not None
