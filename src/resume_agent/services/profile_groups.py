"""Set or clear durable skill-group corrections and refresh matrix.json."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.group_corrections import (
    GroupCorrection,
    corrections_path,
    load_group_corrections,
    save_group_corrections,
)
from resume_agent.profile.manual_skills import manual_skills_lock
from resume_agent.profile.matrix import (
    MatrixRow,
    SkillMatrix,
    build_decorated_matrix,
    rebuild_saved_matrix,
)
from resume_agent.profile.store import load_facts
from resume_agent.services.profile_skills import (
    ProfileNotBuiltError,
    SkillNotFoundError,
)
from resume_agent.taxonomy.groups import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill


class UnknownGroupError(ValueError):
    """Raised when a group slug is outside the fixed vocabulary."""


class GroupCorrectionNotFoundError(ValueError):
    """Raised when the requested skill has no correction to clear."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_facts_or_raise(profile_dir: str | Path) -> ProfileFacts:
    try:
        return load_facts(Path(profile_dir) / "facts.json")
    except FileNotFoundError as exc:
        raise ProfileNotBuiltError(
            "Build your profile before editing skill groups"
        ) from exc


def _resolve_row(matrix: SkillMatrix, key: str) -> MatrixRow:
    token = normalize_skill(key)
    for row in matrix.rows:
        lookup_tokens = {
            row.key,
            normalize_skill(row.display),
            *(normalize_skill(alias) for alias in row.aliases),
        }
        if token in lookup_tokens:
            return row
    raise SkillNotFoundError(f"No skill '{key}'")


def set_group(profile_dir: str | Path, key: str, group: str) -> MatrixRow:
    if group not in SKILL_GROUPS:
        raise UnknownGroupError(f"Unknown group '{group}'")

    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        row = _resolve_row(build_decorated_matrix(profile_dir, facts), key)
        path = corrections_path(profile_dir)
        ledger = load_group_corrections(path)
        ledger.corrections[row.key] = GroupCorrection(
            group=group,
            corrected_at=_utcnow(),
        )
        save_group_corrections(ledger, path)
        return _resolve_row(rebuild_saved_matrix(profile_dir, facts), row.key)


def clear_group(profile_dir: str | Path, key: str) -> None:
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        path = corrections_path(profile_dir)
        ledger = load_group_corrections(path)
        token = normalize_skill(key)
        if token not in ledger.corrections:
            token = _resolve_row(build_decorated_matrix(profile_dir, facts), key).key
        if token not in ledger.corrections:
            raise GroupCorrectionNotFoundError(f"No group correction for '{key}'")
        del ledger.corrections[token]
        save_group_corrections(ledger, path)
        rebuild_saved_matrix(profile_dir, facts)
