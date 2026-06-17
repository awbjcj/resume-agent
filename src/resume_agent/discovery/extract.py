from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.job import JobCriteria, JobCriteriaExtract


_INSTRUCTIONS = [
    "Extract structured hiring criteria from the job description text.",
    "Infer the sponsorship signal: 'offered', 'denied', or 'silent' when the text says nothing.",
    "Infer seniority as one of: junior, mid, senior, staff, principal -- leave null if unclear.",
    "Infer employment type as one of: full_time, contract, internship, part_time -- leave null if unclear.",
    "List the concrete tech stack (languages, frameworks, tools) named in the post.",
    "Capture the industry or domain (e.g. fintech, healthcare) when stated.",
    "Capture company size or stage (startup, scaleup, enterprise) when stated.",
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
            output_schema=JobCriteriaExtract,
        )
    )


def extract_job_criteria(jd_text: str, agent: Runner) -> JobCriteria:
    result = agent.run(jd_text)
    extracted = result.content
    if not isinstance(extracted, JobCriteriaExtract):
        raise TypeError(
            f"Expected JobCriteriaExtract from agent, got {type(extracted).__name__}"
        )
    return extracted.to_criteria()
