from resume_tailor_harness.models.cover_letter import CoverLetterContent
from resume_tailor_harness.models.profile import ProfileFacts


def collect_fact_ids(facts: ProfileFacts) -> set[str]:
    """Every provenance-eligible fact id in the profile."""
    ids: set[str] = set()
    for exp in facts.experience:
        ids.add(exp.id)
        for bullet in exp.bullets:
            ids.add(bullet.id)
    for project in facts.projects:
        ids.add(project.id)
    for skills in facts.skills.values():
        for skill in skills:
            ids.add(skill.id)
    for group in (
        facts.education,
        facts.certifications,
        facts.publications,
        facts.awards,
        facts.languages,
        facts.volunteer,
    ):
        for item in group:
            ids.add(item.id)
    if facts.github_profile is not None:
        ids.add(facts.github_profile.id)
    return ids


def unsupported_provenance(
    content: CoverLetterContent, fact_ids: set[str]
) -> list[str]:
    """Provenance ids cited by the letter that do not exist in the profile."""
    return [
        pid
        for paragraph in content.paragraphs
        for pid in paragraph.provenance
        if pid not in fact_ids
    ]
