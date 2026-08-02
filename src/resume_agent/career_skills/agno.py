"""Small adapters that attach verified career skills to Agno agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar

from agno.skills import LocalSkills, Skills

from resume_agent.career_skills.models import AgentFamily, AgentRunMeta
from resume_agent.career_skills.registry import VerifiedSkill
from resume_agent.llm_runner import Runner


def skill_kwargs(skill: VerifiedSkill) -> dict[str, Skills]:
    """Return the single approved local-skill loader for one task agent."""
    return {"skills": Skills(loaders=[LocalSkills(str(skill.directory))])}


@dataclass(frozen=True)
class AgentCacheKey:
    family: AgentFamily
    skill_sha256: str | None
    model_id: str
    output_schema: str | None
    prompt_policy_version: str


_RunnerT = TypeVar("_RunnerT", bound=Runner)


class SkilledAgentPool:
    """Thread-safe cache for stable, non-tool-bearing task agents."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[AgentCacheKey, Runner] = {}

    def get(self, key: AgentCacheKey, builder: Callable[[], _RunnerT]) -> _RunnerT:
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                return existing  # type: ignore[return-value]
            built = builder()
            self._items[key] = built
            return built


def run_meta_payload(*runners: Runner) -> list[dict[str, object]]:
    """Return redacted metadata suitable for a background-run record."""
    payload: list[dict[str, object]] = []
    for runner in runners:
        meta = getattr(runner, "run_meta", None)
        if not isinstance(meta, AgentRunMeta):
            continue
        item: dict[str, object] = {
            "agentFamily": meta.agent_family.value,
            "promptPolicyVersion": meta.prompt_policy_version,
            "modelId": meta.model_id,
        }
        if meta.skill_ref is not None:
            item["skill"] = {
                "name": meta.skill_ref.name,
                "version": meta.skill_ref.version,
                "sha256": meta.skill_ref.sha256,
            }
        payload.append(item)
    return payload
