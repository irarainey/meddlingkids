"""Decoders for privacy-relevant cookies and storage values.

Extracts structured data from well-known cookie formats
beyond the IAB TC and AC strings.  Each decoder returns a
plain dict suitable for JSON serialisation (camelCase keys).

Supported formats
-----------------
- **USP String** (``usprivacy``): IAB CCPA opt-out signal.
- **GPP String** (``__gpp`` / ``__gpp_sid``): IAB Global
  Privacy Platform multi-jurisdiction consent string.
- **Google Analytics** (``_ga``, ``_gid``): client ID and
  first-visit timestamp.
- **Facebook Pixel** (``_fbp``, ``_fbc``): browser ID and
  click-through attribution.
- **Google Ads** (``_gcl_au``, ``_gcl_aw``): conversion
  linker timestamps and click IDs.
- **OneTrust** (``OptanonConsent``): category-level consent.
- **Cookiebot** (``CookieConsent``): category-level consent.
- **Google SOCS** (``SOCS``): Google consent mode state.
- **GPC / DNT**: Global Privacy Control and Do Not Track
  header detection.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib import parse

from src.utils import logger

log = logger.create_logger("CookieDecoders")

# Maximum characters retained for raw cookie value previews.
_RAW_VALUE_PREVIEW_LIMIT = 200

# Shorter preview limit for minimal decoders (e.g. SOCS).
_SOCS_PREVIEW_LIMIT = 100


# ====================================================================
# Helper: cookie value extractor
# ====================================================================


def _cookie_value(
    cookies: Sequence[object],
    target_name: str,
) -> str | None:
    """Return the value of the first cookie matching *target_name*."""
    for cookie in cookies:
        if isinstance(cookie, dict):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
        else:
            name = str(getattr(cookie, "name", ""))
            value = str(getattr(cookie, "value", ""))
        if name == target_name and value:
            return str(value)
    return None


# ====================================================================
# 1. USP String  (usprivacy)
# ====================================================================

_USP_CHAR_MAP: dict[str, str] = {
    "Y": "Yes",
    "N": "No",
    "-": "Not applicable",
}


def decode_usp_string(raw: str) -> dict[str, object] | None:
    """Decode an IAB US Privacy String (CCPA).

    Format: 4 characters — ``{version}{notice}{optOut}{lspa}``
    Example: ``1YNN`` → version 1, notice given, not opted out,
    not covered by LSPA.

    See https://github.com/InteractiveAdvertisingBureau/USPrivacy
    """
    if not raw or len(raw) < 4:
        return None

    try:
        version = int(raw[0])
    except ValueError:
        return None

    def _label(ch: str) -> str:
        return _USP_CHAR_MAP.get(ch.upper(), ch)

    notice = raw[1].upper()
    opt_out = raw[2].upper()
    lspa = raw[3].upper()

    return {
        "version": version,
        "noticeGiven": notice == "Y",
        "optedOut": opt_out == "Y",
        "lspaCovered": lspa == "Y",
        "noticeLabel": _label(notice),
        "optOutLabel": _label(opt_out),
        "lspaLabel": _label(lspa),
        "rawString": raw,
    }


def find_usp_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode the ``usprivacy`` cookie."""
    raw = _cookie_value(cookies, "usprivacy")
    if raw:
        return decode_usp_string(raw)
    return None


# ====================================================================
# 2. GPP String  (__gpp / __gpp_sid)
# ====================================================================

_GPP_SECTION_NAMES: dict[int, str] = {
    2: "TCF EU v2",
    3: "TCF EU v1 (deprecated)",
    6: "USP v1 (CCPA)",
    7: "US National",
    8: "US California (CPRA)",
    9: "US Virginia (VCDPA)",
    10: "US Colorado (CPA)",
    11: "US Utah (UCPA)",
    12: "US Connecticut (CTDPA)",
    13: "US Florida (FDBR)",
    14: "US Montana (MCDPA)",
    15: "US Oregon (OCPA)",
    16: "US Texas (TDPSA)",
    17: "US Delaware (DPDPA)",
    18: "US Iowa (ICDPA)",
    19: "US Nebraska (NDPA)",
    20: "US New Hampshire (NHPA)",
    21: "US New Jersey (NJDPA)",
    22: "US Tennessee (TIPA)",
}


