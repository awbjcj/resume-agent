from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.tailor.agents import model_for_tier

_DRAFT_INSTRUCTIONS = [
    "Write a concise, specific cover letter for the candidate targeting the given job.",
    "Use ONLY facts present in the candidate profile. Never invent employers, projects, skills, or metrics.",
    "Each paragraph MUST list in 'provenance' the ids of the profile facts it draws on.",
    "Use 3-4 short paragraphs: open with genuine fit, give evidence from real experience, close with intent.",
]

_REVISE_INSTRUCTIONS = [
    "Revise the cover letter to remove any claim whose provenance id is not a real profile fact.",
    "Every paragraph's 'provenance' must list only ids that exist in the candidate profile.",
    "Keep it concise and truthful; introduce no new unsupported claims.",
]


def build_cover_letter_agent(model_id: str | None = None) -> Runner:
    s = get_settings()
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("premium"), api_key=s.anthropic_api_key or None),
            description="You are an expert cover-letter writer who never fabricates.",
            instructions=_DRAFT_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=True,
        )
    )


def build_cover_letter_reviser_agent(model_id: str | None = None) -> Runner:
    s = get_settings()
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("mid"), api_key=s.anthropic_api_key or None),
            description="You revise cover letters to keep every claim fact-locked.",
            instructions=_REVISE_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=True,
        )
    )
