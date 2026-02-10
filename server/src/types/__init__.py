# Types package — re-export all models for backward compatibility.
# Prefer importing from the specific submodule (e.g. src.types.consent).

from src.types.analysis import (
    AnalysisResult as AnalysisResult,
    CategoryScore as CategoryScore,
    DomainBreakdown as DomainBreakdown,
    DomainData as DomainData,
    ScoreBreakdown as ScoreBreakdown,
    SummaryFinding as SummaryFinding,
    SummaryFindingType as SummaryFindingType,
    TrackingSummary as TrackingSummary,
)
from src.types.browser import (
    AccessDenialResult as AccessDenialResult,
    DeviceConfig as DeviceConfig,
    DeviceType as DeviceType,
    NavigationResult as NavigationResult,
)
from src.types.consent import (
    ConfidenceLevel as ConfidenceLevel,
    ConsentCategory as ConsentCategory,
    ConsentDetails as ConsentDetails,
    ConsentPartner as ConsentPartner,
    CookieConsentDetection as CookieConsentDetection,
    OverlayType as OverlayType,
)
from src.types.partners import (
    PartnerCategoryConfig as PartnerCategoryConfig,
    PartnerCategoryType as PartnerCategoryType,
    PartnerClassification as PartnerClassification,
    PartnerEntry as PartnerEntry,
    PartnerRiskLevel as PartnerRiskLevel,
    PartnerRiskSummary as PartnerRiskSummary,
    ScriptPattern as ScriptPattern,
)
from src.types.tracking_data import (
    NetworkRequest as NetworkRequest,
    ScriptGroup as ScriptGroup,
    StorageItem as StorageItem,
    TrackedCookie as TrackedCookie,
    TrackedScript as TrackedScript,
)
