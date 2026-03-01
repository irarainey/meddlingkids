"""Tests for TC String consent validation.

Validates cross-referencing of decoded TC String data against
consent dialog text, detection of undisclosed purposes,
LI misuse, special features, and vendor count discrepancies.
"""

from __future__ import annotations

from src.analysis.tc_validation import (
    TcValidationFinding,
    validate_tc_consent,
)

# ====================================================================
# Fixtures — reusable TC String data dicts
# ====================================================================


def _make_tc_data(
    *,
    purpose_consents: list[int] | None = None,
    purpose_lis: list[int] | None = None,
    special_features: list[int] | None = None,
    vendor_consent_count: int = 0,
    vendor_li_count: int = 0,
) -> dict[str, object]:
    """Build a minimal TC String data dict for testing."""
    return {
        "version": 2,
        "created": "2025-01-01T00:00:00+00:00",
        "lastUpdated": "2025-01-01T00:00:00+00:00",
        "cmpId": 300,
        "cmpVersion": 1,
        "consentScreen": 1,
        "consentLanguage": "EN",
        "vendorListVersion": 100,
        "tcfPolicyVersion": 4,
        "isServiceSpecific": False,
        "useNonStandardStacks": False,
        "publisherCountryCode": "GB",
        "purposeConsents": purpose_consents or [],
        "purposeLegitimateInterests": purpose_lis or [],
        "specialFeatureOptIns": special_features or [],
        "vendorConsents": list(range(1, (vendor_consent_count or 0) + 1)),
        "vendorLegitimateInterests": list(
            range(1, (vendor_li_count or 0) + 1),
        ),
        "vendorConsentCount": vendor_consent_count or 0,
        "vendorLiCount": vendor_li_count or 0,
        "totalPurposesConsented": len(purpose_consents or []),
        "rawString": "test-tc-string",
    }


# ====================================================================
# Basic validation
# ====================================================================


class TestValidateTcConsent:
    """Core validation logic tests."""

    def test_all_purposes_shown_no_findings_for_undisclosed(
        self,
    ) -> None:
        """No undisclosed-purpose findings when dialog matches TC."""
        tc_data = _make_tc_data(purpose_consents=[1, 2, 3])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[
                "Store and/or access information on a device",
                "Use limited data to select advertising",
                "Create profiles for personalised advertising",
            ],
            matched_purpose_ids={1, 2, 3},
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert undisclosed == []

    def test_purpose_signals_cover_all_11(self) -> None:
        """Purpose signals include all 11 TCF purposes."""
        tc_data = _make_tc_data(purpose_consents=[1])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        ids = {ps.id for ps in result.purpose_signals}
        assert ids == set(range(1, 12))

    def test_purpose_signal_consent_flag(self) -> None:
        """Purpose signals correctly mark consented purposes."""
        tc_data = _make_tc_data(purpose_consents=[1, 3, 7])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        consented_ids = {ps.id for ps in result.purpose_signals if ps.consented}
        assert consented_ids == {1, 3, 7}

    def test_purpose_signal_li_flag(self) -> None:
        """Purpose signals correctly mark LI purposes."""
        tc_data = _make_tc_data(purpose_lis=[2, 7, 9])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        li_ids = {ps.id for ps in result.purpose_signals if ps.legitimate_interest}
        assert li_ids == {2, 7, 9}

    def test_purpose_signal_disclosed_flag(self) -> None:
        """Purpose signals mark disclosure status correctly."""
        tc_data = _make_tc_data(purpose_consents=[1, 2, 3])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["Store and/or access information on a device"],
            matched_purpose_ids={1},
        )
        p1 = next(ps for ps in result.purpose_signals if ps.id == 1)
        p2 = next(ps for ps in result.purpose_signals if ps.id == 2)
        assert p1.disclosed_in_dialog is True
        assert p2.disclosed_in_dialog is False


# ====================================================================
# Undisclosed purpose detection
# ====================================================================


