from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from resume_tailor_harness.models.evidence_portfolio import (
    EvidenceCatalog,
    EvidenceExcerpt,
    EvidenceFactCandidate,
    EvidenceOwnerCandidate,
    EvidencePortfolio,
    PortfolioOmission,
    PortfolioRequirement,
    PortfolioSelection,
)
from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.models.profile import Experience, ProfileFacts, Project, Skill
from resume_tailor_harness.profile.matrix import SkillMatch, SkillMatchContext
from resume_tailor_harness.tailor.provenance import index_facts, renderable_profile
from resume_tailor_harness.tailor.numeric_evidence import claim_numbers
from resume_tailor_harness.tailor.review_config import LengthBudget
from resume_tailor_harness.llm_runner import Runner
from resume_tailor_harness.tailor.length import format_budget
from resume_tailor_harness.tailor.portfolio_planner import (
    aplan_evidence_portfolio,
    compose_evidence_portfolio_input,
    plan_evidence_portfolio,
)
from resume_tailor_harness.tracking.match_gap import normalize_skill


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortfolioPlanRequest:
    jd_text: str
    criteria: JobCriteria
    profile_facts: ProfileFacts
    skill_context: SkillMatchContext | None
    budget: LengthBudget


def _fallback_warning(error: Exception | None) -> str:
    reason = type(error).__name__ if error is not None else "planner unavailable"
    return f"Evidence planner unavailable ({reason}); deterministic fallback used."


def _portfolio_is_usable(portfolio: EvidencePortfolio, owner_ids: set[str]) -> bool:
    return bool(portfolio.selections) and any(
        selection.owner_id in owner_ids for selection in portfolio.selections
    )


_KNOWN_SECTIONS = {
    "summary",
    "experience",
    "education",
    "projects",
    "skills",
    "publications",
    "certifications",
    "awards",
    "languages",
    "volunteer",
}


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _project_text(project: Project) -> str:
    return "; ".join(
        value
        for value in (
            project.name,
            project.description or "",
            ", ".join(project.tech),
            "; ".join(highlight.text for highlight in project.highlights),
        )
        if value
    )


def _match_fact_ids(match: SkillMatch) -> set[str]:
    return set(match.row.evidence_fact_ids) if match.row is not None else set()


def _requirements_for_ids(
    fact_ids: set[str],
    context: SkillMatchContext | None,
    coverage: str,
    source: str | None = None,
) -> list[str]:
    if context is None:
        return []
    return _unique(
        match.requirement
        for match in context.matches
        if match.coverage == coverage
        and (source is None or match.source == source)
        and fact_ids & _match_fact_ids(match)
    )


