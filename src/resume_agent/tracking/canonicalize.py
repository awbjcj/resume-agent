import json
from typing import Callable

from agno.agent import Agent
from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner, build_model, use_json_mode_for
from resume_agent.models.base import ExtensibleModel

_INSTRUCTIONS = [
    "You canonicalize technical skill names.",
    "Given a JSON array of lowercased skill tokens, group tokens that refer to the same skill.",
    "Return clusters as lists; put the most canonical token first in each cluster.",
    "Only group true synonyms such as kubernetes/k8s or ci cd/continuous integration.",
]

_THEME_INSTRUCTIONS = [
    "Group canonical technical skill tokens into broad, useful themes.",
    "Use 3 to 8 themes when the number and variety of tokens allow it.",
    "Use concise labels such as Backend, Data, Cloud, DevOps, or Frontend.",
    "Include every input token exactly once and do not invent or rewrite tokens.",
]


class SkillClusters(ExtensibleModel):
    """Groups of equivalent skill tokens; the first token is canonical."""

    clusters: list[list[str]] = Field(default_factory=list)


class ThemeGroup(ExtensibleModel):
    """A broad skill theme and the canonical tokens assigned to it."""

    label: str = ""
    skills: list[str] = Field(default_factory=list)


class SkillThemes(ExtensibleModel):
    """Broad themes that form an exact partition of skill tokens."""

    themes: list[ThemeGroup] = Field(default_factory=list)


Themer = Callable[[set[str]], list[tuple[str, list[str]]]]


def clusters_to_mapping(clusters: list[list[str]], tokens: set[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for cluster in clusters:
        if not cluster:
            continue
        canonical = cluster[0]
        for token in cluster:
            mapping[token] = canonical
    return {token: mapping.get(token, token) for token in tokens}


def themes_to_pairs(
    themes: list[ThemeGroup], tokens: set[str]
) -> list[tuple[str, list[str]]]:
    pairs: list[tuple[str, list[str]]] = []
    assigned: set[str] = set()

    for theme in themes:
        label = theme.label.strip()
        if not label:
            raise ValueError("theme labels must be nonblank")

        members: list[str] = []
        group_members: set[str] = set()
        for raw_skill in theme.skills:
            skill = raw_skill.strip()
            if not skill:
                raise ValueError("theme skill members must be nonblank")
            if skill in group_members:
                raise ValueError(f"duplicate skill token in theme: {skill!r}")
            if skill not in tokens:
                raise ValueError(f"unknown skill token in theme output: {skill!r}")
            if skill in assigned:
                raise ValueError(f"skill token appears in multiple themes: {skill!r}")
            group_members.add(skill)
            assigned.add(skill)
            members.append(skill)

        if not members:
            raise ValueError("theme groups must contain at least one skill token")
        pairs.append((label, members))

    missing = tokens - assigned
    if missing:
        raise ValueError(f"theme output is missing skill tokens: {sorted(missing)!r}")

    return pairs


def _default_agent() -> Runner:
    settings = get_settings()
    model = build_model(settings.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="You canonicalize skill names into synonym clusters.",
            instructions=_INSTRUCTIONS,
            output_schema=SkillClusters,
            use_json_mode=use_json_mode_for(model),
        )
    )


def _default_themer_agent() -> Runner:
    settings = get_settings()
    model = build_model(settings.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="You organize canonical technical skills into broad themes.",
            instructions=_THEME_INSTRUCTIONS,
            output_schema=SkillThemes,
            use_json_mode=use_json_mode_for(model),
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


def build_skill_themer(agent: Runner | None = None) -> Themer:
    runner = agent or _default_themer_agent()

    def theme(tokens: set[str]) -> list[tuple[str, list[str]]]:
        if not tokens:
            return []
        result = runner.run(json.dumps(sorted(tokens)))
        content = result.content
        themes = content.themes if isinstance(content, SkillThemes) else []
        return themes_to_pairs(themes, tokens)

    return theme
