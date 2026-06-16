import json
from typing import Callable

from agno.agent import Agent
from agno.models.anthropic import Claude
from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.base import ExtensibleModel

_INSTRUCTIONS = [
    "You canonicalize technical skill names.",
    "Given a JSON array of lowercased skill tokens, group tokens that refer to the same skill.",
    "Return clusters as lists; put the most canonical token first in each cluster.",
    "Only group true synonyms such as kubernetes/k8s or ci cd/continuous integration.",
]


class SkillClusters(ExtensibleModel):
    """Groups of equivalent skill tokens; the first token is canonical."""

    clusters: list[list[str]] = Field(default_factory=list)


def clusters_to_mapping(clusters: list[list[str]], tokens: set[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for cluster in clusters:
        if not cluster:
            continue
        canonical = cluster[0]
        for token in cluster:
            mapping[token] = canonical
    return {token: mapping.get(token, token) for token in tokens}


def _default_agent() -> Runner:
    settings = get_settings()
    return AgentRunner(
        Agent(
            model=Claude(id=settings.cheap_model, api_key=settings.anthropic_api_key or None),
            description="You canonicalize skill names into synonym clusters.",
            instructions=_INSTRUCTIONS,
            output_schema=SkillClusters,
        )
    )


def build_skill_canonicalizer(agent: Runner | None = None) -> Callable[[set[str]], dict[str, str]]:
    runner = agent or _default_agent()

    def canonicalize(tokens: set[str]) -> dict[str, str]:
        if not tokens:
            return {}
        result = runner.run(json.dumps(sorted(tokens)))
        content = result.content
        clusters = content.clusters if isinstance(content, SkillClusters) else []
        return clusters_to_mapping(clusters, tokens)

    return canonicalize
