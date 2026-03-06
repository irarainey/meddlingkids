"""Tests for src.models.report — structured report Pydantic models."""

from __future__ import annotations

from src.models.report import (
    DataCollectionItem,
    NamedEntity,
    ThirdPartyGroup,
    TrackerEntry,
    _coerce_named_entities,
)


class TestNamedEntity:
    """Tests for the NamedEntity model."""

    def test_basic_creation(self) -> None:
        entity = NamedEntity(name="Google")
        assert entity.name == "Google"
        assert entity.url == ""

    def test_with_url(self) -> None:
        entity = NamedEntity(name="Google", url="https://google.com")
        assert entity.url == "https://google.com"

    def test_camel_case_alias(self) -> None:
        entity = NamedEntity(name="Test")
        dumped = entity.model_dump(by_alias=True)
        assert "name" in dumped


class TestCoerceNamedEntities:
    """Tests for _coerce_named_entities()."""

    def test_plain_strings(self) -> None:
        result = _coerce_named_entities(["Google", "Facebook"])
        assert len(result) == 2
        assert result[0].name == "Google"

    def test_dicts(self) -> None:
        result = _coerce_named_entities([{"name": "Google", "url": "https://google.com"}])
        assert result[0].name == "Google"
        assert result[0].url == "https://google.com"

    def test_named_entities_passthrough(self) -> None:
        entities: list[str | dict[str, str] | NamedEntity] = [NamedEntity(name="Google")]
        result = _coerce_named_entities(entities)
        assert result[0].name == "Google"

    def test_mixed_types(self) -> None:
        result = _coerce_named_entities(
            [
                "Google",
                {"name": "Facebook"},
                NamedEntity(name="Twitter"),
            ]
        )
        assert len(result) == 3

    def test_other_types_stringified(self) -> None:
        result = _coerce_named_entities([42])  # type: ignore[list-item]
        assert result[0].name == "42"


class TestDataCollectionItem:
    """Tests for DataCollectionItem canonical risk enforcement."""

    def test_canonical_risk_override(self) -> None:
        item = DataCollectionItem(
            category="Browsing Behaviour",
            details=["page views"],
            risk="critical",  # LLM overestimated
        )
        assert item.risk == "medium"
        assert item.sensitive is False

    def test_canonical_health_risk(self) -> None:
        item = DataCollectionItem(
            category="Health & Wellness",
            details=["health data"],
            risk="low",  # LLM underestimated
        )
        assert item.risk == "critical"
        assert item.sensitive is True

    def test_canonical_financial_risk(self) -> None:
        item = DataCollectionItem(
            category="Financial / Payment",
            details=["card details"],
            risk="low",
        )
        assert item.risk == "critical"
        assert item.sensitive is True

    def test_unknown_category_critical_downgraded_without_sensitive(self) -> None:
        item = DataCollectionItem(
            category="Custom Category",
            details=["custom data"],
            risk="critical",
            sensitive=False,
        )
        assert item.risk == "high"

    def test_unknown_category_critical_with_sensitive(self) -> None:
        item = DataCollectionItem(
            category="Custom Category",
            details=["custom data"],
            risk="critical",
            sensitive=True,
        )
        assert item.risk == "critical"

    def test_shared_with_coercion(self) -> None:
        item = DataCollectionItem(
            category="Analytics",
            details=["page views"],
            risk="low",
            shared_with=["Google", "Facebook"],  # type: ignore[list-item]
        )
        assert len(item.shared_with) == 2
        assert item.shared_with[0].name == "Google"


class TestTrackerEntry:
    """Tests for TrackerEntry model."""

    def test_basic_tracker(self) -> None:
        entry = TrackerEntry(
            name="Google Analytics",
            domains=["analytics.google.com"],
            purpose="Analytics",
        )
        assert entry.name == "Google Analytics"
        assert entry.cookies == []
        assert entry.storage_keys == []

    def test_camel_case_serialization(self) -> None:
        entry = TrackerEntry(
            name="Test",
            domains=["test.com"],
            storage_keys=["_ga"],
            purpose="Analytics",
        )
        dumped = entry.model_dump(by_alias=True)
        assert "storageKeys" in dumped


class TestThirdPartyGroup:
    """Tests for ThirdPartyGroup service coercion."""

    def test_services_coerced_from_strings(self) -> None:
        group = ThirdPartyGroup(
            category="Advertising",
            services=["Google Ads", "Facebook Ads"],  # type: ignore[list-item]
            privacy_impact="High",
        )
        assert len(group.services) == 2
        assert group.services[0].name == "Google Ads"
