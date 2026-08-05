"""Must-have coverage: the deterministic answer the pipeline already computes.

``build_skill_match_context`` maps each job requirement to covered, adjacent,
or gap, together with the matching matrix row and its evidence fact ids. This
module renders that context for prompt consumers and measures which evidenced
must-haves reached the generated resume.

Coverage is advisory rather than a gate. A one-page resume may have to leave a
truthful, evidenced requirement out, and turning that length trade-off into a
blocking failure would make the tailoring loop unwinnable.
"""

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.profile.matrix import SkillMatch, SkillMatchContext
from resume_agent.tracking.match_gap import normalize_skill

COVERAGE_REVIEWER: str = "must-have-coverage"

_HEADER = (
    "MUST-HAVE COVERAGE (deterministic; fact ids are evidence pointers, not claims):"
)


class CoverageReport(ExtensibleModel):
    """Which evidenced must-haves reached the produced resume."""

    covered_total: int = 0
    rendered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)


def _line(match: SkillMatch) -> str:
    if match.coverage == "covered":
        facts = ", ".join(match.row.evidence_fact_ids) if match.row else ""
        return f"- {match.requirement} — covered — facts: {facts}"
    if match.coverage == "adjacent":
        label = match.row.display if match.row else "a related skill"
        return (
            f"- {match.requirement} — adjacent ({label}) — may inform emphasis, "
            "never named"
        )
    return f"- {match.requirement} — gap — no profile evidence; do not claim or imply"


def format_coverage(context: SkillMatchContext | None) -> str:
    """Render the coverage block with must-haves before nice-to-haves."""
    if context is None or not context.matches:
        return ""
    order = {"must": 0, "nice": 1, "tech": 2}
    ordered = sorted(context.matches, key=lambda match: order.get(match.source, 3))
    return "\n".join([_HEADER, *(_line(match) for match in ordered)])


def _rendered_tokens(content: ResumeContent) -> set[str]:
    """Normalized names of skills explicitly selected for the resume."""
    tokens = {
        normalize_skill(entry.name)
        for entries in content.skills.values()
        for entry in entries
    }
    tokens.discard("")
    return tokens


def _prose(content: ResumeContent) -> str:
    """Normalized, padded generated prose for exact phrase containment."""
    parts = [content.summary or ""]
    for experience in content.experience:
        parts.extend(bullet.text for bullet in experience.bullets)
    for project in content.projects:
        parts.append(project.description or "")
        parts.extend(bullet.text for bullet in project.bullets)
    for volunteer in content.volunteer:
        parts.extend(bullet.text for bullet in volunteer.bullets)
    # Padding prevents a one-letter requirement such as ``R`` from matching
    # every prose string through a bare substring test.
    return f" {normalize_skill(' '.join(parts))} "


def _match_tokens(match: SkillMatch) -> set[str]:
    """Requirement spellings that identify the same matrix row."""
    values = [match.requirement]
    if match.row is not None:
        values.extend((match.row.display, *match.row.aliases, match.row.key))
    tokens = {normalize_skill(value) for value in values}
    tokens.discard("")
    return tokens


def coverage_report(
    content: ResumeContent, context: SkillMatchContext | None
) -> CoverageReport:
    """Measure rendered coverage among must-haves with profile evidence."""
    if context is None:
        return CoverageReport()

    skill_tokens = _rendered_tokens(content)
    prose = _prose(content)
    rendered: list[str] = []
    missed: list[str] = []
    for match in context.matches:
        if match.source != "must" or match.coverage != "covered":
            continue
        tokens = _match_tokens(match)
        if not tokens:
            continue
        if any(token in skill_tokens or f" {token} " in prose for token in tokens):
            rendered.append(match.requirement)
        else:
            missed.append(match.requirement)
    return CoverageReport(
        covered_total=len(rendered) + len(missed),
        rendered=rendered,
        missed=missed,
    )


def coverage_critique(
    content: ResumeContent, context: SkillMatchContext | None
) -> ReviewCritique | None:
    """Return an advisory coverage rate, or ``None`` when there is no measure."""
    report = coverage_report(content, context)
    if not report.covered_total:
        return None
    return ReviewCritique(
        reviewer=COVERAGE_REVIEWER,
        score=round(100 * len(report.rendered) / report.covered_total),
        passed=True,
        issues=[
            ReviewIssue(
                severity=Severity.major,
                location="skills",
                message=(
                    f"must-have {requirement!r} has profile evidence but does not "
                    "appear in this resume"
                ),
                suggestion=(
                    "add it as a skills entry, or show it in a bullet, if a truthful "
                    "cited fact supports it"
                ),
            )
            for requirement in report.missed
        ],
    )
