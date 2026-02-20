"""Tests for the storage lookup service.

Verifies that known storage keys are resolved from databases without
LLM calls, and that the fallback path is exercised for unknown keys.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.storage_info_agent import StorageInfoAgent, StorageInfoResult
from src.analysis import storage_lookup

# ── Database lookups (no LLM) ──────────────────────────────────


class TestKnownStorageKeys:
    """Storage keys in the tracking-storage.json database should return
    a result without touching the LLM."""

    @pytest.mark.asyncio
    async def test_amplitude_id_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "amplitude_id_my_project",
            "localStorage",
            '{"deviceId":"abc123"}',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Amplitude" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_segment_anonymous_id_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "ajs_anonymous_id",
            "localStorage",
            '"abc-def-123"',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Segment" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_segment_user_id_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "ajs_user_id",
            "localStorage",
            '"user-456"',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Segment" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixpanel_key_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "mp_abc123_mixpanel",
            "localStorage",
            '{"distinct_id":"xyz"}',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Mixpanel" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_facebook_fbp_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "_fbp",
            "localStorage",
            "fb.1.12345.67890",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Meta" in result.set_by or "Facebook" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_hotjar_session_user_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "_hjSessionUser_1234567",
            "localStorage",
            '{"id":"abc","uuid":"def"}',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Hotjar" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_optimizely_end_user_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "optimizelyEndUserId",
            "localStorage",
            "oeu1234567890r0.12345",
            agent,
        )
        assert result.purpose == "analytics"
        assert "Optimizely" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_fullstory_uid_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "fs_uid",
            "localStorage",
            '{"uid":"abc123"}',
            agent,
        )
        assert result.purpose == "analytics"
        assert "FullStory" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_heap_id_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "_hp2_id.abc123",
            "localStorage",
            '{"userId":"xyz","identity":"abc"}',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Heap" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_criteo_storage_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "cto_bundle",
            "localStorage",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "Criteo" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_adobe_ecid_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "AMCV_ABC123456789",
            "localStorage",
            "MCMID|12345",
            agent,
        )
        assert result.purpose == "identity-resolution"
        assert "Adobe" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_cookiebot_consent_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "CookieConsent",
            "localStorage",
            '{"stamp":"abc","necessary":1}',
            agent,
        )
        assert result.purpose == "consent"
        assert "Cookiebot" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_optanon_consent_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "OptanonConsent",
            "localStorage",
            "isIABGlobal=false&groups=C0001:1",
            agent,
        )
        assert result.purpose == "consent"
        assert "OneTrust" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_fingerprint_key_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "fpjs_visitor_id",
            "localStorage",
            "abc123xyz",
            agent,
        )
        assert result.purpose == "fingerprinting"
        assert "FingerprintJS" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_device_id_pattern_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "device_id",
            "localStorage",
            "uuid-abc-123",
            agent,
        )
        assert result.purpose == "fingerprinting"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_loglevel_functional(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "loglevel",
            "localStorage",
            "warn",
            agent,
        )
        assert result.purpose == "functional"
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_tiktok_ttp_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "_ttp",
            "localStorage",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "TikTok" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_linkedin_storage_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "li_fat_id",
            "localStorage",
            "abc123",
            agent,
        )
        assert result.purpose == "advertising"
        assert "LinkedIn" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_prebid_storage_found(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "pbjs:s2sConfig",
            "localStorage",
            '{"accountId":"12345"}',
            agent,
        )
        assert result.purpose == "advertising"
        assert "Prebid" in result.set_by
        agent.explain.assert_not_called()

    @pytest.mark.asyncio
    async def test_risk_level_populated(self) -> None:
        """Matched keys should have a risk level from the risk map."""
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "_fbp",
            "localStorage",
            "fb.1.12345.67890",
            agent,
        )
        assert result.risk_level == "high"

    @pytest.mark.asyncio
    async def test_privacy_note_populated(self) -> None:
        """Matched keys should have a privacy note from the map."""
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "amplitude_id",
            "localStorage",
            '{"deviceId":"abc"}',
            agent,
        )
        assert result.privacy_note  # Non-empty

    @pytest.mark.asyncio
    async def test_session_storage_works(self) -> None:
        """sessionStorage keys should match the same patterns."""
        agent = AsyncMock(spec=StorageInfoAgent)
        result = await storage_lookup.get_storage_info(
            "ajs_anonymous_id",
            "sessionStorage",
            '"abc-def-123"',
            agent,
        )
        assert result.purpose == "analytics"
        assert "Segment" in result.set_by
        agent.explain.assert_not_called()


# ── LLM fallback ───────────────────────────────────────────────


class TestLLMFallback:
    """Unknown storage keys should fall back to the LLM agent."""

    @pytest.mark.asyncio
    async def test_unknown_key_calls_llm(self) -> None:
        llm_result = StorageInfoResult(
            description="Custom UI state storage",
            setBy="Website",
            purpose="functional",
            riskLevel="none",
            privacyNote="",
        )
        agent = AsyncMock(spec=StorageInfoAgent)
        agent.explain = AsyncMock(return_value=llm_result)

        result = await storage_lookup.get_storage_info(
            "my_custom_state",
            "localStorage",
            '{"collapsed":true}',
            agent,
        )
        assert result.description == "Custom UI state storage"
        assert result.purpose == "functional"
        agent.explain.assert_called_once_with(
            "my_custom_state",
            "localStorage",
            '{"collapsed":true}',
        )

    @pytest.mark.asyncio
    async def test_llm_failure_returns_generic(self) -> None:
        agent = AsyncMock(spec=StorageInfoAgent)
        agent.explain = AsyncMock(return_value=None)

        result = await storage_lookup.get_storage_info(
            "mystery_key",
            "localStorage",
            "val",
            agent,
        )
        assert result.purpose == "unknown"
        assert result.risk_level == "low"


# ── Serialisation ──────────────────────────────────────────────


class TestStorageInfoResult:
    """Verify the Pydantic model serialises correctly with aliases."""

    def test_serialisation_by_alias(self) -> None:
        result = StorageInfoResult(
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


class TestStorageInfoAgentFallbackParsing:
    """Verify the agent falls back to manual JSON parsing when
    response.value returns None."""

    @pytest.mark.asyncio
    async def test_json_text_fallback_parses_valid_json(self) -> None:
        """When response.value is None but response.text contains
        valid JSON, the agent should parse it manually."""
        agent = StorageInfoAgent.__new__(StorageInfoAgent)
        json_text = json.dumps(
            {
                "description": "Page engagement timing metric",
                "setBy": "DotMetrics",
                "purpose": "analytics",
                "riskLevel": "medium",
                "privacyNote": "Tracks time on page.",
            }
        )
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("DotMetricsTimeOnPage", "localStorage", "12345")

        assert result is not None
        assert result.description == "Page engagement timing metric"
        assert result.purpose == "analytics"

    @pytest.mark.asyncio
    async def test_json_text_fallback_with_markdown_fences(self) -> None:
        """JSON wrapped in markdown code fences should still be parsed."""
        agent = StorageInfoAgent.__new__(StorageInfoAgent)
        json_text = (
            "```json\n"
            + json.dumps(
                {
                    "description": "Test key",
                    "setBy": "TestSDK",
                    "purpose": "functional",
                    "riskLevel": "none",
                    "privacyNote": "",
                }
            )
            + "\n```"
        )
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("test_key", "localStorage", "val")

        assert result is not None
        assert result.purpose == "functional"

    @pytest.mark.asyncio
    async def test_invalid_json_text_returns_none(self) -> None:
        """When both response.value and text parsing fail, return None."""
        agent = StorageInfoAgent.__new__(StorageInfoAgent)
        mock_response = MagicMock()
        mock_response.value = None
        mock_response.text = "I don't know this key."

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("mystery_key", "localStorage", "val")

        assert result is None

    @pytest.mark.asyncio
    async def test_structured_parse_from_text(self) -> None:
        """When response.text contains valid JSON, _parse_response
        parses it directly without needing the fallback."""
        agent = StorageInfoAgent.__new__(StorageInfoAgent)
        json_text = json.dumps(
            {
                "description": "Structured result",
                "setBy": "Framework",
                "purpose": "session",
                "riskLevel": "none",
                "privacyNote": "",
            }
        )
        mock_response = MagicMock()
        mock_response.text = json_text

        with patch.object(agent, "_complete", new_callable=AsyncMock, return_value=mock_response):
            result = await agent.explain("session_id", "sessionStorage", "abc")

        assert result is not None
        assert result.description == "Structured result"
        assert result.purpose == "session"
