from collections.abc import Mapping

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.panel import run_panel
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.tailoring import compose_revise_input, compose_tailor_input, revise, tailor
from resume_agent.tailor.verdict import PanelVerdict, aggregate


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict


def run_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[TailorRound]:
    """Draft, then review/revise until the round passes or max_rounds is hit.

    Returns one TailorRound per iteration (content + its panel verdict).
    """
    content = tailor(compose_tailor_input(jd_text, criteria, profile_facts), tailor_agent)
    rounds: list[TailorRound] = []
    for round_num in range(1, config.max_rounds + 1):
        critiques = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
        verdict = aggregate(critiques, config)
        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts), reviser_agent
        )
    return rounds
