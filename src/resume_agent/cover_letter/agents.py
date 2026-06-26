from agno.agent import Agent

from resume_agent.llm_runner import (
    AgentRunner,
    Runner,
    build_model,
    retry_kwargs,
    use_json_mode_for,
)
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

_REVISION_INSTRUCTIONS = [
    "Apply the user's instruction to the cover letter.",
    "Change ONLY what the instruction asks; keep everything else intact.",
    "Use ONLY facts present in the candidate profile. Never invent anything.",
    "Every paragraph's provenance list must keep ids that point at real profile facts.",
    "If the instruction cannot be satisfied truthfully, make the closest truthful change.",
]


def build_cover_letter_agent(model_id: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You are an expert cover-letter writer who never fabricates.",
            instructions=_DRAFT_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def build_cover_letter_reviser_agent(model_id: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("mid"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise cover letters to keep every claim fact-locked.",
            instructions=_REVISE_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


def build_cover_letter_revision_agent(model_id: str | None = None) -> Runner:
    model = build_model(model_id or model_for_tier("premium"))
    return AgentRunner(
        Agent(
            model=model,
            description="You revise cover letters per a user's instruction without fabricating.",
            instructions=_REVISION_INSTRUCTIONS,
            output_schema=CoverLetterContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
