from typing import Any, Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts, Skill
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity

PROVENANCE_REVIEWER = "provenance"


class ProvenanceReport(ExtensibleModel):
    """Result of the deterministic provenance check."""

    ok: bool
    missing: list[str] = Field(default_factory=list)
    invalid: list[str] = Field(default_factory=list)


def index_facts(facts: ProfileFacts) -> dict[str, Any]:
    """Map every provenance-addressable fact id to its fact object."""
    index: dict[str, Any] = {}
    for exp in facts.experience:
        index[exp.id] = exp
        for bullet in exp.bullets:
            index[bullet.id] = bullet
    for proj in facts.projects:
        index[proj.id] = proj
    for skills in facts.skills.values():
        for skill in skills:
            index[skill.id] = skill
    for record in (
        *facts.education,
        *facts.publications,
        *facts.certifications,
        *facts.awards,
        *facts.languages,
        *facts.volunteer,
    ):
        index[record.id] = record
    return index


ProvenanceUse = Literal["skill", "bullet", "entity"]


def _referenced_uses(content: ResumeContent) -> list[tuple[str, ProvenanceUse]]:
    uses: list[tuple[str, ProvenanceUse]] = []
    # "entity" use, so the inferred-skill branch below rejects an inferred
    # pointer in the summary exactly as it does for a bullet.
    uses.extend((fact_id, "entity") for fact_id in content.summary_provenance)
    for exp in content.experience:
        uses.append((exp.provenance, "entity"))
        uses.extend((bullet.provenance, "bullet") for bullet in exp.bullets)
    for proj in content.projects:
        uses.append((proj.provenance, "entity"))
        uses.extend((bullet.provenance, "bullet") for bullet in proj.bullets)
    for skills in content.skills.values():
        uses.extend((skill.provenance, "skill") for skill in skills)
    uses.extend((publication.provenance, "entity") for publication in content.publications)
    uses.extend(
        (certification.provenance, "entity")
        for certification in content.certifications
    )
    uses.extend((award.provenance, "entity") for award in content.awards)
    for vol in content.volunteer:
        uses.append((vol.provenance, "entity"))
        uses.extend((bullet.provenance, "bullet") for bullet in vol.bullets)
    return uses


def referenced_ids(content: ResumeContent) -> set[str]:
    """Every provenance id the resume claims to draw from."""
    return {fact_id for fact_id, _usage in _referenced_uses(content)}


def check_provenance(content: ResumeContent, facts: ProfileFacts) -> ProvenanceReport:
    """Validate existence and the restricted use of inferred skill pointers.

    `summary_provenance` defaults to an empty list so a resume stored before the
    field existed still deserializes, but a *newly checked* round with prose in
    `summary` and nothing in `summary_provenance` is an unsupported claim the
    fact-check reviewer would otherwise never notice was missing evidence for.
    This function only runs against freshly produced content (tailor/revise
    rounds), never against stored content on load, so it can enforce the
    stricter rule without breaking legacy deserialization.
    """
    index = index_facts(facts)
    missing = sorted(fact_id for fact_id in referenced_ids(content) if fact_id not in index)
    invalid: set[str] = set()
    if content.summary and not content.summary_provenance:
        invalid.add("summary: nonempty summary has no summary_provenance ids")
    for fact_id, usage in _referenced_uses(content):
        fact = index.get(fact_id)
        if fact is None or not getattr(fact, "inferred", False):
            continue
        if usage != "skill":
            invalid.add(
                f"{fact_id}: inferred provenance is only valid for a skills-section entry"
            )
            continue
        if getattr(fact, "category", None) != "hard":
            invalid.add(f"{fact_id}: inferred soft/domain skills cannot be rendered")
        evidence_ids = getattr(fact, "evidence_fact_ids", []) or []
        if not evidence_ids:
            invalid.add(f"{fact_id}: inferred skill has no evidence_fact_ids")
            continue
        for evidence_id in evidence_ids:
            evidence = index.get(evidence_id)
            if evidence is None:
                invalid.add(
                    f"{fact_id}: inferred skill evidence not found: {evidence_id}"
                )
            elif getattr(evidence, "inferred", False):
                invalid.add(
                    f"{fact_id}: inferred skill evidence must be literal: {evidence_id}"
                )
    ordered_invalid = sorted(invalid)
    return ProvenanceReport(
        ok=not missing and not ordered_invalid,
        missing=missing,
        invalid=ordered_invalid,
    )


def provenance_critique(content: ResumeContent, facts: ProfileFacts) -> ReviewCritique:
    """The fact-lock gate as a critique: every cited id must resolve to a real fact.

    A deterministic gate — no LLM. Failing ids become blocking issues, so the
    verdict's gate logic sees provenance through the same shape as a reviewer gate.
    """
    report = check_provenance(content, facts)
    return ReviewCritique(
        reviewer=PROVENANCE_REVIEWER,
        score=100 if report.ok else 0,
        passed=report.ok,
        issues=[
            ReviewIssue(
                severity=Severity.blocking,
                message=f"provenance id not found in profile facts: {missing_id}",
            )
            for missing_id in report.missing
        ]
        + [
            ReviewIssue(
                severity=Severity.blocking,
                message=f"invalid provenance: {invalid}",
            )
            for invalid in report.invalid
        ],
    )


def renderable_profile(facts: ProfileFacts) -> ProfileFacts:
    """The writer's view of the profile: only facts it is allowed to render.

    `check_provenance` rejects an inferred soft/domain skill wherever it is
    cited, but those skills are still legal facts that the matrix and the match
    plan legitimately use. Handing them to the writer as ordinary facts and then
    failing the round for citing them makes the rule unlearnable, so the writer
    is given a profile in which the forbidden pointers simply do not exist.

    The gate keeps indexing the *full* facts, so a forbidden id arriving by any
    other route still fails. This narrows the menu; it does not relax the rule.
    """
    return facts.model_copy(
        update={
            "skills": {
                category: [
                    skill
                    for skill in skills
                    if not (skill.inferred and skill.category != "hard")
                ]
                for category, skills in facts.skills.items()
            }
        }
    )


def resolve_evidence(content: ResumeContent, facts: ProfileFacts) -> dict[str, Any]:
    """Return cited facts plus literal evidence backing cited inferred skills."""
    index = index_facts(facts)
    expanded = set(referenced_ids(content))
    for fact_id in tuple(expanded):
        fact = index.get(fact_id)
        if isinstance(fact, Skill):
            expanded.update(
                evidence_id
                for evidence_id in fact.evidence_fact_ids
                if evidence_id in index
            )
    return {
        fact_id: index[fact_id].model_dump(mode="json")
        for fact_id in sorted(expanded)
        if fact_id in index
    }
