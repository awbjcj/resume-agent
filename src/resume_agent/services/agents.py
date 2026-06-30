"""Central agent-bundle builders.

These were previously inlined in cli.py. Keeping them here lets the CLI, the API,
and any future adapter build the same agent sets the same way. Imports of the
concrete `build_*_agent` functions are module-level so tests can monkeypatch them.
"""

from dataclasses import dataclass
from typing import Mapping

from resume_agent.cover_letter.agents import (
    build_cover_letter_agent,
    build_cover_letter_revision_agent,
    build_cover_letter_reviser_agent,
)
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.industry import build_industry_classifier
from resume_agent.discovery.relevance import build_relevance_agent
from resume_agent.discovery.url_ingest.llm import build_url_extract_agent
from resume_agent.llm_runner import Runner
from resume_agent.tailor.agents import (
    build_reviewer_agent,
    build_revision_agent,
    build_reviser_agent,
    build_tailor_agent,
    model_for_tier,
)
from resume_agent.tailor.match_plan import build_match_plan_agent
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
from resume_agent.tracking.match_gap import Canonicalizer


@dataclass
class DiscoveryBundle:
    extract: Runner
    fit: Runner
    relevance: Runner | None
    canonicalizer: Canonicalizer | None
    industry_classifier: Runner


@dataclass
class TailorBundle:
    tailor: Runner
    reviser: Runner
    reviewers: Mapping[str, Runner]
    revision: Runner
    match_plan: Runner | None = None


@dataclass
class CoverLetterBundle:
    draft: Runner
    reviser: Runner
    revision: Runner


def build_discovery_bundle() -> DiscoveryBundle:
    return DiscoveryBundle(
        extract=build_extract_agent(),
        fit=build_fit_agent(),
        relevance=build_relevance_agent(),
        canonicalizer=build_skill_canonicalizer(),
        industry_classifier=build_industry_classifier(),
    )


def build_tailor_bundle(config, style_guide: str | None = None) -> TailorBundle:
    reviewers = {}
    for spec in config.reviewers:
        kwargs = {"style_guide": style_guide}
        if getattr(spec, "score_bands", False):
            kwargs["score_bands"] = True
        reviewers[spec.name] = build_reviewer_agent(
            spec.name, model_for_tier(spec.model_tier), **kwargs
        )
    return TailorBundle(
        tailor=build_tailor_agent(style_guide=style_guide),
        reviser=build_reviser_agent(style_guide=style_guide),
        reviewers=reviewers,
        revision=build_revision_agent(style_guide=style_guide),
        match_plan=(
            build_match_plan_agent(style_guide=style_guide)
            if getattr(config, "match_plan_enabled", False)
            else None
        ),
    )


def build_cover_letter_bundle() -> CoverLetterBundle:
    return CoverLetterBundle(
        draft=build_cover_letter_agent(),
        reviser=build_cover_letter_reviser_agent(),
        revision=build_cover_letter_revision_agent(),
    )


__all__ = [
    "DiscoveryBundle", "TailorBundle", "CoverLetterBundle",
    "build_discovery_bundle", "build_tailor_bundle", "build_cover_letter_bundle",
    "build_url_extract_agent",
    # re-exported so tests can monkeypatch them on this module:
    "build_extract_agent", "build_fit_agent", "build_relevance_agent",
    "build_industry_classifier",
    "build_tailor_agent", "build_reviser_agent", "build_revision_agent", "build_reviewer_agent",
    "build_match_plan_agent",
    "build_cover_letter_agent", "build_cover_letter_reviser_agent",
    "build_cover_letter_revision_agent",
    "model_for_tier", "build_skill_canonicalizer",
]
