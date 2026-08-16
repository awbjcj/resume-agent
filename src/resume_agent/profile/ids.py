"""Deterministic, content-derived fact IDs for stable provenance."""

import hashlib
import re

from resume_agent.models.base import FactItem
from resume_agent.models.profile import ProfileFacts

_NORM = re.compile(r"[^a-z0-9]+")


def _key(text: str | None) -> str:
    return _NORM.sub(" ", (text or "").casefold()).strip()


def deterministic_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


class _Assigner:
    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self._seen: dict[str, int] = {}

    def assign(self, item: FactItem, *parts: str | None) -> str:
        base = "|".join((self.doc_id, *(_key(part) or "-" for part in parts)))
        count = self._seen.get(base, 0)
        self._seen[base] = count + 1
        item.id = deterministic_id(base, str(count))
        item.source_ref = self.doc_id
        return item.id


def assign_fact_ids(facts: ProfileFacts, doc_id: str) -> ProfileFacts:
    """Return a deep copy with deterministic IDs and the corpus source reference."""
    output = facts.model_copy(deep=True)
    ids = _Assigner(doc_id)
    for experience in output.experience:
        parent = ids.assign(experience, "exp", experience.company, experience.title)
        for bullet in experience.bullets:
            ids.assign(bullet, "bullet", parent, bullet.text)
    for project in output.projects:
        parent = ids.assign(project, "proj", project.name)
        for highlight in project.highlights:
            ids.assign(highlight, "highlight", parent, highlight.text)
    for education in output.education:
        ids.assign(education, "edu", education.institution, education.degree)
    for category, skills in output.skills.items():
        for skill in skills:
            ids.assign(skill, "skill", category, skill.name)
    for certification in output.certifications:
        ids.assign(certification, "cert", certification.name)
    for publication in output.publications:
        ids.assign(publication, "pub", publication.title)
    for award in output.awards:
        ids.assign(award, "award", award.name)
    for language in output.languages:
        ids.assign(language, "lang", language.language)
    for volunteer in output.volunteer:
        ids.assign(volunteer, "vol", volunteer.organization, volunteer.role)
    if output.github_profile is not None:
        ids.assign(output.github_profile, "github", output.github_profile.username)
    return output
