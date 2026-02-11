"""AI-powered streaming tracking analysis service.

Orchestrates the ``TrackingAnalysisAgent`` to stream a
privacy analysis report token-by-token.  Scoring and
summary findings are handled separately by the caller.
"""

from __future__ import annotations

from collections.abc import AsyncIterable

from src import agents
from src.types import consent, tracking_data
from src.utils import logger
from src.utils import tracking_summary as tracking_summary_mod

log = logger.create_logger("AI-Analysis")


async def stream_tracking_analysis(
    cookies: list[tracking_data.TrackedCookie],
    local_storage: list[tracking_data.StorageItem],
    session_storage: list[tracking_data.StorageItem],
    network_requests: list[tracking_data.NetworkRequest],
    scripts: list[tracking_data.TrackedScript],
    analyzed_url: str,
    consent_details: consent.ConsentDetails | None = None,
) -> AsyncIterable[str]:
    """Stream the main tracking analysis token-by-token.

    Yields incremental text deltas from the
    ``TrackingAnalysisAgent``.  After the stream completes,
    callers should run the summary-findings and scoring
    steps separately.

    Args:
        cookies: Tracked cookies from the page.
        local_storage: localStorage items.
        session_storage: sessionStorage items.
        network_requests: Captured network requests.
        scripts: Tracked scripts.
        analyzed_url: The URL that was analysed.
        consent_details: Optional consent dialog info.

    Yields:
        Incremental text chunks of the analysis.
    """
    tracking_agent = agents.get_tracking_analysis_agent()

    tracking_summary = (
        tracking_summary_mod.build_tracking_summary(
            cookies,
            scripts,
            network_requests,
            local_storage,
            session_storage,
            analyzed_url,
        )
    )

    async for update in tracking_agent.analyze_stream(
        tracking_summary, consent_details
    ):
        if update.text:
            text = (
                update.text
                if isinstance(update.text, str)
                else str(update.text)
            )
            if text:
                yield text
