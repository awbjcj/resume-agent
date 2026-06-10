from collections.abc import Mapping

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.panel import run_panel
from resume_agent.tailor.provenance import ProvenanceReport, check_provenance
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.tailoring import compose_revise_input, compose_tailor_input, revise, tailor
from resume_agent.tailor.verdict import PanelVerdict, aggregate


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict


def _provenance_verdict(report: ProvenanceReport) -> PanelVerdict:
    """Build a blocking verdict from a failed structural check, without LLM calls."""
    critique = ReviewCritique(
        reviewer="provenance",
        score=0,
        passed=False,
        issues=[
            ReviewIssue(
                severity=Severity.blocking,
                message=f"provenance id not found in profile facts: {missing_id}",
            )
            for missing_id in report.missing
        ],
    )
    return PanelVerdict(passed=False, gate_passed=False, aggregate_score=0, critiques=[critique])


def run_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[TailorRound]:
    """Draft, then gate/review/revise until the round passes or max_rounds is hit."""
    content = tailor(compose_tailor_input(jd_text, criteria, profile_facts), tailor_agent)
    rounds: list[TailorRound] = []
    for round_num in range(1, config.max_rounds + 1):
        provenance = check_provenance(content, profile_facts)
        if provenance.ok:
            critiques = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
            verdict = aggregate(critiques, config, provenance_passed=True)
        else:
            verdict = _provenance_verdict(provenance)

        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts), reviser_agent
        )
    return rounds
