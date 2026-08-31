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

from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.review import ReviewCritique, ReviewIssue, Severity
from resume_tailor_harness.profile.matrix import SkillMatch, SkillMatchContext
from resume_tailor_harness.tracking.match_gap import normalize_skill

COVERAGE_REVIEWER: str = "must-have-coverage"

_HEADER = (
    "MUST-HAVE COVERAGE (deterministic; fact ids are evidence pointers, not claims):"
)


class CoverageCritique(ReviewCritique):
    """Runtime marker for the advisory coverage measurement.

    The persisted/API shape remains ``ReviewCritique``. This subtype exists
    only while a round is aggregated so a configured reviewer named
    ``must-have-coverage`` is never shadowed by the deterministic measurement.

    ``covered_total`` and ``rendered_total`` are measurement metadata declared
    here (not inherited from ``ReviewCritique``) so they survive JSON
    persistence and health reports can aggregate a weighted coverage rate
    across rounds. The ``supporting_*`` pair does the same for the
    nice-to-have and tech-stack tiers.
    """

    covered_total: int = 0
    rendered_total: int = 0
    supporting_total: int = 0
    supporting_rendered_total: int = 0


class CoverageReport(ExtensibleModel):
    """Which evidenced requirements reached the produced resume.

    Two tiers, kept apart because they answer different questions. The
    must-have tally is the quality bar (``score`` reports it). The supporting
    tally - nice-to-have plus tech stack - exists so *under-inclusion* is
    observable at all: the panel measured only must-haves, so a resume could
    omit every evidenced supporting skill in the profile and no reviewer, gate,
    or score could see it. That blind spot is why the skills section shrank
    without anything registering a complaint.
    """

    covered_total: int = 0
    rendered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    supporting_total: int = 0
    supporting_rendered: list[str] = Field(default_factory=list)
    supporting_missed: list[str] = Field(default_factory=list)


# The block carries every requirement tier, so each line names its own. Order
# alone cannot say whether a `gap` is a must-have the resume must not claim or a
# tech-stack mention, and the writer prioritizes on exactly that difference.
_TIERS: dict[str, str] = {
    "must": "must-have",
    "nice": "nice-to-have",
    "tech": "tech stack",
}
_TIER_ORDER: dict[str, int] = {"must": 0, "nice": 1, "tech": 2}


def _line(match: SkillMatch) -> str:
    tier = _TIERS.get(match.source, match.source)
    head = f"- ({tier}) {match.requirement}"
    if match.coverage == "covered":
        facts = ", ".join(match.row.evidence_fact_ids) if match.row else ""
        return f"{head} — covered — facts: {facts}"
    if match.coverage == "adjacent":
        label = match.row.display if match.row else "a related skill"
        return f"{head} — adjacent ({label}) — may inform emphasis, never named"
    return f"{head} — gap — no profile evidence; do not claim or imply"


def format_coverage(context: SkillMatchContext | None) -> str:
    """Render the coverage block with must-haves before nice-to-haves."""
    if context is None or not context.matches:
        return ""
    ordered = sorted(
        context.matches, key=lambda match: _TIER_ORDER.get(match.source, 3)
    )
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


def _prose(content: ResumeContent) -> list[str]:
    """Each bullet normalized and padded, for exact phrase containment.

    Bullets stay separate rather than being joined into one string: joining lets
    a multi-word requirement match across a bullet boundary, so a bullet ending
    "...on the machine" followed by one starting "learning pipelines..." would
    count "machine learning" as rendered.

    Padding prevents a one-letter requirement such as ``R`` from matching every
    bullet through a bare substring test.
    """
    bullets: list[str] = []
    for experience in content.experience:
        bullets.extend(bullet.text for bullet in experience.bullets)
    for project in content.projects:
        bullets.extend(bullet.text for bullet in project.bullets)
    for volunteer in content.volunteer:
        bullets.extend(bullet.text for bullet in volunteer.bullets)
    return [f" {normalize_skill(text)} " for text in bullets]


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
    bullets = _prose(content)
    rendered: list[str] = []
    missed: list[str] = []
    supporting_rendered: list[str] = []
    supporting_missed: list[str] = []
    for match in context.matches:
        if match.coverage != "covered":
            continue
        tokens = _match_tokens(match)
        if not tokens:
            continue
        is_rendered = any(
            token in skill_tokens or any(f" {token} " in text for text in bullets)
            for token in tokens
        )
        if match.source == "must":
            (rendered if is_rendered else missed).append(match.requirement)
        else:
            (supporting_rendered if is_rendered else supporting_missed).append(
                match.requirement
            )
    return CoverageReport(
        covered_total=len(rendered) + len(missed),
        rendered=rendered,
        missed=missed,
        supporting_total=len(supporting_rendered) + len(supporting_missed),
        supporting_rendered=supporting_rendered,
        supporting_missed=supporting_missed,
    )


# How many omitted supporting skills to name before summarizing the remainder.
# One issue per omission would be correct and useless: a profile with hundreds
# of skills would bury every other reviewer's feedback in the reviser's prompt.
_SUPPORTING_SAMPLE = 12


def _supporting_issue(report: CoverageReport) -> ReviewIssue | None:
    """One bounded issue naming supporting skills the resume left out."""
    if not report.supporting_missed:
        return None
    sample = report.supporting_missed[:_SUPPORTING_SAMPLE]
    remainder = len(report.supporting_missed) - len(sample)
    listed = ", ".join(repr(requirement) for requirement in sample)
    tail = f", and {remainder} more" if remainder else ""
    return ReviewIssue(
        severity=Severity.major,
        location="skills",
        message=(
            f"{len(report.supporting_missed)} supporting skills (nice-to-have or "
            f"tech stack) have profile evidence but are absent from this resume: "
            f"{listed}{tail}"
        ),
        suggestion=(
            "add each as a skills entry citing its profile Skill id; the skills "
            "section costs about one line per category and is not where this "
            "resume runs long"
        ),
    )


def coverage_critique(
    content: ResumeContent, context: SkillMatchContext | None
) -> CoverageCritique | None:
    """Return an advisory coverage rate, or ``None`` when there is no measure.

    ``score`` stays the must-have rendered share: that is the quality bar, and
    changing its meaning would silently rewrite every stored round's health
    metric. Supporting coverage rides alongside as its own totals plus one
    issue, which is what actually reaches the reviser.
    """
    report = coverage_report(content, context)
    # A context with only supporting requirements evidenced is exactly the case
    # where breadth feedback matters most, so it must not return None here.
    if not report.covered_total and not report.supporting_total:
        return None
    supporting = _supporting_issue(report)
    return CoverageCritique(
        reviewer=COVERAGE_REVIEWER,
        score=(
            round(100 * len(report.rendered) / report.covered_total)
            if report.covered_total
            else round(100 * len(report.supporting_rendered) / report.supporting_total)
        ),
        passed=True,
        covered_total=report.covered_total,
        rendered_total=len(report.rendered),
        supporting_total=report.supporting_total,
        supporting_rendered_total=len(report.supporting_rendered),
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
        ]
        + ([supporting] if supporting is not None else []),
    )
