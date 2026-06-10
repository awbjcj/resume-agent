from typing import Any

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent


class ProvenanceReport(ExtensibleModel):
    """Result of the deterministic provenance check."""

    ok: bool
    missing: list[str] = Field(default_factory=list)


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


def referenced_ids(content: ResumeContent) -> set[str]:
    """Every provenance id the resume claims to draw from."""
    ids: set[str] = set()
    for exp in content.experience:
        ids.add(exp.provenance)
        ids.update(b.provenance for b in exp.bullets)
    for proj in content.projects:
        ids.add(proj.provenance)
        ids.update(b.provenance for b in proj.bullets)
    for skills in content.skills.values():
        ids.update(s.provenance for s in skills)
    ids.update(p.provenance for p in content.publications)
    ids.update(c.provenance for c in content.certifications)
    ids.update(a.provenance for a in content.awards)
    for vol in content.volunteer:
        ids.add(vol.provenance)
        ids.update(b.provenance for b in vol.bullets)
    return ids


def check_provenance(content: ResumeContent, facts: ProfileFacts) -> ProvenanceReport:
    """Fail fast in plain code: every referenced id must resolve to a real fact."""
    valid = set(index_facts(facts))
    missing = sorted(i for i in referenced_ids(content) if i not in valid)
    return ProvenanceReport(ok=not missing, missing=missing)
