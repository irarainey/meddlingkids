"""
Type definitions for the tracking analysis server.
Contains dataclasses for cookies, scripts, storage, network requests,
consent detection, and analysis results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ============================================================================
# Tracking Data Types
# ============================================================================


@dataclass
class TrackedCookie:
    """Represents a cookie captured from the browser context."""

    name: str
    value: str
    domain: str
    path: str
    expires: float
    http_only: bool
    secure: bool
    same_site: str
    timestamp: str


@dataclass
class TrackedScript:
    """Represents a JavaScript script loaded by the page."""

    url: str
    domain: str
    timestamp: str = ""
    description: str | None = None
    resource_type: str = "script"
    group_id: str | None = None
    is_grouped: bool | None = None


@dataclass
class ScriptGroup:
    """Represents a group of similar scripts."""

    id: str
    name: str
    description: str
    count: int
    example_urls: list[str]
    domain: str


@dataclass
class StorageItem:
    """Represents an item stored in localStorage or sessionStorage."""

    key: str
    value: str
    timestamp: str


@dataclass
class NetworkRequest:
    """Represents an HTTP network request made by the page."""

    url: str
    domain: str
    method: str
    resource_type: str
    is_third_party: bool
    timestamp: str
    status_code: int | None = None


# ============================================================================
# Cookie Consent Types
# ============================================================================

OverlayType = Literal[
    "cookie-consent",
    "sign-in",
    "newsletter",
    "paywall",
    "age-verification",
    "other",
]

ConfidenceLevel = Literal["high", "medium", "low"]


@dataclass
class CookieConsentDetection:
    """Result of LLM vision analysis for detecting cookie consent banners."""

    found: bool
    overlay_type: OverlayType | None
    selector: str | None
    button_text: str | None
    confidence: ConfidenceLevel
    reason: str


@dataclass
class ConsentCategory:
    """Represents a cookie category disclosed in a consent dialog."""

    name: str
    description: str
    required: bool


@dataclass
class ConsentPartner:
    """Represents a third-party partner/vendor listed in a consent dialog."""

    name: str
    purpose: str
    data_collected: list[str]
    risk_level: str | None = None
    risk_category: str | None = None
    risk_score: int | None = None
    concerns: list[str] | None = None


@dataclass
class ConsentDetails:
    """Detailed information extracted from a cookie consent dialog."""

    has_manage_options: bool
    manage_options_selector: str | None
    categories: list[ConsentCategory]
    partners: list[ConsentPartner]
    purposes: list[str]
    raw_text: str
    expanded: bool | None = None


# ============================================================================
# Analysis Types
# ============================================================================


@dataclass
class DomainData:
    """Tracking data grouped by domain."""

    cookies: list[TrackedCookie] = field(default_factory=list)
    scripts: list[TrackedScript] = field(default_factory=list)
    network_requests: list[NetworkRequest] = field(default_factory=list)


@dataclass
class DomainBreakdown:
    """Summary statistics for a single domain's tracking activity."""

    domain: str
    cookie_count: int
    cookie_names: list[str]
    script_count: int
    request_count: int
    request_types: list[str]


@dataclass
class TrackingSummary:
    """Complete summary of tracking data collected from a page."""

    analyzed_url: str
    total_cookies: int
    total_scripts: int
    total_network_requests: int
    local_storage_items: int
    session_storage_items: int
    third_party_domains: list[str]
    domain_breakdown: list[DomainBreakdown]
    local_storage: list[dict[str, str]]
    session_storage: list[dict[str, str]]


SummaryFindingType = Literal["critical", "high", "moderate", "info", "positive"]


@dataclass
class SummaryFinding:
    """A single finding in the summary."""

    type: SummaryFindingType
    text: str


@dataclass
class CategoryScore:
    """Score for an individual category."""

    points: int = 0
    max_points: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of how the score was calculated."""

    total_score: int = 0
    categories: dict[str, CategoryScore] = field(default_factory=dict)
    factors: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class AnalysisResult:
    """Result of the AI-powered tracking analysis."""

    success: bool
    analysis: str | None = None
    summary_findings: list[SummaryFinding] | None = None
    privacy_score: int | None = None
    privacy_summary: str | None = None
    score_breakdown: ScoreBreakdown | None = None
    summary: TrackingSummary | None = None
    error: str | None = None


# ============================================================================
# Data / Partner Types
# ============================================================================

PartnerRiskLevel = Literal["critical", "high", "medium", "low", "unknown"]

PartnerCategoryType = Literal[
    "data-broker",
    "advertising",
    "cross-site-tracking",
    "identity-resolution",
    "analytics",
    "social-media",
    "content-delivery",
    "fraud-prevention",
    "personalization",
    "measurement",
    "unknown",
]


@dataclass
class PartnerEntry:
    """Partner entry as stored in JSON."""

    concerns: list[str]
    aliases: list[str]


@dataclass
class ScriptPattern:
    """Compiled script pattern with regex ready for matching."""

    pattern: str  # raw regex string, compiled on use
    description: str


@dataclass
class PartnerCategoryConfig:
    """Configuration for how a partner category should be classified."""

    file: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    risk_score: int


@dataclass
class PartnerClassification:
    """Classification result for a partner."""

    name: str
    risk_level: PartnerRiskLevel
    category: PartnerCategoryType
    reason: str
    concerns: list[str]
    risk_score: int


@dataclass
class PartnerRiskSummary:
    """Quick risk summary for a set of consent partners."""

    critical_count: int
    high_count: int
    total_risk_score: int
    worst_partners: list[str]


# ============================================================================
# Browser Session Types
# ============================================================================


@dataclass
class NavigationResult:
    """Result of a navigation attempt."""

    success: bool
    status_code: int | None
    status_text: str | None
    is_access_denied: bool
    error_message: str | None


@dataclass
class AccessDenialResult:
    """Result of an access denial check."""

    denied: bool
    reason: str | None


# ============================================================================
# Device Types
# ============================================================================

DeviceType = Literal[
    "iphone",
    "ipad",
    "android-phone",
    "android-tablet",
    "windows-chrome",
    "macos-safari",
]


@dataclass
class DeviceConfig:
    """Device configuration for browser emulation."""

    user_agent: str
    viewport: dict[str, int]
    device_scale_factor: float
    is_mobile: bool
    has_touch: bool
