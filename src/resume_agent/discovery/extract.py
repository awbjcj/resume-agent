from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.models.job import JobCriteria


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Extract structured hiring criteria from the job description text.",
    "Infer the sponsorship signal: 'offered', 'denied', or 'silent' when the text says nothing.",
    "Use only what the text supports; leave unknown fields null.",
]


def build_extract_agent(model_id: str | None = None) -> Agent:
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You extract structured hiring criteria from job descriptions.",
        instructions=_INSTRUCTIONS,
        output_schema=JobCriteria,
    )


def extract_job_criteria(jd_text: str, agent: Runner) -> JobCriteria:
    result = agent.run(jd_text)
    criteria = result.content
    if not isinstance(criteria, JobCriteria):
        raise TypeError(f"Expected JobCriteria from agent, got {type(criteria).__name__}")
    return criteria
