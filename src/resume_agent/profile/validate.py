from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts


_SECTION_CUES = (
    ("publication", "publications"),
    ("certification", "certifications"),
    ("award", "awards"),
    ("volunteer", "volunteer"),
)


class CoverageReport(ExtensibleModel):
    """Advisory deterministic checks over an extracted profile."""

    ok: bool
    warnings: list[str] = Field(default_factory=list)


def validate_profile(facts: ProfileFacts, raw_text: str) -> CoverageReport:
    warnings: list[str] = []

    if not facts.contact.name.strip():
        warnings.append("contact.name is empty")

    for exp in facts.experience:
        if not exp.bullets:
            warnings.append(f"experience '{exp.title} @ {exp.company}' has no bullets")

    lowered = raw_text.lower()
    for cue, attr in _SECTION_CUES:
        if cue in lowered and not getattr(facts, attr):
            warnings.append(f"raw text mentions '{cue}' but no {attr} were extracted")

    return CoverageReport(ok=not warnings, warnings=warnings)
