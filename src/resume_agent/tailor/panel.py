import asyncio
import json
from collections.abc import Coroutine, Mapping
from typing import Any

from resume_agent.llm_runner import Runner, acall, expect_schema
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import MergedPanelReview, ReviewCritique
from resume_agent.tailor.length import resume_stats
from resume_agent.tailor.provenance import resolve_evidence
from resume_agent.tailor.review_config import ReviewConfig

MERGED_ADVISORY = "advisory-panel"


def split_merged_critiques(
    review: MergedPanelReview, expected: list[str]
) -> list[ReviewCritique]:
    """Require exact unique coverage, then restore configured reviewer order."""
    received = [critique.reviewer for critique in review.critiques]
    if len(received) != len(set(received)) or sorted(received) != sorted(expected):
        raise ValueError(
            f"Merged advisory review must cover exactly {expected!r}, got {received!r}"
        )
    by_name = {critique.reviewer: critique for critique in review.critiques}
    return [by_name[name] for name in expected]


def compose_lean_review_input(content: ResumeContent, jd_text: str, stats: str) -> str:
    """Input for non-gate reviewers: resume + JD + size stats. No raw profile."""
    return (
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "RESUME STATS:\n"
        f"{stats}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def compose_evidence_review_input(
    content: ResumeContent, jd_text: str, evidence: Mapping[str, Any]
) -> str:
    """Input for gate reviewers: resume + JD + only referenced facts."""
    return (
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "SUPPORTING FACTS (the only profile facts this resume cites, keyed by id):\n"
        f"{json.dumps(evidence)}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def review_one(input_text: str, agent: Runner) -> ReviewCritique:
    return expect_schema(agent.run(input_text), ReviewCritique, source="reviewer")


def run_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
) -> list[ReviewCritique]:
    """Run configured reviewers with the smallest sufficient input per role."""
    if not config.merged_advisory:
        return [
            review_one(text, reviewer_agents[name])
            for name, text in _panel_inputs(content, profile_facts, jd_text, config)
        ]

    evidence = resolve_evidence(content, profile_facts)
    critiques = [
        review_one(
            compose_evidence_review_input(content, jd_text, evidence),
            reviewer_agents[spec.name],
        )
        for spec in config.reviewers
        if spec.gate
    ]
    advisory_names = _advisory_names(config)
    if advisory_names:
        result = reviewer_agents[MERGED_ADVISORY].run(
            compose_lean_review_input(content, jd_text, resume_stats(content))
        )
        critiques.extend(_merged_review(result, advisory_names))
    return critiques


def _advisory_names(config: ReviewConfig) -> list[str]:
    return [spec.name for spec in config.reviewers if not spec.gate]


def _merged_review(result: Any, expected: list[str]) -> list[ReviewCritique]:
    """Takes the whole run result, not just its content, so a parse failure can
    report the provider diagnostics that say why it did not parse."""
    review = expect_schema(result, MergedPanelReview, source="merged advisory")
    return split_merged_critiques(review, expected)


def _panel_inputs(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
) -> list[tuple[str, str]]:
    """(reviewer_name, input_text) pairs, smallest sufficient input per role."""
    evidence = resolve_evidence(content, profile_facts)
    stats = resume_stats(content)
    inputs: list[tuple[str, str]] = []
    for spec in config.reviewers:
        if spec.gate:
            text = compose_evidence_review_input(content, jd_text, evidence)
        else:
            text = compose_lean_review_input(content, jd_text, stats)
        inputs.append((spec.name, text))
    return inputs


async def areview_one(
    input_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> ReviewCritique:
    result = await acall(agent, input_text, sem=sem)
    return expect_schema(result, ReviewCritique, source="reviewer")


async def arun_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
    *,
    sem: asyncio.Semaphore,
) -> list[ReviewCritique]:
    """Run configured reviewers concurrently; results stay in reviewer order."""
    if not config.merged_advisory:
        inputs = _panel_inputs(content, profile_facts, jd_text, config)
        outputs = await asyncio.gather(
            *(areview_one(text, reviewer_agents[name], sem=sem) for name, text in inputs),
            return_exceptions=True,
        )
        return _settled_critiques(outputs)

    evidence = resolve_evidence(content, profile_facts)
    gate_specs = [spec for spec in config.reviewers if spec.gate]
    advisory_names = _advisory_names(config)
    calls: list[Coroutine[Any, Any, Any]] = [
        areview_one(
            compose_evidence_review_input(content, jd_text, evidence),
            reviewer_agents[spec.name],
            sem=sem,
        )
        for spec in gate_specs
    ]
    if advisory_names:
        calls.append(
            acall(
                reviewer_agents[MERGED_ADVISORY],
                compose_lean_review_input(content, jd_text, resume_stats(content)),
                sem=sem,
            )
        )
    outputs = await asyncio.gather(*calls, return_exceptions=True)
    critiques: list[ReviewCritique] = []
    first_error: BaseException | None = None
    for index, output in enumerate(outputs):
        if isinstance(output, BaseException):
            first_error = first_error or output
        elif advisory_names and index == len(gate_specs):
            try:
                critiques.extend(_merged_review(output, advisory_names))
            except (TypeError, ValueError) as exc:
                first_error = first_error or exc
        else:
            critiques.append(output)
    if first_error is not None:
        raise first_error
    return critiques


def _settled_critiques(
    outputs: list[ReviewCritique | BaseException],
) -> list[ReviewCritique]:
    critiques: list[ReviewCritique] = []
    first_error: BaseException | None = None
    for output in outputs:
        if isinstance(output, BaseException):
            first_error = first_error or output
        else:
            critiques.append(output)
    if first_error is not None:
        raise first_error
    return critiques