def decode_gpp_string(
    gpp_raw: str,
    sid_raw: str | None = None,
) -> dict[str, object] | None:
    """Decode a GPP String header and section IDs.

    The full GPP String is complex (multi-segment Base64) so
    we extract the header metadata and applicable section IDs
    without fully decoding every section's bitfields.

    Args:
        gpp_raw: The ``__gpp`` cookie value.
        sid_raw: The ``__gpp_sid`` cookie value (comma-
            separated section IDs), if present.
    """
    if not gpp_raw:
        return None

    # Parse section IDs from __gpp_sid first.
    section_ids: list[int] = []
    if sid_raw:
        for part in sid_raw.replace("_", ",").split(","):
            part = part.strip()
            if part.isdigit():
                section_ids.append(int(part))

    # The GPP header is the first segment (before the first ~).
    segments = gpp_raw.split("~")

    sections: list[dict[str, object]] = []
    for sid in section_ids:
        name = _GPP_SECTION_NAMES.get(sid, f"Section {sid}")
        sections.append({"id": sid, "name": name})

    result: dict[str, object] = {
        "segmentCount": len(segments),
        "sectionIds": section_ids,
        "sections": sections,
        "rawString": gpp_raw,
    }

    # Try to extract the GPP version from the header.
    try:
        header_b64 = segments[0]
        # GPP uses Base64url; add padding if needed.
        padding = 4 - len(header_b64) % 4
        if padding < 4:
            header_b64 += "=" * padding
        header_bytes = base64.urlsafe_b64decode(header_b64)
        if len(header_bytes) >= 1:
            # First 6 bits = type (should be 3 for GPP header).
            # Next 6 bits = version.
            first_byte = header_bytes[0]
            gpp_type = (first_byte >> 2) & 0x3F
            if gpp_type == 3 and len(header_bytes) >= 2:
                version = ((first_byte & 0x03) << 4) | ((header_bytes[1] >> 4) & 0x0F)
                result["version"] = version
    except Exception:
        pass  # Header decode is best-effort.

    return result


def find_gpp_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode ``__gpp`` / ``__gpp_sid`` cookies."""
    gpp_raw = _cookie_value(cookies, "__gpp")
    if not gpp_raw:
        return None
    sid_raw = _cookie_value(cookies, "__gpp_sid")
    return decode_gpp_string(gpp_raw, sid_raw)


# ====================================================================
# 3. Google Analytics  (_ga / _gid)
# ====================================================================

_GA_PATTERN = re.compile(
    r"^GA\d+\.\d+\.(\d+)\.(\d+)$",
)


def decode_ga_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Google Analytics ``_ga`` cookie.

    Format: ``GA1.2.{clientId}.{timestamp}``
    The timestamp is a Unix epoch (seconds) of first visit.
    """
    if not raw:
        return None

    m = _GA_PATTERN.match(raw)
    if not m:
        return None

    client_id = m.group(1)
    try:
        ts = int(m.group(2))
        first_visit = datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (ValueError, OSError):
        first_visit = None

    return {
        "clientId": client_id,
        "firstVisitTimestamp": ts if first_visit else None,
        "firstVisit": first_visit,
        "rawValue": raw,
    }


def find_ga_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode the ``_ga`` cookie."""
    raw = _cookie_value(cookies, "_ga")
    if raw:
        return decode_ga_cookie(raw)
    return None


# ====================================================================
# 4. Facebook Pixel  (_fbp / _fbc)
# ====================================================================

_FB_PATTERN = re.compile(
    r"^fb\.\d+\.(\d+)\.(.+)$",
)


def decode_fbp_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Facebook ``_fbp`` (browser ID) cookie.

    Format: ``fb.{subdomain}.{timestamp_ms}.{randomId}``
    """
    if not raw:
        return None

    m = _FB_PATTERN.match(raw)
    if not m:
        return None

    try:
        ts_ms = int(m.group(1))
        created = datetime.fromtimestamp(
            ts_ms / 1000,
            tz=UTC,
        ).isoformat()
    except (ValueError, OSError):
        ts_ms = 0
        created = None

    return {
        "browserId": m.group(2),
        "createdTimestamp": ts_ms,
        "created": created,
        "rawValue": raw,
    }


def decode_fbc_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Facebook ``_fbc`` (click ID) cookie.

    Format: ``fb.{subdomain}.{timestamp_ms}.{fbclid}``
    The fbclid links the visit to a specific Facebook ad click.
    """
    if not raw:
        return None

    m = _FB_PATTERN.match(raw)
    if not m:
        return None

    try:
        ts_ms = int(m.group(1))
        clicked = datetime.fromtimestamp(
            ts_ms / 1000,
            tz=UTC,
        ).isoformat()
    except (ValueError, OSError):
        ts_ms = 0
        clicked = None

    return {
        "fbclid": m.group(2),
        "clickTimestamp": ts_ms,
        "clicked": clicked,
        "rawValue": raw,
    }


def find_fb_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode Facebook ``_fbp`` and ``_fbc`` cookies.

    Returns a combined dict with ``fbp`` and ``fbc`` sub-keys.
    """
    fbp_raw = _cookie_value(cookies, "_fbp")
    fbc_raw = _cookie_value(cookies, "_fbc")
    if not fbp_raw and not fbc_raw:
        return None

    result: dict[str, object] = {}
    if fbp_raw:
        result["fbp"] = decode_fbp_cookie(fbp_raw)
    if fbc_raw:
        result["fbc"] = decode_fbc_cookie(fbc_raw)
    return result


