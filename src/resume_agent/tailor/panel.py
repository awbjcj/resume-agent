from typing import Any, Protocol

from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


def compose_review_input(content: ResumeContent, profile_facts: ProfileFacts, jd_text: str) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def review_one(input_text: str, agent: Runner) -> ReviewCritique:
    result = agent.run(input_text)
    critique = result.content
    if not isinstance(critique, ReviewCritique):
        raise TypeError(f"Expected ReviewCritique from reviewer, got {type(critique).__name__}")
    return critique


def run_panel(input_text: str, config: ReviewConfig, reviewer_agents: dict[str, Runner]) -> list[ReviewCritique]:
    """Run every configured reviewer over the same input and collect their critiques."""
    return [review_one(input_text, reviewer_agents[spec.name]) for spec in config.reviewers]
