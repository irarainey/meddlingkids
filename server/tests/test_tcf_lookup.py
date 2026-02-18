"""Tests for the TCF purpose matching service."""

from __future__ import annotations

from src.analysis import tcf_lookup


class TestMatchPurpose:
    """Tests for individual purpose string matching."""

    def test_exact_match_purpose_1(self) -> None:
        result = tcf_lookup._match_purpose("Store and/or access information on a device")
        assert result is not None
        assert result.id == 1
        assert result.category == "purpose"
        assert result.risk_level == "low"

    def test_exact_match_purpose_3(self) -> None:
        result = tcf_lookup._match_purpose("Create profiles for personalised advertising")
        assert result is not None
        assert result.id == 3
        assert result.category == "purpose"
        assert result.risk_level == "high"

    def test_exact_match_purpose_7(self) -> None:
        result = tcf_lookup._match_purpose("Measure advertising performance")
        assert result is not None
        assert result.id == 7
        assert result.category == "purpose"

    def test_exact_match_purpose_11(self) -> None:
        result = tcf_lookup._match_purpose("Use limited data to select content")
        assert result is not None
        assert result.id == 11
        assert result.category == "purpose"

    def test_match_special_purpose(self) -> None:
        result = tcf_lookup._match_purpose("Ensure security, prevent and detect fraud, and fix errors")
        assert result is not None
        assert result.id == 1
        assert result.category == "special-purpose"
        assert result.risk_level == "low"

    def test_match_feature(self) -> None:
        result = tcf_lookup._match_purpose("Match and combine data from other data sources")
        assert result is not None
        assert result.id == 1
        assert result.category == "feature"
        assert result.risk_level == "high"

    def test_match_special_feature_geolocation(self) -> None:
        result = tcf_lookup._match_purpose("Use precise geolocation data")
        assert result is not None
        assert result.id == 1
        assert result.category == "special-feature"
        assert result.risk_level == "critical"

    def test_match_special_feature_fingerprinting(self) -> None:
        result = tcf_lookup._match_purpose("Actively scan device characteristics for identification")
        assert result is not None
        assert result.id == 2
        assert result.category == "special-feature"
        assert result.risk_level == "critical"

    def test_case_insensitive(self) -> None:
        result = tcf_lookup._match_purpose("MEASURE ADVERTISING PERFORMANCE")
        assert result is not None
        assert result.id == 7

    def test_substring_match_purpose_in_longer_text(self) -> None:
        result = tcf_lookup._match_purpose("Purpose 3: Create profiles for personalised advertising")
        assert result is not None
        assert result.id == 3

    def test_no_match_random_text(self) -> None:
        result = tcf_lookup._match_purpose("completely unrelated text about weather")
        assert result is None

    def test_no_match_empty_string(self) -> None:
        result = tcf_lookup._match_purpose("")
        assert result is None

    def test_no_match_short_ambiguous(self) -> None:
        """Short strings should not match via reverse containment."""
        result = tcf_lookup._match_purpose("data")
        assert result is None


class TestLookupPurposes:
    """Tests for the full purpose list lookup."""

    def test_empty_list(self) -> None:
        result = tcf_lookup.lookup_purposes([])
        assert result.matched == []
        assert result.unmatched == []

    def test_all_match(self) -> None:
        purposes = [
            "Store and/or access information on a device",
            "Create profiles for personalised advertising",
            "Measure content performance",
        ]
        result = tcf_lookup.lookup_purposes(purposes)
        assert len(result.matched) == 3
        assert len(result.unmatched) == 0
        assert result.matched[0].id == 1
        assert result.matched[1].id == 3
        assert result.matched[2].id == 8

    def test_mixed_match_and_unmatched(self) -> None:
        purposes = [
            "Store and/or access information on a device",
            "Custom site analytics",
            "Measure advertising performance",
        ]
        result = tcf_lookup.lookup_purposes(purposes)
        assert len(result.matched) == 2
        assert len(result.unmatched) == 1
        assert result.unmatched[0] == "Custom site analytics"

    def test_deduplication(self) -> None:
        """Duplicate purpose strings should produce a single match."""
        purposes = [
            "Store and/or access information on a device",
            "Store and/or access information on a device",
        ]
        result = tcf_lookup.lookup_purposes(purposes)
        assert len(result.matched) == 1
        assert result.matched[0].id == 1

    def test_sort_order_categories(self) -> None:
        """Purposes should sort with standard purposes first, then special."""
        purposes = [
            "Use precise geolocation data",
            "Store and/or access information on a device",
            "Match and combine data from other data sources",
            "Ensure security, prevent and detect fraud, and fix errors",
        ]
        result = tcf_lookup.lookup_purposes(purposes)
        assert len(result.matched) == 4
        assert result.matched[0].category == "purpose"
        assert result.matched[1].category == "special-purpose"
        assert result.matched[2].category == "feature"
        assert result.matched[3].category == "special-feature"

    def test_all_11_standard_purposes(self) -> None:
        """All 11 standard TCF v2.2 purposes should match."""
        purposes = [
            "Store and/or access information on a device",
            "Use limited data to select advertising",
            "Create profiles for personalised advertising",
            "Use profiles to select personalised advertising",
            "Create profiles to personalise content",
            "Use profiles to select personalised content",
            "Measure advertising performance",
            "Measure content performance",
            "Understand audiences through statistics or combinations of data from different sources",
            "Develop and improve services",
            "Use limited data to select content",
        ]
        result = tcf_lookup.lookup_purposes(purposes)
        assert len(result.matched) == 11
        assert len(result.unmatched) == 0
        ids = [m.id for m in result.matched]
        assert ids == list(range(1, 12))

    def test_lawful_bases_populated(self) -> None:
        result = tcf_lookup.lookup_purposes(["Develop and improve services"])
        assert len(result.matched) == 1
        purpose = result.matched[0]
        assert "consent" in purpose.lawful_bases
        assert "legitimate_interest" in purpose.lawful_bases

    def test_notes_populated(self) -> None:
        result = tcf_lookup.lookup_purposes(["Create profiles for personalised advertising"])
        assert len(result.matched) == 1
        assert "profile" in result.matched[0].notes.lower()


class TestTcfPurposeMatch:
    """Tests for the TcfPurposeMatch model serialisation."""

    def test_camel_case_serialisation(self) -> None:
        match = tcf_lookup.TcfPurposeMatch(
            id=1,
            name="Test",
            description="Test description",
            risk_level="low",
            lawful_bases=["consent"],
            notes="Test notes",
            category="purpose",
        )
        data = match.model_dump(by_alias=True)
        assert "riskLevel" in data
        assert "lawfulBases" in data
        assert "risk_level" not in data

    def test_lookup_result_camel_case(self) -> None:
        result = tcf_lookup.lookup_purposes(["Store and/or access information on a device"])
        data = result.model_dump(by_alias=True)
        assert "matched" in data
        assert "unmatched" in data
        assert data["matched"][0]["riskLevel"] == "low"
