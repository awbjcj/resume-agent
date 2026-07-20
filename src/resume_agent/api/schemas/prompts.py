"""Wire contract for prompt transparency and guidance editing."""

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.prompts.guidance import MAX_GUIDANCE_CHARS


class AgentPromptItem(CamelModel):
    key: str
    title: str
    stage: str
    description: str
    instructions: list[str]
    guidance: str | None = None
    editable: bool


class GuidanceUpdate(CamelModel):
    guidance: str = Field(max_length=MAX_GUIDANCE_CHARS)
