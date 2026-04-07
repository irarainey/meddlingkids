"""MAF Workflow for structured report generation.

Replaces manual ``asyncio.gather()`` with a typed
``WorkflowBuilder`` fan-out / fan-in pattern.  Ten section
executors run concurrently and their results are aggregated
by a merge executor that applies deterministic overrides.

Usage::

    from src.agents.report_workflow import run_report_workflow

    report = await run_report_workflow(agent, input_data)
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING

import agent_framework
import pydantic

from src.agents import context_builder
from src.agents.prompts import structured_report
from src.models import analysis, consent, report
from src.utils import logger

if TYPE_CHECKING:
    from src.agents import structured_report_agent as sra_mod
    from src.analysis import domain_cache

log = logger.create_logger("ReportWorkflow")


# ── Workflow data types ─────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ReportInput:
    """Input broadcast to all section executors."""

    tracking_summary: analysis.TrackingSummary
    consent_details: consent.ConsentDetails | None = None
    pre_consent_stats: analysis.PreConsentStats | None = None
    score_breakdown: analysis.ScoreBreakdown | None = None
    domain_knowledge: domain_cache.DomainKnowledge | None = None


@dataclasses.dataclass
class SectionResult:
    """Output from a single section executor."""

    section_name: str
    data: pydantic.BaseModel | None


# ── Section configuration ───────────────────────────────────────

# Maps section name → (system prompt, response model class)
_SECTION_CONFIGS: list[tuple[str, str, type[pydantic.BaseModel]]] = []


def _init_section_configs() -> list[tuple[str, str, type[pydantic.BaseModel]]]:
    """Lazily build section configs to avoid circular imports."""
    # Import the module (not individual classes) to comply
    # with Google import style.  Accessed via module attribute.
    from src.agents import structured_report_agent as sra  # noqa: important[misplaced-import]

    return [
        ("tracking-technologies", structured_report.TRACKING_TECH, sra._TrackingTechResponse),
        ("data-collection", structured_report.DATA_COLLECTION, sra._DataCollectionResponse),
        ("third-party-services", structured_report.THIRD_PARTY, sra._ThirdPartyResponse),
        ("cookie-analysis", structured_report.COOKIE_ANALYSIS, sra._CookieAnalysisResponse),
        ("storage-analysis", structured_report.STORAGE_ANALYSIS, sra._StorageAnalysisResponse),
        ("privacy-risk", structured_report.PRIVACY_RISK, sra._PrivacyRiskResponse),
        ("consent-analysis", structured_report.CONSENT_ANALYSIS, sra._ConsentAnalysisResponse),
        ("consent-digest", structured_report.CONSENT_DIGEST, sra._ConsentDigestResponse),
        ("social-media-implications", structured_report.SOCIAL_MEDIA_IMPLICATIONS, sra._SocialMediaImplicationsResponse),
        ("recommendations", structured_report.RECOMMENDATIONS, sra._RecommendationsResponse),
    ]


# ── Section Executor ────────────────────────────────────────────


class SectionExecutor(agent_framework.Executor):
    """Executor that builds a single report section via LLM.

    Receives a ``ReportInput``, builds the section-specific
    data context, calls the agent's ``_build_section`` method,
    and sends a ``SectionResult`` downstream.
    """

    def __init__(
        self,
        section_name: str,
        system_prompt: str,
        response_model: type[pydantic.BaseModel],
        agent: sra_mod.StructuredReportAgent,
        *,
        skip_condition: Callable[[ReportInput], bool] | None = None,
        default_result: pydantic.BaseModel | None = None,
        social_media_trackers: list[report.TrackerEntry] | None = None,
    ) -> None:
        super().__init__(id=f"section-{section_name}")
        self._section_name = section_name
        self._system_prompt = system_prompt
        self._response_model = response_model
        self._agent = agent
        self._skip_condition = skip_condition
        self._default_result = default_result
        self._social_media_trackers = social_media_trackers

    @agent_framework.handler(input=ReportInput, output=SectionResult)
    async def process(
        self,
        data: ReportInput,
        ctx: agent_framework.WorkflowContext[SectionResult],
    ) -> None:
        """Build one report section and send the result."""
        if self._skip_condition and self._skip_condition(data):
            await ctx.send_message(
                SectionResult(
                    section_name=self._section_name,
                    data=self._default_result,
                ),
            )
            return

        data_context = context_builder.build_section_context(
            self._section_name,
            data.tracking_summary,
            consent_details=data.consent_details,
            pre_consent_stats=data.pre_consent_stats,
            score_breakdown=data.score_breakdown,
            domain_knowledge=data.domain_knowledge,
            social_media_trackers=self._social_media_trackers,
        )

        result = await self._agent._build_section(
            self._system_prompt,
            data_context,
            self._response_model,
            self._section_name,
        )

        await ctx.send_message(
            SectionResult(section_name=self._section_name, data=result),
        )


# ── Fan-out source executor ────────────────────────────────────


class BroadcastExecutor(agent_framework.Executor):
    """Receives the initial ``ReportInput`` and broadcasts it."""

    def __init__(self) -> None:
        super().__init__(id="broadcast")

    @agent_framework.handler(input=ReportInput, output=ReportInput)
    async def process(
        self,
        data: ReportInput,
        ctx: agent_framework.WorkflowContext[ReportInput],
    ) -> None:
        await ctx.send_message(data)


# ── Fan-in merge executor ──────────────────────────────────────


class MergeExecutor(agent_framework.Executor):
    """Collects all section results and yields the merged output."""

    def __init__(self) -> None:
        super().__init__(id="merge")

    @agent_framework.handler(
        input=list[SectionResult],
        output=SectionResult,
        workflow_output=list[SectionResult],
    )
    async def merge(
        self,
        sections: list[SectionResult],
        ctx: agent_framework.WorkflowContext[SectionResult, list[SectionResult]],
    ) -> None:
        await ctx.yield_output(sections)


# ── Workflow factory ────────────────────────────────────────────


def build_report_workflow(
    agent: sra_mod.StructuredReportAgent,
    consent_details: consent.ConsentDetails | None = None,
    social_media_trackers: list[report.TrackerEntry] | None = None,
) -> agent_framework.Workflow:
    """Build a workflow that generates all report sections concurrently.

    Args:
        agent: The StructuredReportAgent to use for LLM calls.
        consent_details: Consent details for conditional section
            skipping.
        social_media_trackers: Deterministic tracker entries
            for the social-media section context.

    Returns:
        A ``Workflow`` ready to run.
    """
    configs = _init_section_configs()

    def _skip_consent(data: ReportInput) -> bool:
        cd = data.consent_details
        return not cd or not (cd.categories or cd.partners or cd.claimed_partner_count)

    broadcast = BroadcastExecutor()
    merge = MergeExecutor()

    section_executors: list[SectionExecutor] = []
    for section_name, prompt, response_model in configs:
        skip: Callable[[ReportInput], bool] | None = None
        default: pydantic.BaseModel | None = None
        if section_name == "consent-analysis":
            skip = _skip_consent
            from src.agents import structured_report_agent as sra  # noqa: important[misplaced-import]

            default = sra._ConsentAnalysisResponse(section=report.ConsentAnalysisSection())
        elif section_name == "consent-digest":
            skip = _skip_consent
            from src.agents import structured_report_agent as sra  # noqa: important[misplaced-import]

            default = sra._ConsentDigestResponse(plain_language_summary="")

        section_executors.append(
            SectionExecutor(
                section_name=section_name,
                system_prompt=prompt,
                response_model=response_model,
                agent=agent,
                skip_condition=skip,
                default_result=default,
                social_media_trackers=social_media_trackers,
            ),
        )

    builder = agent_framework.WorkflowBuilder(
        start_executor=broadcast,
        name="structured-report",
        description="Generates all 10 report sections concurrently",
        output_executors=[merge],
    )
    builder.add_fan_out_edges(broadcast, section_executors)
    builder.add_fan_in_edges(section_executors, merge)

    return builder.build()


async def run_report_workflow(
    agent: sra_mod.StructuredReportAgent,
    report_input: ReportInput,
    consent_details: consent.ConsentDetails | None = None,
    social_media_trackers: list[report.TrackerEntry] | None = None,
    on_section_done: Callable[[str, int, int], None] | None = None,
) -> dict[str, pydantic.BaseModel | None]:
    """Run the report workflow and return section results.

    Args:
        agent: The StructuredReportAgent for LLM calls.
        report_input: Input data for all sections.
        consent_details: For conditional section skipping.
        social_media_trackers: Deterministic tracker entries.
        on_section_done: Optional progress callback.

    Returns:
        Dict mapping section name → parsed response wrapper.
    """
    workflow = build_report_workflow(
        agent,
        consent_details,
        social_media_trackers,
    )

    log.info("Running report workflow (10 sections concurrently)...")

    result = await workflow.run(report_input)
    outputs = result.get_outputs()

    # The merge executor yields list[SectionResult]
    all_sections: list[SectionResult] = []
    for output in outputs:
        if isinstance(output, list):
            all_sections.extend(output)
        elif isinstance(output, SectionResult):
            all_sections.append(output)

    # Build result dict and fire progress callbacks
    section_map: dict[str, pydantic.BaseModel | None] = {}
    total = len(all_sections)
    for i, section in enumerate(all_sections, 1):
        section_map[section.section_name] = section.data
        if on_section_done:
            on_section_done(section.section_name, i, total)

    return section_map