def build_evidence_catalog(
    facts: ProfileFacts,
    criteria: JobCriteria,
    context: SkillMatchContext | None,
) -> EvidenceCatalog:
    """Index selectable work/project evidence with deterministic JD signals."""
    del criteria  # requirements are already represented by the authoritative context
    owners: list[EvidenceOwnerCandidate] = []
    for source_order, experience in enumerate(facts.experience):
        owner_ids = {experience.id, *(bullet.id for bullet in experience.bullets)}
        fact_candidates = []
        for fact_order, bullet in enumerate(experience.bullets):
            ids = {bullet.id}
            fact_candidates.append(
                EvidenceFactCandidate(
                    fact_id=bullet.id,
                    text=bullet.text,
                    source_order=fact_order,
                    metric_count=len(claim_numbers(bullet.text)),
                    direct_must_requirements=_requirements_for_ids(
                        ids, context, "covered", "must"
                    ),
                    direct_requirements=_requirements_for_ids(ids, context, "covered"),
                    adjacent_requirements=_requirements_for_ids(
                        ids, context, "adjacent"
                    ),
                )
            )
        direct = _requirements_for_ids(owner_ids, context, "covered")
        adjacent = _requirements_for_ids(owner_ids, context, "adjacent")
        strength = sum(
            match.row.strength
            for match in (context.matches if context else [])
            if match.row is not None
            and match.requirement in direct
            and owner_ids & set(match.row.evidence_fact_ids)
        )
        owners.append(
            EvidenceOwnerCandidate(
                owner_id=experience.id,
                owner_kind="experience",
                label=f"{experience.company} — {experience.title}",
                start=experience.start,
                end=experience.end,
                current=experience.current,
                source_order=source_order,
                strength=round(strength, 2),
                direct_must_requirements=_requirements_for_ids(
                    owner_ids, context, "covered", "must"
                ),
                direct_requirements=direct,
                adjacent_requirements=adjacent,
                facts=fact_candidates,
            )
        )

    project_offset = len(facts.experience)
    for source_order, project in enumerate(facts.projects):
        text = _project_text(project)
        ids = {project.id}
        direct = _requirements_for_ids(ids, context, "covered")
        adjacent = _requirements_for_ids(ids, context, "adjacent")
        strength = sum(
            match.row.strength
            for match in (context.matches if context else [])
            if match.row is not None
            and match.requirement in direct
            and project.id in match.row.evidence_fact_ids
        )
        owners.append(
            EvidenceOwnerCandidate(
                owner_id=project.id,
                owner_kind="project",
                label=project.name,
                start=project.start,
                end=project.end or project.last_updated,
                source_order=project_offset + source_order,
                strength=round(strength, 2),
                suggested_bullet_count=max(
                    1,
                    len(project.highlights) or int(bool(project.description)),
                ),
                direct_must_requirements=_requirements_for_ids(
                    ids, context, "covered", "must"
                ),
                direct_requirements=direct,
                adjacent_requirements=adjacent,
                facts=[
                    EvidenceFactCandidate(
                        fact_id=project.id,
                        text=text,
                        metric_count=len(claim_numbers(text)),
                        direct_must_requirements=_requirements_for_ids(
                            ids, context, "covered", "must"
                        ),
                        direct_requirements=direct,
                        adjacent_requirements=adjacent,
                    )
                ],
            )
        )
    return EvidenceCatalog(owners=owners)


def _owner_rank(owner: EvidenceOwnerCandidate) -> tuple:
    metric_count = sum(fact.metric_count for fact in owner.facts)
    date = owner.end or owner.start or ""
    return (
        len(owner.direct_must_requirements),
        len(owner.direct_requirements),
        len(owner.adjacent_requirements),
        metric_count,
        owner.current,
        date,
        owner.strength,
        -owner.source_order,
    )


def _fact_rank(fact: EvidenceFactCandidate) -> tuple:
    return (
        len(fact.direct_must_requirements),
        len(fact.direct_requirements),
        len(fact.adjacent_requirements),
        fact.metric_count,
        -fact.source_order,
    )


def _context_match(text: str, context: SkillMatchContext | None) -> SkillMatch | None:
    token = normalize_skill(text)
    return next(
        (
            match
            for match in (context.matches if context else [])
            if normalize_skill(match.requirement) == token
        ),
        None,
    )


def _skill_index(facts: ProfileFacts) -> dict[str, Skill]:
    renderable = renderable_profile(facts)
    return {
        skill.id: skill for entries in renderable.skills.values() for skill in entries
    }


def _approved_skill_terms(
    match: SkillMatch | None, skill_by_id: dict[str, Skill]
) -> list[str]:
    if match is None or match.coverage != "covered" or match.row is None:
        return []
    terms = [match.row.display, *match.row.aliases]
    for fact_id in match.row.evidence_fact_ids:
        skill = skill_by_id.get(fact_id)
        if skill is not None:
            terms.extend([skill.name, *skill.aliases])
    return _unique(terms)


