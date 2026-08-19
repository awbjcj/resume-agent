"""Central agent-bundle builders.

These were previously inlined in cli.py. Keeping them here lets the CLI, the API,
and any future adapter build the same agent sets the same way. Imports of the
concrete `build_*_agent` functions are module-level so tests can monkeypatch them.
"""

from dataclasses import dataclass
from typing import Mapping

from resume_agent.config import get_settings
from resume_agent.cover_letter.agents import (
    build_cover_letter_agent,
    build_cover_letter_revision_agent,
    build_cover_letter_reviser_agent,
)
from resume_agent.career_skills.models import (
    AgentFamily,
    CoverLetterSkillName,
    ResumeAuthoringSkillName,
)
from resume_agent.career_skills.registry import CareerSkillRegistry, VerifiedSkill
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.industry import build_industry_classifier
from resume_agent.discovery.relevance import build_relevance_agent
from resume_agent.discovery.url_ingest.llm import build_url_extract_agent
from resume_agent.llm_runner import Runner
from resume_agent.tailor.agents import (
    build_merged_advisory_agent,
    build_reviewer_agent,
    build_revision_agent,
    build_reviser_agent,
    build_tailor_agent,
    model_for_tier,
)
from resume_agent.tailor.match_plan import build_match_plan_agent
from resume_agent.tailor.portfolio_planner import build_evidence_portfolio_agent
from resume_agent.tailor.panel import MERGED_ADVISORY
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
from resume_agent.tracking.match_gap import Canonicalizer
from resume_agent.taxonomy.term_assistant import (
    ModelTermTypeAssistant,
    build_term_type_assistant,
)


@dataclass
class DiscoveryBundle:
    extract: Runner
    fit: Runner
    relevance: Runner | None
    canonicalizer: Canonicalizer | None
    industry_classifier: Runner
    term_type_assistant: ModelTermTypeAssistant | None = None


@dataclass
class TailorBundle:
    tailor: Runner
    reviser: Runner
    reviewers: Mapping[str, Runner]
    revision: Runner
    match_plan: Runner | None = None
    evidence_portfolio: Runner | None = None


@dataclass
class CoverLetterBundle:
    draft: Runner
    reviser: Runner
    revision: Runner


def build_discovery_bundle(
    *, registry: CareerSkillRegistry | None = None
) -> DiscoveryBundle:
    if registry is None:
        extract = build_extract_agent()
        fit = build_fit_agent()
    else:
        extract = build_extract_agent(
            skill=registry.require(
                "job-description-analyzer",
                family=AgentFamily.JOB_ANALYSIS,
                use="extract",
            )
        )
        fit = build_fit_agent(
            skill=registry.require(
                "job-fit-analyzer", family=AgentFamily.JOB_ANALYSIS, use="fit"
            )
        )
    return DiscoveryBundle(
        extract=extract,
        fit=fit,
        relevance=build_relevance_agent(),
        canonicalizer=build_skill_canonicalizer(),
        industry_classifier=build_industry_classifier(),
        term_type_assistant=(
            build_term_type_assistant()
            if get_settings().career_capability_mode != "legacy"
            else None
        ),
    )


