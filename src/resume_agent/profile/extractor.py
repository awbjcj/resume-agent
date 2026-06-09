from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.models.profile import ProfileFacts


class Runner(Protocol):
    """Anything with Agno's ``run(prompt) -> result`` shape (result has ``.content``)."""

    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Extract structured resume facts from the raw resume text provided.",
    "Use ONLY information present in the text. Never invent companies, dates, skills, or numbers.",
    "Leave fields empty or null when the text does not provide them.",
    "Split each role's accomplishments into individual bullet entries.",
]


def build_extractor_agent(model_id: str | None = None) -> Agent:
    """Create the Agno agent that structures resume text into ProfileFacts."""
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You extract structured, truthful resume facts from raw resume text.",
        instructions=_INSTRUCTIONS,
        output_schema=ProfileFacts,
    )


def extract_profile_facts(resume_text: str, agent: Runner) -> ProfileFacts:
    """Run the agent and return its ProfileFacts, validating the result type."""
    result = agent.run(resume_text)
    facts = result.content
    if not isinstance(facts, ProfileFacts):
        raise TypeError(f"Expected ProfileFacts from agent, got {type(facts).__name__}")
    return facts