def _authoritative_requirements(
    draft: EvidencePortfolio,
    facts: ProfileFacts,
    criteria: JobCriteria,
    context: SkillMatchContext | None,
) -> list[PortfolioRequirement]:
    valid_ids = set(index_facts(facts))
    skill_by_id = _skill_index(facts)
    drafted = {normalize_skill(req.text): req for req in draft.requirements}
    requirements: list[PortfolioRequirement] = []
    seen: set[str] = set()

    fields = (
        (criteria.must_have_skills, True),
        (criteria.nice_to_have_skills, False),
        (criteria.tech_stack, False),
    )
    source_index = 0
    for values, is_core_source in fields:
        for text in values:
            token = normalize_skill(text)
            if not token or token in seen:
                continue
            seen.add(token)
            source_index += 1
            supplied = drafted.get(token)
            match = _context_match(text, context)
            coverage = match.coverage if match is not None else "gap"
            supporting = (
                [
                    fact_id
                    for fact_id in match.row.evidence_fact_ids
                    if fact_id in valid_ids
                ]
                if match is not None and match.row is not None and coverage == "covered"
                else []
            )
            approved = _approved_skill_terms(match, skill_by_id)
            requirements.append(
                PortfolioRequirement(
                    text=text,
                    kind="skill",
                    priority=supplied.priority if supplied else source_index,
                    coverage=coverage,
                    supporting_fact_ids=_unique(supporting),
                    approved_terms=approved,
                    core=is_core_source,
                    rationale=supplied.rationale if supplied else "",
                )
            )

    # The planner may add material responsibilities or seniority expectations.
    # They are retained only when backed by known facts; they never become
    # highlighted skill terms.
    for supplied in sorted(draft.requirements, key=lambda item: item.priority):
        token = normalize_skill(supplied.text)
        if not token or token in seen or supplied.kind == "skill":
            continue
        supporting = _unique(
            fact_id for fact_id in supplied.supporting_fact_ids if fact_id in valid_ids
        )
        seen.add(token)
        requirements.append(
            supplied.model_copy(
                update={
                    "coverage": "covered" if supporting else "gap",
                    "supporting_fact_ids": supporting,
                    "approved_terms": [],
                    "core": False,
                }
            )
        )

    coverage_order = {"covered": 0, "adjacent": 1, "gap": 2}
    return sorted(
        requirements,
        key=lambda item: (
            0 if item.core else 1,
            coverage_order[item.coverage],
            item.priority,
        ),
    )


def _core_skill_ids(
    requirements: list[PortfolioRequirement], facts: ProfileFacts
) -> list[str]:
    skill_by_id = _skill_index(facts)
    return _unique(
        fact_id
        for requirement in requirements[:]
        if requirement.kind == "skill" and requirement.core
        for fact_id in requirement.supporting_fact_ids
        if fact_id in skill_by_id
    )


def _highlight_terms(requirements: list[PortfolioRequirement]) -> list[str]:
    terms: list[str] = []
    for requirement in requirements:
        if requirement.kind != "skill" or not requirement.core:
            continue
        approved_by_token = {
            normalize_skill(term): term for term in requirement.approved_terms
        }
        term = approved_by_token.get(normalize_skill(requirement.text))
        if term is not None:
            # Preserve the JD's spelling when the explicit fact vocabulary says
            # it names the same skill.
            terms.append(requirement.text)
        elif requirement.approved_terms:
            terms.append(requirement.approved_terms[0])
        if len(terms) == 5:
            break
    return _unique(terms)


