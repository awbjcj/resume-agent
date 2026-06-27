"""Two-stage advisor agents: grounded research followed by schema formatting."""

from __future__ import annotations

from typing import Literal

from agno.agent import Agent
from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import (
    AgentRunner,
    Runner,
    build_model,
    build_search_equipped,
    retry_kwargs,
    use_json_mode_for,
)
from resume_agent.models.base import ExtensibleModel


class RepoRef(ExtensibleModel):
    name: str = ""
    url: str = ""
    why: str = ""


class ResourceRef(ExtensibleModel):
    title: str = ""
    url: str = ""
    kind: Literal["course", "doc", "tutorial"] = "doc"


class ProjectIdea(ExtensibleModel):
    title: str = ""
    summary: str = ""
    skills_demonstrated: list[str] = Field(default_factory=list)


class SuggestionDraft(ExtensibleModel):
    repos: list[RepoRef] = Field(default_factory=list)
    resources: list[ResourceRef] = Field(default_factory=list)
    project: ProjectIdea | None = None
    bridge: str = ""
    citations: list[str] = Field(default_factory=list)


_SEARCH_INSTRUCTIONS = [
    "Research how a job seeker can close the specified skill gap.",
    "Use web search to find real, currently available GitHub repositories and learning resources.",
    "Prefer official documentation, established courses, reference implementations, and maintained repositories.",
    "Report real URLs and never invent a link.",
    "End with the source URLs used for the research.",
]

_FORMAT_INSTRUCTIONS = [
    "Convert the research into the structured suggestion schema.",
    "Put GitHub links in repos and classify learning links as course, doc, or tutorial.",
    "Propose one concrete portfolio project and a concise profile bridge.",
    "Use only URLs present in the research input.",
]


def _advisor_model_id() -> str:
    settings = get_settings()
    return settings.advisor_model or settings.premium_model


def build_search_agent() -> Runner:
    model, tools = build_search_equipped(_advisor_model_id())
    return AgentRunner(
        Agent(
            model=model,
            tools=tools,
            description="Research gap-closing resources with grounded web search.",
            instructions=_SEARCH_INSTRUCTIONS,
            **retry_kwargs(),
        )
    )


def build_formatter_agent() -> Runner:
    settings = get_settings()
    model = build_model(settings.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="Format grounded research into a gap-closing suggestion.",
            instructions=_FORMAT_INSTRUCTIONS,
            output_schema=SuggestionDraft,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
