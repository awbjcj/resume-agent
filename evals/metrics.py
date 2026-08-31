from dataclasses import dataclass

from evals.schema import Trap
from evals.textscan import trap_terms_hit
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.models.evidence_portfolio import EvidencePortfolio
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.review import ReviewCritique
from resume_tailor_harness.tailor.provenance import check_provenance, referenced_ids
from resume_tailor_harness.tailor.review_config import LengthBudget


def trap_avoided(content: ResumeContent, traps: list[Trap]) -> bool:
    return not trap_terms_hit(content, traps)


def provenance_ok(content: ResumeContent, facts: ProfileFacts) -> bool:
    return check_provenance(content, facts).ok


def must_cite_covered(content: ResumeContent, must_cite: list[str]) -> bool:
    cited = referenced_ids(content)
    return all(fact_id in cited for fact_id in must_cite)


def budget_ok(content: ResumeContent, budget: LengthBudget) -> bool:
    if len(content.experience) > budget.max_experiences:
        return False
    return not any(
        len(experience.bullets) > budget.max_bullets_per_role
        for experience in content.experience
    )


def total_bullets(content: ResumeContent) -> int:
    return (
        sum(len(experience.bullets) for experience in content.experience)
        + sum(len(project.bullets) for project in content.projects)
        + sum(len(volunteer.bullets) for volunteer in content.volunteer)
    )


@dataclass
class RoundRecord:
    round_num: int
    content: ResumeContent
    aggregate_score: int | None
    critiques: list[ReviewCritique]
    phase_seconds: dict[str, float] | None = None


@dataclass
class ProbeRecord:
    trap_id: str
    detected: bool | None
    error: str | None = None


def portfolio_selected_ids(portfolio: EvidencePortfolio | None) -> set[str]:
    if portfolio is None:
        return set()
    return {
        fact_id
        for selection in portfolio.selections
        for fact_id in (selection.owner_id, *selection.selected_fact_ids)
    }


def portfolio_mandatory_hits(
    portfolio: EvidencePortfolio | None, mandatory_ids: list[str]
) -> tuple[int, int]:
    selected = portfolio_selected_ids(portfolio)
    return sum(fact_id in selected for fact_id in mandatory_ids), len(mandatory_ids)


def portfolio_forbidden_hits(
    portfolio: EvidencePortfolio | None,
    forbidden_ids: list[str],
    forbidden_highlights: list[str],
) -> list[str]:
    if portfolio is None:
        return []
    selected = portfolio_selected_ids(portfolio)
    hits = [fact_id for fact_id in forbidden_ids if fact_id in selected]
    highlights = {term.casefold() for term in portfolio.highlight_terms}
    hits.extend(
        f"highlight:{term}"
        for term in forbidden_highlights
        if term.casefold() in highlights
    )
    return hits


def fact_check_trap_recall(probes: list[ProbeRecord]) -> float | None:
    completed = [probe for probe in probes if probe.detected is not None]
    if not completed:
        return None
    return sum(probe.detected is True for probe in completed) / len(completed)


def correlation(xs: list[float], ys: list[float], min_n: int = 5) -> float | None:
    count = len(xs)
    if count < min_n or count != len(ys):
        return None
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    differences_x = [value - mean_x for value in xs]
    differences_y = [value - mean_y for value in ys]
    numerator = sum(left * right for left, right in zip(differences_x, differences_y))
    denominator = (
        sum(value * value for value in differences_x)
        * sum(value * value for value in differences_y)
    ) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def convergence(rounds: list[RoundRecord]) -> tuple[int, bool]:
    scores = [
        round_.aggregate_score
        for round_ in rounds
        if round_.aggregate_score is not None
    ]
    regressed = any(current < previous for previous, current in zip(scores, scores[1:]))
    return len(rounds), regressed
