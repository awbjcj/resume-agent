from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts


class FitScore(ExtensibleModel):
    score: int  # 0-100
    rationale: str


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Score how well the candidate fits the job, from 0 to 100.",
    "Base the score only on the candidate facts and job description provided.",
    "Give a one or two sentence rationale.",
]


def build_fit_agent(model_id: str | None = None) -> Agent:
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You rate how well a candidate fits a job.",
        instructions=_INSTRUCTIONS,
        output_schema=FitScore,
    )


def compose_fit_input(jd_text: str, profile_facts: ProfileFacts) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def score_fit(input_text: str, agent: Runner) -> FitScore:
    result = agent.run(input_text)
    fit = result.content
    if not isinstance(fit, FitScore):
        raise TypeError(f"Expected FitScore from agent, got {type(fit).__name__}")
    return fit
