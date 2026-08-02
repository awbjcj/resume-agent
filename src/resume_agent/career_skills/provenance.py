"""Strict persistence helpers for agent skill provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from resume_agent.career_skills.models import AgentRunMeta, SkillUse, SkillUseStage, read_skill_uses


def require_run_meta(runner: Any) -> AgentRunMeta:
    meta = getattr(runner, "run_meta", None)
    if not isinstance(meta, AgentRunMeta):
        raise ValueError("agent runner has no validated run metadata")
    return meta


def append_skill_use(raw: object, runner: Any, stage: SkillUseStage) -> list[dict[str, object]]:
    uses = read_skill_uses(raw)
    meta = require_run_meta(runner)
    if meta.skill_ref is not None:
        uses.append(
            SkillUse(
                skill_ref=meta.skill_ref,
                stage=stage,
                used_at=datetime.now(timezone.utc),
                model_id=meta.model_id,
                prompt_policy_version=meta.prompt_policy_version,
            )
        )
    return [use.model_dump(mode="json") for use in uses]
