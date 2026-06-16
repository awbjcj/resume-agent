from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.job import JobCriteria


_INSTRUCTIONS = [
    "Extract structured hiring criteria from the job description text.",
    "Infer the sponsorship signal: 'offered', 'denied', or 'silent' when the text says nothing.",
    "Use only what the text supports; leave unknown fields null.",
]


def build_extract_agent(model_id: str | None = None) -> Runner:
    s = get_settings()
    resolved = model_id or s.cheap_model
    return AgentRunner(
        Agent(
            model=Claude(id=resolved, api_key=s.anthropic_api_key or None),
            description="You extract structured hiring criteria from job descriptions.",
            instructions=_INSTRUCTIONS,
            output_schema=JobCriteria,
        )
    )


def extract_job_criteria(jd_text: str, agent: Runner) -> JobCriteria:
    result = agent.run(jd_text)
    criteria = result.content
    if not isinstance(criteria, JobCriteria):
        raise TypeError(f"Expected JobCriteria from agent, got {type(criteria).__name__}")
    return criteria
