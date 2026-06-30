import re
import unicodedata

from evals.schema import Trap
from resume_agent.models.resume import ResumeContent


def resume_text(content: ResumeContent) -> str:
    parts: list[str] = []
    if content.summary:
        parts.append(content.summary)
    for experience in content.experience:
        parts += [
            experience.company,
            experience.title,
            *(bullet.text for bullet in experience.bullets),
        ]
    for project in content.projects:
        parts += [
            project.name,
            project.description or "",
            *project.tech,
            *(bullet.text for bullet in project.bullets),
        ]
    for skills in content.skills.values():
        parts += [skill.name for skill in skills]
        parts += [skill.context or "" for skill in skills]
    parts += [publication.title for publication in content.publications]
    parts += [certification.name for certification in content.certifications]
    for award in content.awards:
        parts += [award.name, award.description or ""]
    for volunteer in content.volunteer:
        parts += [
            volunteer.organization,
            volunteer.role or "",
            *(bullet.text for bullet in volunteer.bullets),
        ]
    return unicodedata.normalize(
        "NFKC", " ".join(part for part in parts if part)
    ).casefold()


def term_present(text: str, term: str) -> bool:
    haystack = unicodedata.normalize("NFKC", text).casefold()
    needle = unicodedata.normalize("NFKC", term).casefold()
    if not needle:
        return False
    # Only assert a word boundary on a side whose edge char is itself a word
    # char; a term like "saved $" ends in a non-word char, and (?!\w) there
    # would wrongly fail to match real text such as "saved $30,000".
    left = r"(?<!\w)" if re.match(r"\w", needle[0]) else ""
    right = r"(?!\w)" if re.match(r"\w", needle[-1]) else ""
    return re.search(rf"{left}{re.escape(needle)}{right}", haystack) is not None


def trap_terms_hit(content: ResumeContent, traps: list[Trap]) -> list[str]:
    text = resume_text(content)
    hits: list[str] = []
    seen: set[str] = set()
    for trap in traps:
        for term in trap.forbidden_terms:
            normalized = unicodedata.normalize("NFKC", term).casefold()
            if normalized not in seen and term_present(text, term):
                hits.append(term)
                seen.add(normalized)
    return hits
