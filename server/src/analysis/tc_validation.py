"""TC String consent validation.

Cross-references the machine-readable TC String signals against
the human-readable consent dialog text to detect discrepancies,
undisclosed purposes, and privacy-relevant signals.

This is a pure deterministic module — no LLM calls, no network
access.  It takes pre-computed data (decoded TC String + TCF
purpose lookup results) and produces structured findings.
"""

from __future__ import annotations

from typing import Any, Literal

import pydantic

from src.data import loader
from src.utils import serialization

# ====================================================================
# Validation result models
# ====================================================================

FindingSeverity = Literal["critical", "high", "moderate", "info"]


class TcValidationFinding(pydantic.BaseModel):
    """A single validation finding from TC String cross-referencing."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    severity: FindingSeverity
    category: str
    title: str
    detail: str


class TcPurposeSignal(pydantic.BaseModel):
    """A purpose consent/LI signal decoded from the TC String."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    id: int
    name: str
    description: str
    risk_level: str
    consented: bool
    legitimate_interest: bool
    disclosed_in_dialog: bool


class TcValidationResult(pydantic.BaseModel):
    """Complete TC String validation result."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    # Purpose-level signals with dialog cross-reference
    purpose_signals: list[TcPurposeSignal]

    # Vendor counts
    vendor_consent_count: int
    vendor_li_count: int
    claimed_partner_count: int | None
    vendor_count_mismatch: bool

    # Google AC String vendor count (non-IAB vendors)
    ac_vendor_count: int | None = None

    # Special feature opt-ins (critical privacy signals)
    special_features: list[str]

    # Structured findings
    findings: list[TcValidationFinding]


# ====================================================================
# Purpose taxonomy cache
# ====================================================================


def _get_purpose_info() -> dict[int, dict[str, Any]]:
    """Return a dict mapping purpose ID → purpose metadata from the TCF taxonomy."""
    data = loader.get_tcf_purposes()
    result: dict[int, dict[str, Any]] = {}
    for pid_str, entry in data.get("purposes", {}).items():
        result[int(pid_str)] = entry
    return result


_SPECIAL_FEATURE_NAMES: dict[int, str] = {
    1: "Use precise geolocation data",
    2: "Actively scan device characteristics for identification",
}


# ====================================================================
# Validation logic
# ====================================================================


def validate_tc_consent(
    tc_string_data: dict[str, object],
    dialog_purposes: list[str],
    matched_purpose_ids: set[int],
    claimed_partner_count: int | None = None,
    ac_vendor_count: int | None = None,
    detected_cmp_id: int | None = None,
) -> TcValidationResult:
    """Cross-reference TC String data against consent dialog content.

    Args:
        tc_string_data: Decoded TC String (camelCase dict from
            ``TcStringData.model_dump(by_alias=True)``).
        dialog_purposes: Raw purpose strings from the consent dialog.
        matched_purpose_ids: Set of TCF purpose IDs that the
            dialog purposes matched to (from ``tcf_lookup``).
        claimed_partner_count: Number of partners the dialog
            text claimed (e.g. "We and our 1467 partners").
        ac_vendor_count: Number of non-IAB vendors from the
            Google Additional Consent Mode (AC String), or
            ``None`` if no AC String was found.
        detected_cmp_id: IAB CMP ID from the detected CMP
            profile, or ``None`` if the CMP was not identified.

    Returns:
        Structured validation result with purpose signals,
        vendor counts, special features, and findings.
    """
    purpose_info = _get_purpose_info()
    findings: list[TcValidationFinding] = []

    # ── Extract TC String fields ─────────────────────────
    _raw_consents = tc_string_data.get("purposeConsents", [])
    tc_purpose_consents: list[int] = list(_raw_consents) if isinstance(_raw_consents, list) else []
    _raw_lis = tc_string_data.get("purposeLegitimateInterests", [])
    tc_purpose_lis: list[int] = list(_raw_lis) if isinstance(_raw_lis, list) else []
    _raw_sfs = tc_string_data.get("specialFeatureOptIns", [])
    tc_special_features: list[int] = list(_raw_sfs) if isinstance(_raw_sfs, list) else []
    _raw_consent_count = tc_string_data.get("vendorConsentCount", 0)
    vendor_consent_count = int(_raw_consent_count) if isinstance(_raw_consent_count, (int, float, str)) else 0
    _raw_li_count = tc_string_data.get("vendorLiCount", 0)
    vendor_li_count = int(_raw_li_count) if isinstance(_raw_li_count, (int, float, str)) else 0

    tc_purpose_ids = set(tc_purpose_consents) | set(tc_purpose_lis)

    # ── CMP ID cross-validation ──────────────────────────
    # When we detected a CMP profile with a known IAB CMP ID,
    # verify that the TC String's embedded cmpId matches.  A
    # mismatch may indicate a misconfigured CMP or a stale TC
    # String from a previous CMP deployment.
    if detected_cmp_id is not None:
        _raw_cmp_id = tc_string_data.get("cmpId")
        tc_cmp_id = int(_raw_cmp_id) if isinstance(_raw_cmp_id, (int, float)) else None
        if tc_cmp_id is not None and tc_cmp_id != detected_cmp_id:
            findings.append(
                TcValidationFinding(
                    severity="info",
                    category="cmp-id-mismatch",
                    title="TC String CMP ID differs from detected CMP",
                    detail=(
                        f"The TC String was created by CMP ID {tc_cmp_id}, "
                        f"but the detected CMP on this page has IAB CMP ID "
                        f"{detected_cmp_id}. This may indicate that the site "
                        f"recently switched CMP providers and the TC String "
                        f"was carried over from the previous deployment, or "
                        f"that the CMP is operating with a different "
                        f"registered identity."
                    ),
                ),
            )

    # ── Build purpose signals ────────────────────────────
    # Cover all 11 TCF purposes, marking consent/LI/disclosed status
    all_purpose_ids = set(range(1, 12)) | tc_purpose_ids | matched_purpose_ids
    purpose_signals: list[TcPurposeSignal] = []

    for pid in sorted(all_purpose_ids):
        info = purpose_info.get(pid)
        if info is None:
            continue

        consented = pid in tc_purpose_consents
        has_li = pid in tc_purpose_lis
        disclosed = pid in matched_purpose_ids

        purpose_signals.append(
            TcPurposeSignal(
                id=pid,
                name=info["name"],
                description=info["description"],
                risk_level=info.get("risk_level", "medium"),
                consented=consented,
                legitimate_interest=has_li,
                disclosed_in_dialog=disclosed,
            ),
        )

    # ── Detect undisclosed purposes ──────────────────────
    # Purposes that have consent or LI in the TC string but
    # were NOT shown to the user in the dialog text.
    if dialog_purposes:
        undisclosed = tc_purpose_ids - matched_purpose_ids
        for pid in sorted(undisclosed):
            info = purpose_info.get(pid)
            if info is None:
                continue
            risk = info.get("risk_level", "medium")
            severity: FindingSeverity = "high" if risk in ("high", "critical") else "moderate"
            findings.append(
                TcValidationFinding(
                    severity=severity,
                    category="undisclosed-purpose",
                    title=f"Purpose not matched to dialog: {info['name']}",
                    detail=(
                        f"TCF Purpose {pid} ({info['name']}) is consented in the TC String "
                        f"but was not matched to the consent dialog text. This could mean "
                        f"the purpose was not disclosed, or that the AI did not recognise "
                        f"the dialog's wording for it."
                    ),
                ),
            )

    # ── Consent-only purposes using LI ───────────────────
    # Purposes 3, 4, 5, 6 require consent under TCF v2.2 —
    # using LI for these is a compliance concern.
    consent_only_purposes = {3, 4, 5, 6}
    li_misuse = consent_only_purposes & set(tc_purpose_lis)
    for pid in sorted(li_misuse):
        info = purpose_info.get(pid)
        if info is None:
            continue
        findings.append(
            TcValidationFinding(
                severity="high",
                category="li-misuse",
                title=f"Legitimate interest on consent-only purpose: {info['name']}",
                detail=(
                    f"TCF Purpose {pid} ({info['name']}) has legitimate interest enabled "
                    f"in the TC String, but this purpose requires explicit consent "
                    f"under TCF v2.2 policy. This is a potential compliance issue."
                ),
            ),
        )

    # ── Special feature opt-ins ──────────────────────────
    special_features: list[str] = []
    for sf_id in sorted(tc_special_features):
        name = _SPECIAL_FEATURE_NAMES.get(sf_id, f"Special Feature {sf_id}")
        special_features.append(name)
        severity = "critical" if sf_id == 1 else "high"
        findings.append(
            TcValidationFinding(
                severity=severity,
                category="special-feature",
                title=f"Special feature opted in: {name}",
                detail=(
                    f"The TC String indicates opt-in to Special Feature {sf_id}: "
                    f"{name}. "
                    + (
                        "Precise geolocation tracking is a critical privacy concern."
                        if sf_id == 1
                        else "Active device fingerprinting is a significant privacy concern."
                    )
                ),
            ),
        )

    # ── Vendor count comparison ──────────────────────────
    vendor_count_mismatch = False
    # Build an AC context string for vendor-count findings
    _ac_note = ""
    if ac_vendor_count is not None and ac_vendor_count > 0:
        _ac_note = (
            f" Additionally, {ac_vendor_count} non-IAB vendor"
            f"{'s' if ac_vendor_count != 1 else ''} received consent "
            f"via Google\u2019s Additional Consent Mode (AC String), "
            f"bringing the combined total to "
            f"{vendor_consent_count + ac_vendor_count}."
        )

    if claimed_partner_count is not None and vendor_consent_count > 0:
        diff = abs(vendor_consent_count - claimed_partner_count)
        ratio = diff / max(claimed_partner_count, 1)
        # Flag if counts differ by more than 20% and more than 10 vendors
        if ratio > 0.2 and diff > 10:
            vendor_count_mismatch = True
            if vendor_consent_count > claimed_partner_count:
                findings.append(
                    TcValidationFinding(
                        severity="info",
                        category="vendor-count",
                        title="Vendor count differs from dialog",
                        detail=(
                            f"The consent dialog claimed {claimed_partner_count} partners, "
                            f"while the TC String grants consent to {vendor_consent_count} "
                            f"IAB-registered vendors. The TC String only covers vendors in the "
                            f"IAB Global Vendor List \u2014 the difference may reflect vendors "
                            f"registered in the GVL that are not individually named in the "
                            f"dialog text.{_ac_note}"
                        ),
                    ),
                )
            else:
                findings.append(
                    TcValidationFinding(
                        severity="info",
                        category="vendor-count",
                        title="Vendor count differs from dialog",
                        detail=(
                            f"The consent dialog claimed {claimed_partner_count} partners, "
                            f"while the TC String grants consent to {vendor_consent_count} "
                            f"IAB-registered vendors. The dialog count may include non-TCF "
                            f"vendors, downstream data-sharing partners, or vendors using "
                            f"Google\u2019s Additional Consent Mode, which are not encoded in "
                            f"the TC String.{_ac_note}"
                        ),
                    ),
                )

    # ── High-risk purpose summary ────────────────────────
    high_risk_consented = [ps for ps in purpose_signals if ps.consented and ps.risk_level in ("high", "critical")]
    if high_risk_consented:
        names = ", ".join(ps.name for ps in high_risk_consented)
        findings.append(
            TcValidationFinding(
                severity="high",
                category="high-risk-consent",
                title=f"{len(high_risk_consented)} high-risk purpose{'s' if len(high_risk_consented) != 1 else ''} consented",
                detail=(
                    f"The TC String grants consent to the following high-risk purposes: "
                    f"{names}. These purposes involve user profiling and personalised "
                    f"advertising."
                ),
            ),
        )

    # Sort findings by severity
    severity_order: dict[str, int] = {
        "critical": 0,
        "high": 1,
        "moderate": 2,
        "info": 3,
    }
    findings.sort(key=lambda f: severity_order.get(f.severity, 99))

    return TcValidationResult(
        purpose_signals=purpose_signals,
        vendor_consent_count=vendor_consent_count,
        vendor_li_count=vendor_li_count,
        claimed_partner_count=claimed_partner_count,
        vendor_count_mismatch=vendor_count_mismatch,
        ac_vendor_count=ac_vendor_count,
        special_features=special_features,
        findings=findings,
    )