def _fallback_selections(
    catalog: EvidenceCatalog, budget: LengthBudget
) -> list[PortfolioSelection]:
    selections: list[PortfolioSelection] = []
    experience_count = 0
    project_count = 0
    bridge_count = 0
    remaining = budget.target_total_bullets
    ranked = sorted(catalog.owners, key=_owner_rank, reverse=True)
    has_direct_evidence = any(owner.direct_requirements for owner in ranked)
    for owner in ranked:
        if len(selections) >= budget.max_evidence_owners or remaining <= 0:
            break
        if owner.owner_kind == "experience":
            if experience_count >= budget.max_experiences:
                continue
            bridge = has_direct_evidence and not owner.direct_requirements
            if bridge and bridge_count >= 1:
                continue
            supporting = [
                fact
                for fact in owner.facts
                if fact.direct_requirements
                or fact.adjacent_requirements
                or fact.metric_count
            ]
            candidates = sorted(supporting or owner.facts, key=_fact_rank, reverse=True)
            limit = 1 if bridge else budget.max_bullets_per_role
            selected_ids = [fact.fact_id for fact in candidates[:limit]]
            if not selected_ids:
                continue
            bullet_budget = min(len(selected_ids), remaining)
            selected_ids = selected_ids[:bullet_budget]
            experience_count += 1
            bridge_count += int(bridge)
        else:
            if project_count >= budget.max_projects:
                continue
            if has_direct_evidence and not owner.direct_requirements:
                continue
            selected_ids = [owner.owner_id]
            bullet_budget = min(
                budget.max_bullets_per_project,
                owner.suggested_bullet_count,
                remaining,
            )
            project_count += 1
        if bullet_budget <= 0:
            continue
        remaining -= bullet_budget
        selections.append(
            PortfolioSelection(
                owner_id=owner.owner_id,
                owner_kind=owner.owner_kind,
                selected_fact_ids=selected_ids,
                requirement_texts=owner.direct_requirements,
                rank=len(selections) + 1,
                bullet_budget=bullet_budget,
                bridge=(
                    owner.owner_kind == "experience"
                    and has_direct_evidence
                    and not owner.direct_requirements
                ),
                rationale=(
                    "strongest deterministic match for "
                    + ", ".join(owner.direct_requirements)
                    if owner.direct_requirements
                    else "most recent remaining evidence"
                ),
            )
        )
    return selections


def _normalized_selections(
    draft: EvidencePortfolio,
    catalog: EvidenceCatalog,
    budget: LengthBudget,
) -> list[PortfolioSelection]:
    owners = {owner.owner_id: owner for owner in catalog.owners}
    result: list[PortfolioSelection] = []
    seen: set[str] = set()
    experience_count = 0
    project_count = 0
    remaining = budget.target_total_bullets
    for selection in sorted(draft.selections, key=lambda item: item.rank):
        owner = owners.get(selection.owner_id)
        if owner is None or owner.owner_kind != selection.owner_kind:
            continue
        if owner.owner_id in seen or len(result) >= budget.max_evidence_owners:
            continue
        if owner.owner_kind == "experience":
            if experience_count >= budget.max_experiences:
                continue
            valid = {fact.fact_id for fact in owner.facts}
            selected_ids = _unique(
                fact_id for fact_id in selection.selected_fact_ids if fact_id in valid
            )
            if not selected_ids:
                selected_ids = [
                    fact.fact_id
                    for fact in sorted(owner.facts, key=_fact_rank, reverse=True)[
                        : budget.max_bullets_per_role
                    ]
                ]
            limit = 1 if selection.bridge else budget.max_bullets_per_role
            selected_ids = selected_ids[:limit]
            bullet_budget = min(selection.bullet_budget, len(selected_ids), remaining)
            selected_ids = selected_ids[:bullet_budget]
            experience_count += 1
        else:
            if project_count >= budget.max_projects:
                continue
            selected_ids = [owner.owner_id]
            bullet_budget = min(
                selection.bullet_budget,
                budget.max_bullets_per_project,
                remaining,
            )
            project_count += 1
        if bullet_budget <= 0:
            continue
        seen.add(owner.owner_id)
        remaining -= bullet_budget
        result.append(
            selection.model_copy(
                update={
                    "selected_fact_ids": selected_ids,
                    "rank": len(result) + 1,
                    "bullet_budget": bullet_budget,
                    "requirement_texts": _unique(
                        text
                        for text in selection.requirement_texts
                        if text in owner.direct_requirements
                    ),
                }
            )
        )
    return result


def _excerpts(
    selections: list[PortfolioSelection],
    omissions: list[PortfolioOmission],
    catalog: EvidenceCatalog,
) -> list[EvidenceExcerpt]:
    owners = {owner.owner_id: owner for owner in catalog.owners}
    excerpts: list[EvidenceExcerpt] = []
    for selection in selections:
        owner = owners[selection.owner_id]
        facts = {fact.fact_id: fact for fact in owner.facts}
        for fact_id in selection.selected_fact_ids:
            fact = facts.get(fact_id)
            excerpts.append(
                EvidenceExcerpt(
                    fact_id=fact_id,
                    owner_id=owner.owner_id,
                    owner_kind=owner.owner_kind,
                    text=fact.text if fact is not None else owner.label,
                )
            )
    for omission in omissions:
        owner = owners.get(omission.owner_id)
        if owner is None:
            continue
        excerpts.append(
            EvidenceExcerpt(
                fact_id=owner.owner_id,
                owner_id=owner.owner_id,
                owner_kind=owner.owner_kind,
                text=owner.label,
            )
        )
    return excerpts


