"""Tests for the cookie lookup service.

Verifies that known cookies are resolved from databases without
LLM calls, and that the fallback path is exercised for unknown cookies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

from src.agents.cookie_info_agent import CookieInfoAgent, CookieInfoResult
from src.analysis import cookie_lookup

# ── Database lookups (no LLM) ──────────────────────────────────


class TestKnownConsentCookies:
    """Cookies in the consent-cookies.json database should return
    a result without touching the LLM."""

    @pytest.mark.asyncio
    async def test_onetrust_cookie_found(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "OptanonConsent",
            ".example.com",
            "groups=C0001:1",
            agent,
        )
        assert result.purpose == "consent"
        assert result.risk_level == "none"
        assert "OneTrust" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_tcf_euconsent_cookie_found(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "euconsent-v2",
            ".example.com",
            "abc123",
            agent,
        )
        assert result.purpose == "consent"
        assert result.risk_level == "none"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_didomi_cookie_found(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "didomi_token",
            ".example.com",
            "token123",
            agent,
        )
        assert result.purpose == "consent"
        assert result.risk_level == "none"
        agent.explain.assert_not_called()


class TestConsentPatterns:
    """Cookies matching consent-state regex patterns should be identified
    without an LLM call."""

    @pytest.mark.asyncio
    async def test_cookielawinfo_pattern(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "cookielawinfo-checkbox-marketing",
            ".example.com",
            "yes",
            agent,
        )
        assert result.purpose == "consent"
        assert result.risk_level == "none"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_cmplz_pattern(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "cmplz_functional",
            ".example.com",
            "allow",
            agent,
        )
        assert result.purpose == "consent"
        agent.explain.assert_not_called()


class TestTrackingPatterns:
    """Cookies matching known tracking patterns should be identified
    without an LLM call."""

    @pytest.mark.asyncio
    async def test_google_analytics_ga(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_ga",
            ".example.com",
            "GA1.2.12345.67890",
            agent,
        )
        assert result.purpose == "analytics"
        assert "Google Analytics" in result.set_by
        assert result.risk_level == "medium"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_facebook_pixel_fbp(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_fbp",
            ".example.com",
            "fb.1.12345.67890",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Facebook" in result.set_by
        assert result.risk_level == "high"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_hotjar_hjid(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_hjid",
            ".example.com",
            "abc-123",
            agent,
        )
        assert result.purpose == "fingerprinting"
        assert "Hotjar" in result.set_by
        assert result.risk_level == "critical"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_clarity_clck(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_clck",
            ".example.com",
            "abc",
            agent,
        )
        assert result.purpose == "fingerprinting"
        assert "Clarity" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_doubleclick_ide(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "IDE",
            ".doubleclick.net",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "DoubleClick" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_ga4_container_cookie(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_ga_1A2B3C4D5E",
            ".example.com",
            "GS1.1.12345.67890",
            agent,
        )
        assert result.purpose == "analytics"
        assert "GA4" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_tiktok_ttp(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_ttp",
            ".example.com",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "TikTok" in result.set_by
        assert result.risk_level == "high"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_linkedin_user_match_history(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "UserMatchHistory",
            ".linkedin.com",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "LinkedIn" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_microsoft_muid(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "MUID",
            ".bing.com",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Microsoft" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_adobe_analytics_s_vi(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "s_vi",
            ".example.com",
            "[CS]v1|abc[CE]",
            agent,
        )
        assert result.purpose == "analytics"
        assert "Adobe" in result.set_by
        assert result.risk_level == "medium"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_hubspot_hstc(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "__hstc",
            ".example.com",
            "abc.123.456.789.012.1",
            agent,
        )
        assert result.purpose == "analytics"
        assert "HubSpot" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_matomo_pk_id(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_pk_id.1.dc1a",
            ".example.com",
            "abc123.12345",
            agent,
        )
        assert result.purpose == "analytics"
        assert "Matomo" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapchat_scid(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_scid",
            ".example.com",
            "abc-def-123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Snapchat" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_reddit_rdt_uuid(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_rdt_uuid",
            ".example.com",
            "abc-123-def",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Reddit" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_amplitude_amp(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "AMP_abc123",
            ".example.com",
            "eyJhbGciO...",
            agent,
        )
        assert result.purpose == "analytics"
        assert "Amplitude" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_criteo_cto_bundle(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "cto_bundle",
            ".example.com",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Criteo" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_hotjar_absolute_session(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_hjAbsoluteSessionInProgress",
            ".example.com",
            "1",
            agent,
        )
        assert result.purpose == "fingerprinting"
        assert "Hotjar" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_facebook_datr(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "datr",
            ".facebook.com",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Facebook" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_twitter_guest_id_marketing(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "guest_id_marketing",
            ".twitter.com",
            "v1:abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Twitter" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_marketo_trk(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        result = await cookie_lookup.get_cookie_info(
            "_mkto_trk",
            ".example.com",
            "id:123-ABC-456&token:_mch-example.com-abc",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Marketo" in result.set_by or "Salesforce" in result.set_by
        agent.explain.assert_not_called()


class TestLLMFallback:
    """Unknown cookies should fall back to the LLM agent."""

    @pytest.mark.asyncio
    async def test_unknown_cookie_calls_llm(self) -> None:
        llm_result = CookieInfoResult(
            description="Custom session token",
            setBy="example.com",
            purpose="session",
            riskLevel="low",
            privacyNote="",
        )
        agent = AsyncMock(spec=CookieInfoAgent)
        agent.explain = AsyncMock(return_value=llm_result)

        result = await cookie_lookup.get_cookie_info(
            "my_custom_session",
            ".example.com",
            "xyz789",
            agent,
        )
        assert result.description == "Custom session token"
        assert result.purpose == "session"
        agent.explain.assert_called_once_with("my_custom_session", ".example.com", "xyz789")

    @pytest.mark.asyncio
    async def test_llm_failure_returns_generic(self) -> None:
        agent = AsyncMock(spec=CookieInfoAgent)
        agent.explain = AsyncMock(return_value=None)

        result = await cookie_lookup.get_cookie_info(
            "mystery_cookie",
            ".example.com",
            "val",
            agent,
        )
        assert result.purpose == "unknown"
        assert result.risk_level == "low"


class TestCookieInfoResult:
    """Verify the Pydantic model serialises correctly with aliases."""

    def test_serialisation_by_alias(self) -> None:
        result = CookieInfoResult(
            description="Test",
            setBy="Tester",
            purpose="analytics",
            riskLevel="medium",
            privacyNote="A note",
        )
        data = result.model_dump(by_alias=True)
        assert data["setBy"] == "Tester"
        assert data["riskLevel"] == "medium"
        assert data["privacyNote"] == "A note"
        assert "set_by" not in data
        assert "risk_level" not in data


class TestCookieInfoAgentFallbackParsing:
    """Verify the agent falls back to manual JSON parsing when
    response.value returns None."""

    @pytest.mark.asyncio
    async def test_json_text_fallback_parses_valid_json(self) -> None:
        """When response.value is None but response.text contains
        valid JSON, the agent should parse it manually."""
        agent = CookieInfoAgent.__new__(CookieInfoAgent)
        json_text = json.dumps({
            "description": "BBC multivariate testing cookie",
            "setBy": "BBC",
            "purpose": "functional",
            "riskLevel": "none",
            "privacyNote": "Used for A/B testing.",
        })
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("ckns_mvt", ".bbc.co.uk", "abc123")

        assert result is not None
        assert result.description == "BBC multivariate testing cookie"
        assert result.purpose == "functional"

    @pytest.mark.asyncio
    async def test_json_text_fallback_with_markdown_fences(self) -> None:
        """JSON wrapped in markdown code fences should still be parsed."""
        agent = CookieInfoAgent.__new__(CookieInfoAgent)
        json_text = '```json\n' + json.dumps({
            "description": "Test cookie",
            "setBy": "TestService",
            "purpose": "analytics",
            "riskLevel": "low",
            "privacyNote": "",
        }) + '\n```'
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("test_cookie", ".example.com", "val")

        assert result is not None
        assert result.purpose == "analytics"

    @pytest.mark.asyncio
    async def test_invalid_json_text_returns_none(self) -> None:
        """When both response.value and text parsing fail, return None."""
        agent = CookieInfoAgent.__new__(CookieInfoAgent)
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = "I don't know this cookie."

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("mystery", ".example.com", "val")

        assert result is None

    @pytest.mark.asyncio
    async def test_structured_parse_from_text(self) -> None:
        """When response.text contains valid JSON, _parse_response
        parses it directly without needing the fallback."""
        agent = CookieInfoAgent.__new__(CookieInfoAgent)
        json_text = json.dumps({
            "description": "Structured result",
            "setBy": "Framework",
            "purpose": "session",
            "riskLevel": "none",
            "privacyNote": "",
        })
        mock_response = MagicMock()
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("sid", ".example.com", "abc")

        assert result is not None
        assert result.description == "Structured result"
        assert result.purpose == "session"