class TestUndisclosedPurposes:
    """Tests for detecting undisclosed TC String purposes."""

    def test_detects_undisclosed_purpose(self) -> None:
        """Flags purposes consented in TC but not shown in dialog."""
        tc_data = _make_tc_data(purpose_consents=[1, 2, 3, 4])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["Store and/or access information on a device"],
            matched_purpose_ids={1},
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        # Purposes 2, 3, 4 are undisclosed
        assert len(undisclosed) == 3
        titles = {f.title for f in undisclosed}
        assert "Purpose not matched to dialog: Use limited data to select advertising" in titles
        assert "Purpose not matched to dialog: Create profiles for personalised advertising" in titles

    def test_li_only_purpose_flagged_as_undisclosed(self) -> None:
        """Purposes with only LI (no consent) are still flagged."""
        tc_data = _make_tc_data(purpose_lis=[7])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["Store and/or access information on a device"],
            matched_purpose_ids={1},
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert len(undisclosed) == 1
        assert "Measure advertising performance" in undisclosed[0].title

    def test_no_undisclosed_when_no_dialog_purposes(self) -> None:
        """No undisclosed findings when dialog purposes is empty.

        If the dialog has no purposes, we can't determine
        whether purposes were properly disclosed.
        """
        tc_data = _make_tc_data(purpose_consents=[1, 2, 3])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert undisclosed == []

    def test_high_risk_undisclosed_is_high_severity(self) -> None:
        """Undisclosed high-risk purpose gets high severity."""
        tc_data = _make_tc_data(purpose_consents=[3])  # high risk
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["Store and/or access information on a device"],
            matched_purpose_ids={1},
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert len(undisclosed) == 1
        assert undisclosed[0].severity == "high"

    def test_low_risk_undisclosed_is_moderate_severity(self) -> None:
        """Undisclosed low-risk purpose gets moderate severity."""
        tc_data = _make_tc_data(purpose_consents=[8])  # low risk
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["Store and/or access information on a device"],
            matched_purpose_ids={1},
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert len(undisclosed) == 1
        assert undisclosed[0].severity == "moderate"


# ====================================================================
# Legitimate interest misuse
# ====================================================================


class TestLiMisuse:
    """Tests for detecting LI on consent-only purposes."""

    def test_li_on_consent_only_purpose_flagged(self) -> None:
        """Purposes 3, 4, 5, 6 with LI are flagged as misuse."""
        tc_data = _make_tc_data(purpose_lis=[3, 4])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        li_findings = [f for f in result.findings if f.category == "li-misuse"]
        assert len(li_findings) == 2
        assert all(f.severity == "high" for f in li_findings)

    def test_li_on_allowed_purpose_not_flagged(self) -> None:
        """Purposes that allow LI (e.g. 2, 7, 8) are not flagged."""
        tc_data = _make_tc_data(purpose_lis=[2, 7, 8, 9, 10])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        li_findings = [f for f in result.findings if f.category == "li-misuse"]
        assert li_findings == []

    def test_li_on_purpose_5_and_6_flagged(self) -> None:
        """Purposes 5 (content profiles) and 6 also require consent."""
        tc_data = _make_tc_data(purpose_lis=[5, 6])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        li_findings = [f for f in result.findings if f.category == "li-misuse"]
        assert len(li_findings) == 2


# ====================================================================
# Special features
# ====================================================================


class TestSpecialFeatures:
    """Tests for special feature opt-in detection."""

    def test_geolocation_flagged(self) -> None:
        """Special feature 1 (geolocation) is critical severity."""
        tc_data = _make_tc_data(special_features=[1])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        sf_findings = [f for f in result.findings if f.category == "special-feature"]
        assert len(sf_findings) == 1
        assert sf_findings[0].severity == "critical"
        assert "geolocation" in sf_findings[0].title.lower()
        assert result.special_features == [
            "Use precise geolocation data",
        ]

    def test_fingerprinting_flagged(self) -> None:
        """Special feature 2 (fingerprinting) is high severity."""
        tc_data = _make_tc_data(special_features=[2])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        sf_findings = [f for f in result.findings if f.category == "special-feature"]
        assert len(sf_findings) == 1
        assert sf_findings[0].severity == "high"
        assert "fingerprinting" in sf_findings[0].detail.lower()

    def test_both_special_features(self) -> None:
        """Both special features produce separate findings."""
        tc_data = _make_tc_data(special_features=[1, 2])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        sf_findings = [f for f in result.findings if f.category == "special-feature"]
        assert len(sf_findings) == 2
        assert len(result.special_features) == 2

    def test_no_special_features(self) -> None:
        """No special feature findings when none are opted in."""
        tc_data = _make_tc_data(special_features=[])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        sf_findings = [f for f in result.findings if f.category == "special-feature"]
        assert sf_findings == []
        assert result.special_features == []


# ====================================================================
# Vendor count comparison
# ====================================================================


