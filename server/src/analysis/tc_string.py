"""IAB TCF v2 TC String and Google AC String decoders.

Decodes the machine-readable consent string (``euconsent-v2``
cookie or ``__tcfapi`` ``getTCData`` response) into structured
data about purpose consents, vendor consents, legitimate
interests, and CMP metadata.

Additionally decodes the Google Additional Consent Mode (AC)
string stored in the ``addtl_consent`` cookie.  The AC String
lists non-IAB ad-tech providers that have received consent
through a Google-certified CMP.

The TC String is a Base64url-encoded bitfield defined by the
IAB Transparency & Consent Framework specification:
https://github.com/InteractiveAdvertisingBureau/GDPR-Transparency-and-Consent-Framework

The AC String format is documented in the Additional Consent
Mode specification:
https://support.google.com/admanager/answer/9681920

This module implements pure-Python decoders with no external
dependencies.

Only the **Core** segment (segment 0) of the TC String is
decoded.  The Disclosed Vendors, Publisher Restrictions, and
Publisher TC segments are present in multi-segment strings
(separated by ``.``) but are not currently parsed.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import UTC, datetime

import pydantic

from src.utils import logger, serialization

log = logger.create_logger("TcString")


# ====================================================================
# Bitfield reader
# ====================================================================


class _BitReader:
    """Read individual fields from a packed bitstring.

    The IAB TC String stores data as tightly packed binary
    fields (variable-width integers).  This reader wraps a
    ``bytes`` object and provides sequential field access.
    """

    __slots__ = ("_bits", "_length", "_pos")

    def __init__(self, data: bytes) -> None:
        self._bits = data
        self._pos = 0
        self._length = len(data) * 8

    @property
    def remaining(self) -> int:
        """Number of unread bits."""
        return self._length - self._pos

    def read_int(self, num_bits: int) -> int:
        """Read an unsigned integer of *num_bits* width."""
        if self._pos + num_bits > self._length:
            return 0
        value = 0
        for _ in range(num_bits):
            byte_index = self._pos // 8
            bit_index = 7 - (self._pos % 8)
            value = (value << 1) | ((self._bits[byte_index] >> bit_index) & 1)
            self._pos += 1
        return value

    def read_bool(self) -> bool:
        """Read a single bit as a boolean."""
        return self.read_int(1) == 1

    def read_bitfield(self, num_bits: int) -> list[int]:
        """Read a fixed-length bitfield, returning 1-based IDs that are set."""
        ids: list[int] = []
        for i in range(num_bits):
            if self.read_bool():
                ids.append(i + 1)
        return ids

    def read_string(self, num_chars: int) -> str:
        """Read a string of 6-bit encoded characters (A=0, Z=25)."""
        chars: list[str] = []
        for _ in range(num_chars):
            code = self.read_int(6)
            chars.append(chr(ord("A") + code))
        return "".join(chars)

    def read_vendor_section(self) -> list[int]:
        """Read a variable-length vendor consent/LI section.

        The IAB spec encodes vendor lists as either a bitfield
        or a range encoding, prefixed by ``MaxVendorId`` and
        an ``IsRangeEncoding`` flag.
        """
        max_vendor_id = self.read_int(16)
        is_range = self.read_bool()

        if not is_range:
            return self.read_bitfield(max_vendor_id)

        # Range encoding
        vendor_ids: list[int] = []
        num_entries = self.read_int(12)
        for _ in range(num_entries):
            is_group = self.read_bool()
            if is_group:
                start = self.read_int(16)
                end = self.read_int(16)
                vendor_ids.extend(range(start, end + 1))
            else:
                vendor_ids.append(self.read_int(16))
        return vendor_ids

    def skip(self, num_bits: int) -> None:
        """Advance the read position by *num_bits*."""
        self._pos = min(self._pos + num_bits, self._length)


# ====================================================================
# Decoded TC String model
# ====================================================================


class TcStringData(pydantic.BaseModel):
    """Decoded contents of a TCF v2 TC String (core segment)."""

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    # Metadata
    version: int
    created: str
    last_updated: str
    cmp_id: int
    cmp_version: int
    consent_screen: int
    consent_language: str
    vendor_list_version: int
    tcf_policy_version: int
    is_service_specific: bool
    use_non_standard_stacks: bool
    publisher_country_code: str

    # Purpose signals
    purpose_consents: list[int]
    purpose_legitimate_interests: list[int]

    # Special feature opt-ins
    special_feature_opt_ins: list[int]

    # Vendor signals
    vendor_consents: list[int]
    vendor_legitimate_interests: list[int]

    # Counts for quick summary
    vendor_consent_count: int = 0
    vendor_li_count: int = 0
    total_purposes_consented: int = 0

    # Raw string for reference
    raw_string: str = ""

    @pydantic.model_validator(mode="after")
    def _set_counts(self) -> TcStringData:
        self.vendor_consent_count = len(self.vendor_consents)
        self.vendor_li_count = len(self.vendor_legitimate_interests)
        self.total_purposes_consented = len(self.purpose_consents)
        return self


# ====================================================================
# Decoder
# ====================================================================

# IAB TCF epoch: deciseconds since 2000-01-01T00:00:00Z
_TCF_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def _decode_timestamp(deciseconds: int) -> str:
    """Convert a TCF decisecond timestamp to an ISO 8601 string."""
    try:
        dt = _TCF_EPOCH.timestamp() + (deciseconds / 10)
        return datetime.fromtimestamp(dt, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _base64url_decode(s: str) -> bytes:
    """Decode a Base64url string with padding correction."""
    # Add padding if needed
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def decode_tc_string(tc_string: str) -> TcStringData | None:
    """Decode a TCF v2 TC String into structured data.

    Parses the Core segment of the TC String, extracting
    metadata, purpose consents/LIs, special feature opt-ins,
    and vendor consents/LIs.

    Args:
        tc_string: The raw TC String (Base64url-encoded).

    Returns:
        Decoded ``TcStringData`` or ``None`` if the string
        cannot be parsed (too short, invalid encoding, or
        unsupported version).
    """
    if not tc_string or len(tc_string) < 10:
        return None

    try:
        # TC strings can have multiple segments separated by "."
        # We only decode the core segment (segment 0).
        core = tc_string.split(".")[0]
        data = _base64url_decode(core)
    except Exception:
        log.debug("TC string Base64 decode failed", {"length": len(tc_string)})
        return None

    reader = _BitReader(data)

    # Minimum core segment is ~170 bits — bail early if too short.
    if reader.remaining < 170:
        log.debug("TC string too short", {"bits": reader.remaining})
        return None

    try:
        version = reader.read_int(6)
        if version not in (1, 2):
            log.debug("Unsupported TC string version", {"version": version})
            return None

        created = _decode_timestamp(reader.read_int(36))
        last_updated = _decode_timestamp(reader.read_int(36))
        cmp_id = reader.read_int(12)
        cmp_version = reader.read_int(12)
        consent_screen = reader.read_int(6)
        consent_language = reader.read_string(2)
        vendor_list_version = reader.read_int(12)
        tcf_policy_version = reader.read_int(6)
        is_service_specific = reader.read_bool()
        use_non_standard_stacks = reader.read_bool()
        special_feature_opt_ins = reader.read_bitfield(12)
        purpose_consents = reader.read_bitfield(24)
        purpose_legitimate_interests = reader.read_bitfield(24)

        # Purpose one treatment (1 bit) — whether Purpose 1
        # was disclosed with "no legitimate interest" treatment.
        reader.skip(1)  # purposeOneTreatment

        publisher_country_code = reader.read_string(2)

        # Vendor consents and LI sections
        vendor_consents = reader.read_vendor_section()
        vendor_legitimate_interests = reader.read_vendor_section()

        return TcStringData(
            version=version,
            created=created,
            last_updated=last_updated,
            cmp_id=cmp_id,
            cmp_version=cmp_version,
            consent_screen=consent_screen,
            consent_language=consent_language,
            vendor_list_version=vendor_list_version,
            tcf_policy_version=tcf_policy_version,
            is_service_specific=is_service_specific,
            use_non_standard_stacks=use_non_standard_stacks,
            publisher_country_code=publisher_country_code,
            special_feature_opt_ins=special_feature_opt_ins,
            purpose_consents=purpose_consents,
            purpose_legitimate_interests=purpose_legitimate_interests,
            vendor_consents=vendor_consents,
            vendor_legitimate_interests=vendor_legitimate_interests,
            raw_string=tc_string,
        )
    except Exception:
        log.debug("TC string decode error", {"length": len(tc_string)})
        return None


# ====================================================================
# Cookie extraction helper
# ====================================================================


def find_tc_string_in_cookies(
    cookies: Sequence[object],
) -> str | None:
    """Find the TC String value from a list of browser cookies.

    Looks for the standard ``euconsent-v2`` cookie name, which
    is the TCF-mandated cookie for storing the TC String.

    Args:
        cookies: List of cookie objects with ``name`` and ``value``
            attributes or keys (supports both ``TrackedCookie``
            objects and plain dicts).

    Returns:
        The TC String value, or ``None`` if not found.
    """
    for cookie in cookies:
        name: str = ""
        value: str = ""
        # Support both dict and object access patterns
        if isinstance(cookie, dict):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
        else:
            name = str(getattr(cookie, "name", ""))
            value = str(getattr(cookie, "value", ""))

        if name == "euconsent-v2" and value:
            return value

    return None


# ====================================================================
# Google Additional Consent Mode (AC String) decoder
# ====================================================================


class AcStringData(pydantic.BaseModel):
    """Decoded contents of a Google AC String.

    The AC String format is ``{version}~{ATP ID 1}.{ATP ID 2}...``
    where ATP IDs are Google Ad Technology Provider identifiers
    for non-IAB vendors that received consent through a
    Google-certified CMP.
    """

    model_config = pydantic.ConfigDict(
        alias_generator=serialization.snake_to_camel,
        populate_by_name=True,
    )

    # Spec version (currently always 1)
    version: int

    # List of consented Google ATP IDs
    vendor_ids: list[int]

    # Count for quick summary
    vendor_count: int = 0

    # Raw string for reference
    raw_string: str = ""

    @pydantic.model_validator(mode="after")
    def _set_count(self) -> AcStringData:
        self.vendor_count = len(self.vendor_ids)
        return self


def decode_ac_string(ac_string: str) -> AcStringData | None:
    """Decode a Google Additional Consent Mode string.

    The AC String is stored in the ``addtl_consent`` cookie and
    lists non-IAB ad-tech providers that have received consent
    through a Google-certified CMP.

    Format: ``{version}~{ATP ID 1}.{ATP ID 2}.{ATP ID 3}...``
    Example: ``1~1.35.70.89.93.108``

    Args:
        ac_string: The raw AC String value.

    Returns:
        Decoded ``AcStringData`` or ``None`` if the string
        cannot be parsed.
    """
    if not ac_string or "~" not in ac_string:
        return None

    try:
        parts = ac_string.split("~", maxsplit=1)
        version = int(parts[0])

        vendor_ids: list[int] = []
        id_part = parts[1].strip()
        if id_part:
            for raw_id in id_part.split("."):
                raw_id = raw_id.strip()
                if raw_id:
                    vendor_ids.append(int(raw_id))

        return AcStringData(
            version=version,
            vendor_ids=sorted(set(vendor_ids)),
            raw_string=ac_string,
        )
    except (ValueError, IndexError):
        log.debug(
            "AC string decode error",
            {"length": len(ac_string)},
        )
        return None


def find_ac_string_in_cookies(
    cookies: Sequence[object],
) -> str | None:
    """Find the AC String value from a list of browser cookies.

    Looks for the standard ``addtl_consent`` cookie name, which
    stores the Google Additional Consent Mode string.

    Args:
        cookies: List of cookie objects with ``name`` and ``value``
            attributes or keys (supports both ``TrackedCookie``
            objects and plain dicts).

    Returns:
        The AC String value, or ``None`` if not found.
    """
    for cookie in cookies:
        name: str = ""
        value: str = ""
        # Support both dict and object access patterns
        if isinstance(cookie, dict):
            name = cookie.get("name", "")
            value = cookie.get("value", "")
        else:
            name = str(getattr(cookie, "name", ""))
            value = str(getattr(cookie, "value", ""))

        if name == "addtl_consent" and value:
            return value

    return None