# ====================================================================
# 5. Google Ads  (_gcl_au / _gcl_aw)
# ====================================================================


def decode_gcl_au_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Google Ads ``_gcl_au`` conversion linker cookie.

    Format: ``{version}.{random}.{timestamp}``
    Timestamp is Unix epoch (seconds).
    """
    if not raw:
        return None

    parts = raw.split(".")
    if len(parts) < 3:
        return None

    try:
        ts = int(parts[-1])
        created = datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (ValueError, OSError):
        ts = 0
        created = None

    return {
        "version": parts[0],
        "createdTimestamp": ts,
        "created": created,
        "rawValue": raw,
    }


def decode_gcl_aw_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Google Ads ``_gcl_aw`` click cookie.

    Format: ``GCL.{timestamp}.{gclid}``
    """
    if not raw:
        return None

    parts = raw.split(".")
    if len(parts) < 3:
        return None

    try:
        ts = int(parts[1])
        clicked = datetime.fromtimestamp(ts, tz=UTC).isoformat()
    except (ValueError, OSError):
        ts = 0
        clicked = None

    gclid = ".".join(parts[2:])

    return {
        "gclid": gclid,
        "clickTimestamp": ts,
        "clicked": clicked,
        "rawValue": raw,
    }


def find_gcl_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode Google Ads ``_gcl_au`` and ``_gcl_aw``."""
    au_raw = _cookie_value(cookies, "_gcl_au")
    aw_raw = _cookie_value(cookies, "_gcl_aw")
    if not au_raw and not aw_raw:
        return None

    result: dict[str, object] = {}
    if au_raw:
        result["gclAu"] = decode_gcl_au_cookie(au_raw)
    if aw_raw:
        result["gclAw"] = decode_gcl_aw_cookie(aw_raw)
    return result


# ====================================================================
# 6. OneTrust  (OptanonConsent)
# ====================================================================

_OPTANON_CATEGORY_NAMES: dict[str, str] = {
    "C0001": "Strictly Necessary",
    "C0002": "Performance / Analytics",
    "C0003": "Functional",
    "C0004": "Targeting / Advertising",
    "C0005": "Social Media",
}


def decode_optanon_consent(raw: str) -> dict[str, object] | None:
    """Decode an OneTrust ``OptanonConsent`` cookie.

    URL-encoded; key fields include ``groups``, ``datestamp``,
    ``isGpcApplied``, and ``consentId``.
    """
    if not raw:
        return None

    decoded = parse.unquote(raw)
    parts: dict[str, str] = {}
    for pair in decoded.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            parts[k] = v

    groups_str = parts.get("groups", "")
    categories: list[dict[str, object]] = []
    if groups_str:
        for group in groups_str.split(","):
            group = group.strip()
            if ":" in group:
                cat_id, status = group.split(":", 1)
                cat_id = cat_id.strip()
                label = _OPTANON_CATEGORY_NAMES.get(
                    cat_id,
                    cat_id,
                )
                consented = status.strip() == "1"
                categories.append(
                    {
                        "id": cat_id,
                        "name": label,
                        "consented": consented,
                    }
                )

    return {
        "categories": categories,
        "datestamp": parts.get("datestamp"),
        "isGpcApplied": parts.get("isGpcApplied") == "true",
        "consentId": parts.get("consentId"),
        "rawValue": raw[:_RAW_VALUE_PREVIEW_LIMIT],
    }


def find_optanon_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode the ``OptanonConsent`` cookie."""
    raw = _cookie_value(cookies, "OptanonConsent")
    if raw:
        return decode_optanon_consent(raw)
    return None


# ====================================================================
# 7. Cookiebot  (CookieConsent)
# ====================================================================