class TestVendorCountComparison:
    """Tests for vendor count mismatch detection."""

    def test_significant_mismatch_flagged(self) -> None:
        """Large discrepancy between claimed and actual is flagged."""
        tc_data = _make_tc_data(vendor_consent_count=500)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=200,
        )
        assert result.vendor_count_mismatch is True
        vc_findings = [f for f in result.findings if f.category == "vendor-count"]
        assert len(vc_findings) == 1
        assert vc_findings[0].severity == "info"

    def test_small_mismatch_not_flagged(self) -> None:
        """Small discrepancy (<20% and <10) is not flagged."""
        tc_data = _make_tc_data(vendor_consent_count=205)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=200,
        )
        assert result.vendor_count_mismatch is False

    def test_fewer_vendors_in_tc_flagged(self) -> None:
        """Fewer vendors in TC String than claimed is info-level."""
        tc_data = _make_tc_data(vendor_consent_count=100)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=500,
        )
        vc_findings = [f for f in result.findings if f.category == "vendor-count"]
        assert len(vc_findings) == 1
        assert vc_findings[0].severity == "info"

    def test_no_claimed_count_skips_check(self) -> None:
        """No vendor count finding when claimed count is None."""
        tc_data = _make_tc_data(vendor_consent_count=500)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=None,
        )
        vc_findings = [f for f in result.findings if f.category == "vendor-count"]
        assert vc_findings == []

    def test_vendor_counts_in_result(self) -> None:
        """Result carries vendor consent and LI counts."""
        tc_data = _make_tc_data(
            vendor_consent_count=400,
            vendor_li_count=150,
        )
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=400,
        )
        assert result.vendor_consent_count == 400
        assert result.vendor_li_count == 150
        assert result.claimed_partner_count == 400

    def test_ac_vendor_count_stored(self) -> None:
        """AC vendor count is carried through to the result."""
        tc_data = _make_tc_data(vendor_consent_count=100)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            ac_vendor_count=50,
        )
        assert result.ac_vendor_count == 50

    def test_ac_vendor_count_none_by_default(self) -> None:
        """AC vendor count defaults to None when not provided."""
        tc_data = _make_tc_data(vendor_consent_count=100)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        assert result.ac_vendor_count is None

    def test_ac_vendor_count_in_mismatch_detail(self) -> None:
        """When AC vendors exist, the mismatch detail mentions them."""
        tc_data = _make_tc_data(vendor_consent_count=100)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=500,
            ac_vendor_count=200,
        )
        vc_findings = [f for f in result.findings if f.category == "vendor-count"]
        assert len(vc_findings) == 1
        assert "200 non-IAB vendor" in vc_findings[0].detail
        assert "Additional Consent Mode" in vc_findings[0].detail
        # Combined total = 100 + 200 = 300
        assert "300" in vc_findings[0].detail

    def test_ac_vendor_zero_not_mentioned(self) -> None:
        """AC vendor count of 0 is not mentioned in finding detail."""
        tc_data = _make_tc_data(vendor_consent_count=100)
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            claimed_partner_count=500,
            ac_vendor_count=0,
        )
        vc_findings = [f for f in result.findings if f.category == "vendor-count"]
        assert len(vc_findings) == 1
        assert "Additional Consent Mode (AC String)" not in vc_findings[0].detail


# ====================================================================
# High-risk purpose consolidation
# ====================================================================


class TestHighRiskPurposes:
    """Tests for high-risk purpose finding."""

    def test_high_risk_purposes_consolidated(self) -> None:
        """Consented high-risk purposes produce a summary finding."""
        tc_data = _make_tc_data(purpose_consents=[3, 4])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        hr_findings = [f for f in result.findings if f.category == "high-risk-consent"]
        assert len(hr_findings) == 1
        assert "2 high-risk purposes" in hr_findings[0].title

    def test_no_high_risk_no_finding(self) -> None:
        """No high-risk finding when only low/medium purposes."""
        tc_data = _make_tc_data(purpose_consents=[1, 8, 11])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        hr_findings = [f for f in result.findings if f.category == "high-risk-consent"]
        assert hr_findings == []


# ====================================================================
# Finding ordering
# ====================================================================


class TestFindingOrdering:
    """Tests for finding severity sort order."""

    def test_findings_sorted_by_severity(self) -> None:
        """Findings are returned in severity order (critical first)."""
        tc_data = _make_tc_data(
            purpose_consents=[1, 2, 3, 4],
            purpose_lis=[3],
            special_features=[1],
            vendor_consent_count=500,
        )
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[
                "Store and/or access information on a device",
            ],
            matched_purpose_ids={1},
            claimed_partner_count=200,
        )
        severities = [f.severity for f in result.findings]
        severity_order = {
            "critical": 0,
            "high": 1,
            "moderate": 2,
            "info": 3,
        }
        order_values = [severity_order[s] for s in severities]
        assert order_values == sorted(order_values)