def normalize_evidence_portfolio(
    draft: EvidencePortfolio,
    catalog: EvidenceCatalog,
    facts: ProfileFacts,
    criteria: JobCriteria,
    context: SkillMatchContext | None,
    budget: LengthBudget,
) -> EvidencePortfolio:
    """Turn untrusted planner output into a bounded, fact-backed portfolio."""
    requirements = _authoritative_requirements(draft, facts, criteria, context)
    selections = _normalized_selections(draft, catalog, budget)
    if not selections:
        selections = _fallback_selections(catalog, budget)

    skill_ids = _core_skill_ids(requirements, facts)
    renderable_skills = _skill_index(facts)
    allowed_skill_ids = {
        fact_id
        for requirement in requirements
        if requirement.kind == "skill" and requirement.coverage == "covered"
        for fact_id in requirement.supporting_fact_ids
        if fact_id in renderable_skills
    }
    supplied_skills = _unique(
        fact_id
        for fact_id in draft.selected_skill_fact_ids
        if fact_id in allowed_skill_ids
    )
    selected_skills = _unique([*skill_ids, *supplied_skills])

    selected_owner_ids = {selection.owner_id for selection in selections}
    owners = {owner.owner_id: owner for owner in catalog.owners}
    omissions = []
    for omission in draft.omissions:
        owner = owners.get(omission.owner_id)
        if (
            owner is None
            or owner.owner_kind != omission.owner_kind
            or owner.owner_id in selected_owner_ids
        ):
            continue
        omissions.append(omission)
        if len(omissions) == 5:
            break
    if not omissions:
        omissions = [
            PortfolioOmission(
                owner_id=owner.owner_id,
                owner_kind=owner.owner_kind,
                rationale="lower relevance or page-budget priority",
            )
            for owner in sorted(catalog.owners, key=_owner_rank, reverse=True)
            if owner.owner_id not in selected_owner_ids
        ][:5]

    section_order = _unique(
        section for section in draft.section_order if section in _KNOWN_SECTIONS
    )
    return EvidencePortfolio(
        status=draft.status,
        warning=draft.warning,
        requirements=requirements,
        selections=selections,
        selected_skill_fact_ids=selected_skills,
        highlight_terms=_highlight_terms(requirements),
        section_order=section_order,
        omissions=omissions,
        evidence_excerpts=_excerpts(selections, omissions, catalog),
    )


def build_fallback_portfolio(
    catalog: EvidenceCatalog,
    facts: ProfileFacts,
    criteria: JobCriteria,
    context: SkillMatchContext | None,
    budget: LengthBudget,
    warning: str | None = None,
) -> EvidencePortfolio:
    draft = EvidencePortfolio(
        status="deterministic_fallback",
        warning=warning,
        selections=_fallback_selections(catalog, budget),
    )
    return normalize_evidence_portfolio(
        draft, catalog, facts, criteria, context, budget
    )