def decode_cookiebot_consent(raw: str) -> dict[str, object] | None:
    """Decode a Cookiebot ``CookieConsent`` cookie.

    URL-encoded or JSON format with category consent bools
    (``necessary``, ``preferences``, ``statistics``,
    ``marketing``), ``stamp``, and ``utc`` timestamp.
    """
    if not raw:
        return None

    decoded = parse.unquote(raw)

    # Try JSON parse first (some implementations use JSON).
    try:
        data = json.loads(decoded)
        if isinstance(data, dict):
            categories: list[dict[str, object]] = []
            for cat in (
                "necessary",
                "preferences",
                "statistics",
                "marketing",
            ):
                if cat in data:
                    categories.append(
                        {
                            "name": cat.title(),
                            "consented": bool(data[cat]),
                        }
                    )
            return {
                "categories": categories,
                "stamp": data.get("stamp"),
                "utc": data.get("utc"),
                "rawValue": raw[:_RAW_VALUE_PREVIEW_LIMIT],
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to stamp-encoded format:
    # stamp:'...'%2Cnecessary:true%2Cpreferences:false%2C...
    parts: dict[str, str] = {}
    for pair in re.split(r"[,&]", decoded):
        if ":" in pair:
            k, v = pair.split(":", 1)
            parts[k.strip().strip("'")] = v.strip().strip("'")

    if not parts:
        return None

    categories = []
    for cat in ("necessary", "preferences", "statistics", "marketing"):
        if cat in parts:
            categories.append(
                {
                    "name": cat.title(),
                    "consented": parts[cat].lower() == "true",
                }
            )

    if not categories:
        return None

    return {
        "categories": categories,
        "stamp": parts.get("stamp"),
        "utc": parts.get("utc"),
        "rawValue": raw[:_RAW_VALUE_PREVIEW_LIMIT],
    }


def find_cookiebot_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode the ``CookieConsent`` cookie."""
    raw = _cookie_value(cookies, "CookieConsent")
    if raw:
        return decode_cookiebot_consent(raw)
    return None


# ====================================================================
# 8. Google SOCS cookie
# ====================================================================


def decode_socs_cookie(raw: str) -> dict[str, object] | None:
    """Decode a Google ``SOCS`` consent cookie.

    The SOCS cookie is Base64-encoded.  The first character
    of the decoded value encodes the consent mode:
    - ``C`` → Customised / all accepted
    - ``A`` → All rejected
    - ``E`` → Essential only
    """
    if not raw:
        return None

    try:
        # SOCS is standard Base64.
        padding = 4 - len(raw) % 4
        if padding < 4:
            raw_padded = raw + "=" * padding
        else:
            raw_padded = raw
        decoded_bytes = base64.b64decode(raw_padded)
        decoded = decoded_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None

    mode_char = decoded[0] if decoded else ""
    mode_labels: dict[str, str] = {
        "C": "All accepted / Customised",
        "A": "All rejected",
        "E": "Essential only",
    }
    mode = mode_labels.get(mode_char, f"Unknown ({mode_char})")

    return {
        "consentMode": mode,
        "modeChar": mode_char,
        "rawValue": raw[:_SOCS_PREVIEW_LIMIT],
    }


def find_socs_in_cookies(
    cookies: Sequence[object],
) -> dict[str, object] | None:
    """Find and decode the ``SOCS`` cookie."""
    raw = _cookie_value(cookies, "SOCS")
    if raw:
        return decode_socs_cookie(raw)
    return None


# ====================================================================
# 9. GPC / DNT detection
# ====================================================================


def detect_gpc_dnt(
    cookies: Sequence[object],
    *,
    response_headers: dict[str, str] | None = None,
) -> dict[str, object] | None:
    """Detect Global Privacy Control and Do Not Track signals.

    GPC can be signalled via a ``Sec-GPC: 1`` response header
    or a ``gpc`` cookie / JS API.  DNT is the older ``DNT: 1``
    header.  This function returns detected signals or ``None``
    if neither is present.
    """
    gpc_header = False
    dnt_header = False

    if response_headers:
        gpc_header = response_headers.get("Sec-GPC") == "1"
        dnt_raw = response_headers.get("DNT", "")
        dnt_header = dnt_raw == "1"

    if not gpc_header and not dnt_header:
        return None

    return {
        "gpcEnabled": gpc_header,
        "dntEnabled": dnt_header,
    }


# ====================================================================
# Master decoder — scans cookies for all known formats
# ====================================================================


def decode_all_privacy_cookies(
    cookies: Sequence[object],
) -> dict[str, object]:
    """Scan cookies and decode all recognised privacy formats.

    Returns a dict keyed by decoder name (e.g. ``"uspString"``,
    ``"gppString"``, ``"googleAnalytics"``).  Only entries that
    decoded successfully are included.
    """
    result: dict[str, object] = {}

    usp = find_usp_in_cookies(cookies)
    if usp:
        result["uspString"] = usp

    gpp = find_gpp_in_cookies(cookies)
    if gpp:
        result["gppString"] = gpp

    ga = find_ga_in_cookies(cookies)
    if ga:
        result["googleAnalytics"] = ga

    fb = find_fb_in_cookies(cookies)
    if fb:
        result["facebookPixel"] = fb

    gcl = find_gcl_in_cookies(cookies)
    if gcl:
        result["googleAds"] = gcl

    optanon = find_optanon_in_cookies(cookies)
    if optanon:
        result["oneTrust"] = optanon

    cookiebot = find_cookiebot_in_cookies(cookies)
    if cookiebot:
        result["cookiebot"] = cookiebot

    socs = find_socs_in_cookies(cookies)
    if socs:
        result["googleSocs"] = socs

    return result
