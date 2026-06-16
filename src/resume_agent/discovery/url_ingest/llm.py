from agno.agent import Agent
from agno.models.anthropic import Claude
from bs4 import BeautifulSoup

from resume_agent.config import get_settings
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import AgentRunner, Runner

_INSTRUCTIONS = [
    "Extract the company, job title, location, and full job-description text.",
    "Use only what the page text supports; leave unknown fields null.",
    "Put the complete responsibilities and requirements prose in jd_text.",
]


def build_url_extract_agent(model_id: str | None = None) -> Runner:
    resolved = model_id or get_settings().cheap_model
    return AgentRunner(
        Agent(
            model=Claude(id=resolved),
            description="You extract a job posting's fields from page text.",
            instructions=_INSTRUCTIONS,
            output_schema=ExtractedJob,
        )
    )


def extract_fields(text: str, agent: Runner) -> ExtractedJob:
    result = agent.run(text)
    extracted = result.content
    if not isinstance(extracted, ExtractedJob):
        raise TypeError(f"Expected ExtractedJob from agent, got {type(extracted).__name__}")
    return extracted


def html_to_text(html: str) -> str:
    """Reduce a page to readable text: drop scripts, styles, and nav chrome."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n", strip=True).splitlines()]
    return "\n".join(ln for ln in lines if ln)
