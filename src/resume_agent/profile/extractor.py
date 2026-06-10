from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.profile import ProfileFacts


_INSTRUCTIONS = [
    "Extract structured resume facts from the raw resume text provided.",
    "Use ONLY information present in the text. Never invent companies, dates, skills, or numbers.",
    "Leave fields empty or null when the text does not provide them.",
    "Split each role's accomplishments into individual bullet entries.",
]


def build_extractor_agent(model_id: str | None = None) -> Runner:
    """Create the Agno agent that structures resume text into ProfileFacts."""
    resolved = model_id or get_settings().mid_model
    return AgentRunner(
        Agent(
            model=Claude(id=resolved),
            description="You extract structured, truthful resume facts from raw resume text.",
            instructions=_INSTRUCTIONS,
            output_schema=ProfileFacts,
        )
    )


def extract_profile_facts(resume_text: str, agent: Runner) -> ProfileFacts:
    """Run the agent and return its ProfileFacts, validating the result type."""
    result = agent.run(resume_text)
    facts = result.content
    if not isinstance(facts, ProfileFacts):
        raise TypeError(f"Expected ProfileFacts from agent, got {type(facts).__name__}")
    return facts
