"""Small adapters that attach verified career skills to Agno agents."""

from __future__ import annotations

from agno.skills import LocalSkills, Skills

from resume_tailor_harness.career_skills.models import AgentRunMeta
from resume_tailor_harness.career_skills.registry import VerifiedSkill
from resume_tailor_harness.llm_runner import Runner


def skill_kwargs(skill: VerifiedSkill) -> dict[str, Skills]:
    """Return the single approved local-skill loader for one task agent."""
    return {"skills": Skills(loaders=[LocalSkills(str(skill.directory))])}


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