def build_tailor_bundle(
    config,
    style_guide: str | None = None,
    *,
    authoring_skill: ResumeAuthoringSkillName | str | None = None,
    registry: CareerSkillRegistry | None = None,
) -> TailorBundle:
    selected_authoring: VerifiedSkill | None = None
    selected_revision: VerifiedSkill | None = None
    if authoring_skill is not None or registry is not None:
        registry = registry or CareerSkillRegistry.from_settings(get_settings())
        selected_name = (
            authoring_skill.value
            if isinstance(authoring_skill, ResumeAuthoringSkillName)
            else authoring_skill or "resume-customizer"
        )
        selected_authoring = registry.require(
            selected_name, family=AgentFamily.RESUME_AUTHORING, use="tailor"
        )
        selected_revision = registry.require(
            "resume-version-manager", family=AgentFamily.RESUME_REVIEW, use="revision"
        )
    reviewers = {}
    merged = bool(getattr(config, "merged_advisory", False))
    for spec in config.reviewers:
        if merged and not spec.gate:
            continue
        kwargs = {
            "style_guide": style_guide,
            "score_bands": bool(getattr(spec, "score_bands", False)),
        }
        if registry is not None:
            mapped = {
                "ats-keyword": "ats-resume-checker",
                "recruiter": "resume-ats-optimizer",
                "concision": "resume-formatter",
            }.get(spec.name)
            if mapped:
                kwargs["skill"] = registry.require(
                    mapped, family=AgentFamily.RESUME_REVIEW, use="review"
                )
        reviewers[spec.name] = build_reviewer_agent(
            spec.name, model_for_tier(spec.model_tier), **kwargs
        )
    if merged:
        advisory_specs = [spec for spec in config.reviewers if not spec.gate]
        if advisory_specs:
            reviewers[MERGED_ADVISORY] = build_merged_advisory_agent(
                [spec.name for spec in advisory_specs],
                model_for_tier("mid"),
                style_guide=style_guide,
                score_bands={
                    spec.name: bool(getattr(spec, "score_bands", False))
                    for spec in advisory_specs
                },
            )
    tailor_model_id = model_for_tier(getattr(config, "tailor_tier", "premium"))
    reviser_model_id = model_for_tier(getattr(config, "reviser_tier", "premium"))
    if selected_authoring is None:
        tailor = build_tailor_agent(
            model_id=tailor_model_id,
            style_guide=style_guide,
        )
        reviser = build_reviser_agent(
            model_id=reviser_model_id,
            style_guide=style_guide,
        )
    else:
        tailor = build_tailor_agent(
            model_id=tailor_model_id,
            style_guide=style_guide,
            skill=selected_authoring,
        )
        reviser = build_reviser_agent(
            model_id=reviser_model_id,
            style_guide=style_guide,
            skill=selected_authoring,
        )

    if selected_revision is None:
        revision = build_revision_agent(style_guide=style_guide)
    else:
        revision = build_revision_agent(
            style_guide=style_guide,
            skill=selected_revision,
        )

    portfolio_enabled = bool(
        getattr(config, "portfolio_enabled", False)
        or getattr(config, "evidence_portfolio_enabled", False)
        or getattr(config, "match_plan_enabled", False)
    )
    portfolio_agent = (
        build_evidence_portfolio_agent(style_guide=style_guide)
        if portfolio_enabled
        else None
    )
    return TailorBundle(
        tailor=tailor,
        reviser=reviser,
        reviewers=reviewers,
        revision=revision,
        # One-release runtime alias for adapters that still read `match_plan`.
        match_plan=portfolio_agent,
        evidence_portfolio=portfolio_agent,
    )


def build_cover_letter_bundle(
    *,
    skill: CoverLetterSkillName | str | None = None,
    registry: CareerSkillRegistry | None = None,
) -> CoverLetterBundle:
    if skill is None and registry is None:
        return CoverLetterBundle(
            draft=build_cover_letter_agent(),
            reviser=build_cover_letter_reviser_agent(),
            revision=build_cover_letter_revision_agent(),
        )
    registry = registry or CareerSkillRegistry.from_settings(get_settings())
    selected_name = (
        skill.value
        if isinstance(skill, CoverLetterSkillName)
        else skill or "cover-letter-generator"
    )
    selected = registry.require(
        selected_name, family=AgentFamily.COVER_LETTER, use="draft"
    )
    return CoverLetterBundle(
        draft=build_cover_letter_agent(skill=selected),
        reviser=build_cover_letter_reviser_agent(),
        revision=build_cover_letter_revision_agent(),
    )


__all__ = [
    "DiscoveryBundle",
    "TailorBundle",
    "CoverLetterBundle",
    "build_discovery_bundle",
    "build_tailor_bundle",
    "build_cover_letter_bundle",
    "build_url_extract_agent",
    # re-exported so tests can monkeypatch them on this module:
    "build_extract_agent",
    "build_fit_agent",
    "build_relevance_agent",
    "build_industry_classifier",
    "build_tailor_agent",
    "build_reviser_agent",
    "build_revision_agent",
    "build_reviewer_agent",
    "build_merged_advisory_agent",
    "build_match_plan_agent",
    "build_evidence_portfolio_agent",
    "build_cover_letter_agent",
    "build_cover_letter_reviser_agent",
    "build_cover_letter_revision_agent",
    "model_for_tier",
    "build_skill_canonicalizer",
]
