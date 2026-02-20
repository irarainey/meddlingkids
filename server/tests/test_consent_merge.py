"""Tests for _merge_results in consent_extraction_agent."""

from __future__ import annotations

from src.agents import consent_extraction_agent
from src.models import consent


def _make_details(
    *,
    purposes: list[str] | None = None,
    categories: list[consent.ConsentCategory] | None = None,
    partners: list[consent.ConsentPartner] | None = None,
    has_manage_options: bool = False,
    claimed_partner_count: int | None = None,
    consent_platform: str | None = None,
) -> consent.ConsentDetails:
    """Helper to build a ConsentDetails with defaults."""
    return consent.ConsentDetails(
        has_manage_options=has_manage_options,
        categories=categories or [],
        partners=partners or [],
        purposes=purposes or [],
        raw_text="test",
        claimed_partner_count=claimed_partner_count,
        consent_platform=consent_platform,
    )


class TestMergeResults:
    """Tests for the _merge_results union logic."""

    def test_llm_only_purposes_preserved(self) -> None:
        llm = _make_details(purposes=["Purpose A", "Purpose B"])
        local = _make_details()
        result = consent_extraction_agent._merge_results(llm, local)
        assert result.purposes == ["Purpose A", "Purpose B"]

    def test_local_only_purposes_preserved(self) -> None:
        llm = _make_details()
        local = _make_details(purposes=["Purpose A", "Purpose B"])
        result = consent_extraction_agent._merge_results(llm, local)
        assert result.purposes == ["Purpose A", "Purpose B"]

    def test_union_deduplicates_purposes_case_insensitive(self) -> None:
        llm = _make_details(purposes=["Measure advertising performance"])
        local = _make_details(purposes=["measure advertising performance", "Understand audiences through statistics"])
        result = consent_extraction_agent._merge_results(llm, local)
        assert len(result.purposes) == 2
        # LLM version kept (first occurrence wins)
        assert result.purposes[0] == "Measure advertising performance"
        assert result.purposes[1] == "Understand audiences through statistics"

    def test_union_categories(self) -> None:
        cat_a = consent.ConsentCategory(name="Analytics", description="Desc A", required=False)
        cat_b = consent.ConsentCategory(name="Performance", description="Desc B", required=False)
        cat_c = consent.ConsentCategory(name="Functional", description="Desc C", required=False)
        llm = _make_details(categories=[cat_a, cat_b])
        local = _make_details(categories=[cat_b, cat_c])  # Performance is a dupe
        result = consent_extraction_agent._merge_results(llm, local)
        names = [c.name for c in result.categories]
        assert names == ["Analytics", "Performance", "Functional"]

    def test_categories_dedup_case_insensitive(self) -> None:
        cat_llm = consent.ConsentCategory(name="analytics", description="llm", required=False)
        cat_local = consent.ConsentCategory(name="Analytics", description="local", required=False)
        result = consent_extraction_agent._merge_results(
            _make_details(categories=[cat_llm]),
            _make_details(categories=[cat_local]),
        )
        assert len(result.categories) == 1
        # LLM version kept
        assert result.categories[0].description == "llm"

    def test_partners_from_llm_only(self) -> None:
        llm_partner = consent.ConsentPartner(name="Google", purpose="Ads", data_collected=[])
        local_partner = consent.ConsentPartner(name="Facebook", purpose="Social", data_collected=[])
        result = consent_extraction_agent._merge_results(
            _make_details(partners=[llm_partner]),
            _make_details(partners=[local_partner]),
        )
        assert len(result.partners) == 1
        assert result.partners[0].name == "Google"

    def test_has_manage_options_ored(self) -> None:
        result = consent_extraction_agent._merge_results(
            _make_details(has_manage_options=False),
            _make_details(has_manage_options=True),
        )
        assert result.has_manage_options is True

        result2 = consent_extraction_agent._merge_results(
            _make_details(has_manage_options=True),
            _make_details(has_manage_options=False),
        )
        assert result2.has_manage_options is True

    def test_claimed_partner_count_fallback(self) -> None:
        result = consent_extraction_agent._merge_results(
            _make_details(claimed_partner_count=None),
            _make_details(claimed_partner_count=842),
        )
        assert result.claimed_partner_count == 842

    def test_claimed_partner_count_llm_preferred(self) -> None:
        result = consent_extraction_agent._merge_results(
            _make_details(claimed_partner_count=100),
            _make_details(claimed_partner_count=842),
        )
        assert result.claimed_partner_count == 100

    def test_consent_platform_from_llm(self) -> None:
        result = consent_extraction_agent._merge_results(
            _make_details(consent_platform="OneTrust"),
            _make_details(),
        )
        assert result.consent_platform == "OneTrust"

    def test_raw_text_from_llm(self) -> None:
        _ = _make_details()
        llm_raw = consent.ConsentDetails(
            has_manage_options=False,
            categories=[],
            partners=[],
            purposes=[],
            raw_text="LLM extracted text",
            claimed_partner_count=None,
        )
        local = _make_details()
        result = consent_extraction_agent._merge_results(llm_raw, local)
        assert result.raw_text == "LLM extracted text"

    def test_full_union_scenario(self) -> None:
        """Realistic scenario: LLM found some purposes, local parser found others."""
        llm = _make_details(
            purposes=["Store and/or access information on a device", "Measure advertising performance"],
            categories=[consent.ConsentCategory(name="Targeting / Advertising", description="LLM", required=False)],
            has_manage_options=True,
            claimed_partner_count=842,
        )
        local = _make_details(
            purposes=[
                "Store and/or access information on a device",  # duplicate
                "Understand audiences through statistics",  # new
                "Develop and improve products",  # new
            ],
            categories=[
                consent.ConsentCategory(name="Targeting / Advertising", description="Local", required=False),  # duplicate
                consent.ConsentCategory(name="Analytics", description="Local", required=False),  # new
            ],
            has_manage_options=False,
            claimed_partner_count=200,
        )
        result = consent_extraction_agent._merge_results(llm, local)
        assert len(result.purposes) == 4
        assert len(result.categories) == 2
        assert result.has_manage_options is True
        assert result.claimed_partner_count == 842
