"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from src.models import analysis, consent, tracking_data

# ── Tracking Data Factories ─────────────────────────────────────


@pytest.fixture()
def sample_cookie() -> tracking_data.TrackedCookie:
    """A basic first-party cookie."""
    return tracking_data.TrackedCookie(
        name="session_id",
        value="abc123",
        domain="example.com",
        path="/",
        expires=0,
        http_only=True,
        secure=True,
        same_site="Lax",
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def tracking_cookie() -> tracking_data.TrackedCookie:
    """A known Google Analytics tracking cookie."""
    return tracking_data.TrackedCookie(
        name="_ga",
        value="GA1.2.123456789.1234567890",
        domain=".example.com",
        path="/",
        expires=1893456000,
        http_only=False,
        secure=False,
        same_site="None",
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def sample_script() -> tracking_data.TrackedScript:
    """A basic first-party script."""
    return tracking_data.TrackedScript(
        url="https://example.com/js/app.js",
        domain="example.com",
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def tracking_script() -> tracking_data.TrackedScript:
    """A known Google Analytics tracking script."""
    return tracking_data.TrackedScript(
        url="https://www.google-analytics.com/analytics.js",
        domain="www.google-analytics.com",
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def sample_network_request() -> tracking_data.NetworkRequest:
    """A first-party network request."""
    return tracking_data.NetworkRequest(
        url="https://example.com/api/data",
        domain="example.com",
        method="GET",
        resource_type="xhr",
        is_third_party=False,
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def third_party_request() -> tracking_data.NetworkRequest:
    """A third-party ad network request."""
    return tracking_data.NetworkRequest(
        url="https://doubleclick.net/pixel",
        domain="doubleclick.net",
        method="GET",
        resource_type="image",
        is_third_party=True,
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def sample_storage_item() -> tracking_data.StorageItem:
    """A basic storage item."""
    return tracking_data.StorageItem(
        key="theme",
        value="dark",
        timestamp="2026-01-01T00:00:00Z",
    )


@pytest.fixture()
def empty_storage() -> dict[str, list[tracking_data.StorageItem]]:
    """Empty storage dict matching the pipeline convention."""
    return {"local_storage": [], "session_storage": []}


# ── Consent Fixtures ────────────────────────────────────────────


@pytest.fixture()
def sample_consent_details() -> consent.ConsentDetails:
    """Populated consent details for testing."""
    return consent.ConsentDetails(
        has_manage_options=True,
        categories=[
            consent.ConsentCategory(
                name="Functional",
                description="Required for the site to work",
                required=True,
            ),
            consent.ConsentCategory(
                name="Analytics",
                description="Help us understand usage",
                required=False,
            ),
        ],
        partners=[
            consent.ConsentPartner(
                name="Google Analytics",
                purpose="Web analytics and measurement",
                data_collected=["page views", "session duration"],
            ),
        ],
        purposes=["Analytics", "Advertising"],
        raw_text="We use cookies to improve your experience.",
        claimed_partner_count=42,
    )


# ── Analysis Fixtures ──────────────────────────────────────────


@pytest.fixture()
def sample_pre_consent_stats() -> analysis.PreConsentStats:
    """Pre-consent tracking statistics."""
    return analysis.PreConsentStats(
        total_cookies=10,
        total_scripts=25,
        total_requests=100,
        total_local_storage=3,
        total_session_storage=1,
        tracking_cookies=3,
        tracking_scripts=5,
        tracker_requests=12,
    )
