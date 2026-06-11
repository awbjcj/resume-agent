import json
from collections.abc import Mapping
from typing import Any

from resume_agent.llm_runner import Runner
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.length import resume_stats
from resume_agent.tailor.provenance import resolve_evidence
from resume_agent.tailor.review_config import ReviewConfig


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
    result = agent.run(input_text)
    critique = result.content
    if not isinstance(critique, ReviewCritique):
        raise TypeError(f"Expected ReviewCritique from reviewer, got {type(critique).__name__}")
    return critique


def run_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
) -> list[ReviewCritique]:
    """Run configured reviewers with the smallest sufficient input per role."""
    evidence = resolve_evidence(content, profile_facts)
    stats = resume_stats(content)
    critiques: list[ReviewCritique] = []
    for spec in config.reviewers:
        if spec.gate:
            text = compose_evidence_review_input(content, jd_text, evidence)
        else:
            text = compose_lean_review_input(content, jd_text, stats)
        critiques.append(review_one(text, reviewer_agents[spec.name]))
    return critiques
