"""Data loader facade -- re-exports from feature-specific sub-modules.

All public symbols are imported from the sub-modules below so
that existing ``from src.data import loader`` call-sites
continue to work unchanged.

Sub-modules:
    ``_base``            -- shared JSON loading helpers
    ``tracker_loader``   -- scripts, cookies, storage, domains,
                           CNAME, Disconnect
    ``partner_loader``   -- partner databases, category config
    ``consent_loader``   -- TCF, GVL, GDPR, ATP, consent platforms
    ``media_loader``     -- media group profiles, LLM context
    ``domain_info``      -- cross-category domain descriptions,
                           storage key hints
"""

from __future__ import annotations

# Re-export every public symbol explicitly so mypy recognises them.
# Using ``import X as X`` makes each name a public re-export in mypy's
# eyes without requiring a module-level ``__all__``.
from src.data._base import _load_json as _load_json
from src.data.consent_loader import get_consent_cookies as get_consent_cookies
from src.data.consent_loader import get_gdpr_reference as get_gdpr_reference
from src.data.consent_loader import (
    get_google_atp_providers as get_google_atp_providers,
)
from src.data.consent_loader import get_gvl_vendor_details as get_gvl_vendor_details
from src.data.consent_loader import get_gvl_vendors as get_gvl_vendors
from src.data.consent_loader import get_tcf_purposes as get_tcf_purposes
from src.data.consent_loader import load_consent_platforms as load_consent_platforms
from src.data.domain_info import get_domain_description as get_domain_description
from src.data.domain_info import get_storage_key_hint as get_storage_key_hint
from src.data.media_loader import build_media_group_context as build_media_group_context
from src.data.media_loader import (
    find_media_group_by_domain as find_media_group_by_domain,
)
from src.data.media_loader import get_media_groups as get_media_groups
from src.data.partner_loader import PARTNER_CATEGORIES as PARTNER_CATEGORIES
from src.data.partner_loader import get_partner_database as get_partner_database
from src.data.tracker_loader import build_disconnect_context as build_disconnect_context
from src.data.tracker_loader import (
    build_tracking_cookie_context as build_tracking_cookie_context,
)
from src.data.tracker_loader import get_benign_scripts as get_benign_scripts
from src.data.tracker_loader import get_cname_domains as get_cname_domains
from src.data.tracker_loader import get_cname_target as get_cname_target
from src.data.tracker_loader import get_disconnect_category as get_disconnect_category
from src.data.tracker_loader import get_disconnect_services as get_disconnect_services
from src.data.tracker_loader import get_tracker_domains as get_tracker_domains
from src.data.tracker_loader import (
    get_tracking_cookie_patterns as get_tracking_cookie_patterns,
)
from src.data.tracker_loader import (
    get_tracking_cookie_privacy_map as get_tracking_cookie_privacy_map,
)
from src.data.tracker_loader import (
    get_tracking_cookie_risk_map as get_tracking_cookie_risk_map,
)
from src.data.tracker_loader import (
    get_tracking_cookie_vendor_index as get_tracking_cookie_vendor_index,
)
from src.data.tracker_loader import get_tracking_cookies as get_tracking_cookies
from src.data.tracker_loader import get_tracking_scripts as get_tracking_scripts
from src.data.tracker_loader import (
    get_tracking_storage_keys as get_tracking_storage_keys,
)
from src.data.tracker_loader import (
    get_tracking_storage_patterns as get_tracking_storage_patterns,
)
from src.data.tracker_loader import (
    get_tracking_storage_privacy_map as get_tracking_storage_privacy_map,
)
from src.data.tracker_loader import (
    get_tracking_storage_risk_map as get_tracking_storage_risk_map,
)
from src.data.tracker_loader import (
    get_tracking_storage_vendor_index as get_tracking_storage_vendor_index,
)
from src.data.tracker_loader import (
    is_known_tracker_domain as is_known_tracker_domain,
)
