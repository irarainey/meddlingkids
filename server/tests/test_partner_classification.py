"""Tests for src.consent.partner_classification."""

from __future__ import annotations

from src.consent.partner_classification import (
    _classify_by_purpose,
    _matches_partner,
    classify_partner_by_pattern_sync,
    get_partner_risk_summary,
)
from src.models import consent, partners

# ── _matches_partner ────────────────────────────────────────────


class TestMatchesPartner:
    def test_key_in_name(self) -> None:
        assert _matches_partner("google analytics", "google", [])

    def test_alias_matches(self) -> None:
        assert _matches_partner("ga4", "google-analytics", ["ga4"])

    def test_no_match(self) -> None:
        assert not _matches_partner("facebook", "google", ["ga4"])


# ── _classify_by_purpose ───────────────────────────────────────


def _partner(name: str, purpose: str = "") -> consent.ConsentPartner:
    return consent.ConsentPartner(name=name, purpose=purpose, data_collected=[])


class TestClassifyByPurpose:
    def test_data_broker(self) -> None:
        result = _classify_by_purpose(_partner("Acme", "data sell"), "data sell")
        assert result is not None
        assert result.risk_level == "critical"
        assert result.category == "data-broker"

    def test_cross_site(self) -> None:
        result = _classify_by_purpose(_partner("X", "cross-site"), "cross-site")
        assert result is not None
        assert result.risk_level == "high"
        assert result.category == "cross-site-tracking"

    def test_advertising(self) -> None:
        result = _classify_by_purpose(_partner("Ad", "advertising"), "advertising")
        assert result is not None
        assert result.risk_level == "medium"
        assert result.category == "advertising"

    def test_analytics(self) -> None:
        result = _classify_by_purpose(_partner("A", "analytics"), "analytics")
        assert result is not None
        assert result.risk_level == "medium"
        assert result.category == "analytics"

    def test_fraud_prevention(self) -> None:
        result = _classify_by_purpose(_partner("F", "fraud"), "fraud")
        assert result is not None
        assert result.risk_level == "low"
        assert result.category == "fraud-prevention"

    def test_content_delivery(self) -> None:
        result = _classify_by_purpose(_partner("C", "cdn"), "cdn")
        assert result is not None
        assert result.risk_level == "low"
        assert result.category == "content-delivery"

    def test_unknown_purpose_returns_none(self) -> None:
        assert _classify_by_purpose(_partner("X", "something"), "something") is None


# ── classify_partner_by_pattern_sync ──────────────────────────


class TestClassifyPartnerByPatternSync:
    def test_unknown_partner_with_purpose(self) -> None:
        """Unknown partner with advertising purpose → medium / advertising."""
        p = _partner("Totally Unknown Corp", "advertising and marketing")
        result = classify_partner_by_pattern_sync(p)
        assert result is not None
        assert result.risk_level == "medium"

    def test_completely_unknown(self) -> None:
        """Partner with no matching database or purpose → None."""
        p = _partner("ZzzUnknownPartnerXyz", "widgets")
        result = classify_partner_by_pattern_sync(p)
        assert result is None


# ── get_partner_risk_summary ──────────────────────────────────


class TestGetPartnerRiskSummary:
    def test_empty_list(self) -> None:
        summary = get_partner_risk_summary([])
        assert isinstance(summary, partners.PartnerRiskSummary)
        assert summary.critical_count == 0
        assert summary.high_count == 0
        assert summary.total_risk_score == 0
        assert summary.worst_partners == []

    def test_unknown_partners_get_default_score(self) -> None:
        """Partners that can't be classified get default risk score of 3."""
        ps = [_partner("Mystery Corp", "widgets")]
        summary = get_partner_risk_summary(ps)
        assert summary.total_risk_score == 3

    def test_mixed_partners(self) -> None:
        """List with known purpose results in nonzero totals."""
        ps = [
            _partner("Ads Inc", "advertising and marketing"),
            _partner("Fraud Guard", "fraud prevention"),
        ]
        summary = get_partner_risk_summary(ps)
        assert summary.total_risk_score > 0

    def test_worst_partners_limited(self) -> None:
        """worst_partners list should not grow unbounded."""
        ps = [_partner(f"HighRisk-{i}", "cross-site tracking") for i in range(10)]
        summary = get_partner_risk_summary(ps)
        assert len(summary.worst_partners) <= 5