# ====================================================================
# Serialization
# ====================================================================


class TestSerialization:
    """Tests for model serialization with camelCase aliases."""

    def test_validation_result_camel_case(self) -> None:
        """Validation result serializes to camelCase."""
        tc_data = _make_tc_data(purpose_consents=[1])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        data = result.model_dump(by_alias=True)
        assert "purposeSignals" in data
        assert "vendorConsentCount" in data
        assert "vendorLiCount" in data
        assert "claimedPartnerCount" in data
        assert "vendorCountMismatch" in data
        assert "specialFeatures" in data

    def test_purpose_signal_camel_case(self) -> None:
        """Purpose signals serialize with camelCase keys."""
        tc_data = _make_tc_data(purpose_consents=[1])
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        ps_data = result.purpose_signals[0].model_dump(by_alias=True)
        assert "riskLevel" in ps_data
        assert "disclosedInDialog" in ps_data
        assert "legitimateInterest" in ps_data

    def test_finding_camel_case(self) -> None:
        """Findings serialize with camelCase keys."""
        finding = TcValidationFinding(
            severity="high",
            category="test",
            title="Test finding",
            detail="Details here",
        )
        data = finding.model_dump(by_alias=True)
        assert "severity" in data
        assert "category" in data
        assert "title" in data
        assert "detail" in data


# ====================================================================
# Edge cases
# ====================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_tc_data(self) -> None:
        """Handles TC data with empty purpose lists."""
        tc_data = _make_tc_data()
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        assert len(result.purpose_signals) == 11
        assert all(not ps.consented for ps in result.purpose_signals)
        assert result.findings == []

    def test_all_purposes_consented_and_disclosed(self) -> None:
        """Full consent + disclosure: only high-risk summary finding."""
        tc_data = _make_tc_data(
            purpose_consents=list(range(1, 12)),
        )
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=["dummy"],
            matched_purpose_ids=set(range(1, 12)),
        )
        undisclosed = [f for f in result.findings if f.category == "undisclosed-purpose"]
        assert undisclosed == []
        # Should have high-risk finding for purposes 3, 4
        hr = [f for f in result.findings if f.category == "high-risk-consent"]
        assert len(hr) == 1

    def test_combined_consent_and_li_purpose(self) -> None:
        """Purpose with both consent and LI is correctly signalled."""
        tc_data = _make_tc_data(
            purpose_consents=[7],
            purpose_lis=[7],
        )
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
        )
        p7 = next(ps for ps in result.purpose_signals if ps.id == 7)
        assert p7.consented is True
        assert p7.legitimate_interest is True


# ====================================================================
# CMP ID cross-validation
# ====================================================================


class TestCmpIdCrossValidation:
    """Verify CMP ID mismatch detection between TC String and detected CMP."""

    def test_no_detected_cmp_id_no_finding(self) -> None:
        """When the CMP was not identified, no CMP ID finding is produced."""
        tc_data = _make_tc_data()
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            detected_cmp_id=None,
        )
        cmp_findings = [f for f in result.findings if f.category == "cmp-id-mismatch"]
        assert cmp_findings == []

    def test_matching_cmp_id_no_finding(self) -> None:
        """When the TC String cmpId matches the detected CMP, no finding."""
        tc_data = _make_tc_data()  # cmpId=300 by default
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            detected_cmp_id=300,
        )
        cmp_findings = [f for f in result.findings if f.category == "cmp-id-mismatch"]
        assert cmp_findings == []

    def test_mismatched_cmp_id_produces_finding(self) -> None:
        """When the TC String cmpId differs from detected CMP, an info finding is raised."""
        tc_data = _make_tc_data()  # cmpId=300
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            detected_cmp_id=28,  # OneTrust
        )
        cmp_findings = [f for f in result.findings if f.category == "cmp-id-mismatch"]
        assert len(cmp_findings) == 1
        finding = cmp_findings[0]
        assert finding.severity == "info"
        assert "300" in finding.detail
        assert "28" in finding.detail

    def test_missing_cmp_id_in_tc_data_no_finding(self) -> None:
        """When TC data has no cmpId field, no mismatch finding."""
        tc_data = _make_tc_data()
        del tc_data["cmpId"]
        result = validate_tc_consent(
            tc_string_data=tc_data,
            dialog_purposes=[],
            matched_purpose_ids=set(),
            detected_cmp_id=28,
        )
        cmp_findings = [f for f in result.findings if f.category == "cmp-id-mismatch"]
        assert cmp_findings == []