def plan_portfolio(
    request: PortfolioPlanRequest,
    planner: Runner | None,
) -> EvidencePortfolio:
    """Return one validated plan or a deterministic fallback.

    The caller supplies intent and a planner adapter; catalog construction,
    untrusted-output validation, normalization, and fallback stay behind this
    lifecycle seam.
    """

    catalog = build_evidence_catalog(
        request.profile_facts, request.criteria, request.skill_context
    )
    if planner is not None:
        try:
            draft = plan_evidence_portfolio(
                compose_evidence_portfolio_input(
                    request.jd_text,
                    request.criteria,
                    catalog,
                    budget=format_budget(request.budget),
                ),
                planner,
            )
            if not _portfolio_is_usable(
                draft, {owner.owner_id for owner in catalog.owners}
            ):
                raise ValueError("planner returned no usable owner selection")
            draft = draft.model_copy(update={"status": "planned", "warning": None})
            return normalize_evidence_portfolio(
                draft,
                catalog,
                request.profile_facts,
                request.criteria,
                request.skill_context,
                request.budget,
            )
        except Exception as error:
            logger.warning(
                "evidence portfolio planner failed; using fallback", exc_info=error
            )
            warning = _fallback_warning(error)
    else:
        warning = _fallback_warning(None)
    return build_fallback_portfolio(
        catalog,
        request.profile_facts,
        request.criteria,
        request.skill_context,
        request.budget,
        warning=warning,
    )


async def aplan_portfolio(
    request: PortfolioPlanRequest,
    planner: Runner | None,
    *,
    sem: asyncio.Semaphore,
) -> EvidencePortfolio:
    """Async adapter for the same validated Evidence portfolio lifecycle."""

    catalog = build_evidence_catalog(
        request.profile_facts, request.criteria, request.skill_context
    )
    if planner is not None:
        try:
            draft = await aplan_evidence_portfolio(
                compose_evidence_portfolio_input(
                    request.jd_text,
                    request.criteria,
                    catalog,
                    budget=format_budget(request.budget),
                ),
                planner,
                sem=sem,
            )
            if not _portfolio_is_usable(
                draft, {owner.owner_id for owner in catalog.owners}
            ):
                raise ValueError("planner returned no usable owner selection")
            draft = draft.model_copy(update={"status": "planned", "warning": None})
            return normalize_evidence_portfolio(
                draft,
                catalog,
                request.profile_facts,
                request.criteria,
                request.skill_context,
                request.budget,
            )
        except Exception as error:
            logger.warning(
                "evidence portfolio planner failed; using fallback", exc_info=error
            )
            warning = _fallback_warning(error)
    else:
        warning = _fallback_warning(None)
    return build_fallback_portfolio(
        catalog,
        request.profile_facts,
        request.criteria,
        request.skill_context,
        request.budget,
        warning=warning,
    )


def portfolio_profile(
    facts: ProfileFacts, portfolio: EvidencePortfolio
) -> ProfileFacts:
    """Prune only selectable work/project/skill facts for generation."""
    selections = {selection.owner_id: selection for selection in portfolio.selections}
    source_order = {
        experience.id: index for index, experience in enumerate(facts.experience)
    }
    experiences: list[Experience] = []
    selected_experiences = [
        experience
        for experience in facts.experience
        if experience.id in selections
        and selections[experience.id].owner_kind == "experience"
    ]
    selected_experiences.sort(
        key=lambda experience: (
            experience.current,
            experience.end or experience.start or "",
            experience.start or "",
            -source_order[experience.id],
        ),
        reverse=True,
    )
    for experience in selected_experiences:
        selection = selections.get(experience.id)
        if selection is None or selection.owner_kind != "experience":
            continue
        selected = set(selection.selected_fact_ids)
        experiences.append(
            experience.model_copy(
                deep=True,
                update={
                    "bullets": [
                        bullet.model_copy(deep=True)
                        for bullet in experience.bullets
                        if bullet.id in selected
                    ]
                },
            )
        )
    selected_projects = [
        project
        for project in facts.projects
        if project.id in selections and selections[project.id].owner_kind == "project"
    ]
    selected_projects.sort(key=lambda project: selections[project.id].rank)
    projects = [project.model_copy(deep=True) for project in selected_projects]
    selected_skills = set(portfolio.selected_skill_fact_ids)
    skills = {
        category: [
            skill.model_copy(deep=True)
            for skill in entries
            if skill.id in selected_skills
        ]
        for category, entries in renderable_profile(facts).skills.items()
    }
    skills = {category: entries for category, entries in skills.items() if entries}
    return facts.model_copy(
        deep=True,
        update={"experience": experiences, "projects": projects, "skills": skills},
    )
