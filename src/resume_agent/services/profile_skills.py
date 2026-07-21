"""Quick-add a skill or alias from a job's gap chip -- takes effect immediately.

Coverage on a job card is computed live from facts.json on every request
(``tracking/queries.py::_skill_tags``), so a facts.json write is the entire
"immediate effect" mechanism; the only other artifact that needs refreshing
is the derived, sha-cached ``matrix.json`` (Settings > Skill Matrix, Match/Gap
dashboard).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.manual_skills import (
    ManualAliasEntry,
    ManualSkillEntry,
    ManualSuppressEntry,
    apply_manual_skills,
    load_manual_skills,
    manual_skills_lock,
    remove_manual_skill_entry,
    save_manual_skills,
)
from resume_agent.profile.matrix import rebuild_saved_matrix
from resume_agent.profile.store import load_facts, save_facts
from resume_agent.tracking.match_gap import normalize_skill


class ProfileNotBuiltError(RuntimeError):
    """Raised when a skill mutation is attempted before facts.json exists."""


class SkillAlreadyExistsError(ValueError):
    """Raised when the requested skill/alias already matches a profile skill."""


class SkillNotFoundError(ValueError):
    """Raised when a skill id passed to ``add_alias`` doesn't resolve."""


class ManualEntryNotFoundError(ValueError):
    """Raised when a ledger entry id passed to ``remove_manual_entry`` doesn't resolve."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _facts_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / "facts.json"


def _ledger_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / "manual_skills.json"


def _load_facts_or_raise(profile_dir: str | Path) -> ProfileFacts:
    try:
        return load_facts(_facts_path(profile_dir))
    except FileNotFoundError as exc:
        raise ProfileNotBuiltError(
            "Build your profile before adding skills"
        ) from exc


def _known_tokens(facts: ProfileFacts) -> set[str]:
    return {
        normalize_skill(alias)
        for skills in facts.skills.values()
        for skill in skills
        for alias in (skill.name, *skill.aliases)
    }


def list_skills(profile_dir: str | Path) -> list[dict[str, str | None]]:
    facts = _load_facts_or_raise(profile_dir)
    return [
        {"id": skill.id, "name": skill.name, "category": skill.category}
        for skills in facts.skills.values()
        for skill in skills
    ]


def add_skill(
    profile_dir: str | Path,
    name: str,
    category: Literal["hard", "soft", "domain"] | None,
) -> ManualSkillEntry:
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        token = normalize_skill(name)
        if not token:
            raise ValueError("skill name is required")

        ledger = load_manual_skills(_ledger_path(profile_dir))
        # Re-adding a currently-suppressed skill restores it rather than erroring:
        # dropping the suppress entry lets the name reappear on the next rebuild.
        was_suppressed = any(
            e.kind == "suppress" and normalize_skill(e.token) == token
            for e in ledger.entries
        )
        if token in _known_tokens(facts) and not was_suppressed:
            raise SkillAlreadyExistsError(f"'{name}' is already in your profile")
        ledger.entries = [
            e
            for e in ledger.entries
            if not (e.kind == "suppress" and normalize_skill(e.token) == token)
        ]
        entry = ManualSkillEntry(name=name, category=category, added_at=_utcnow())
        ledger.entries.append(entry)
        updated_facts, _warnings = apply_manual_skills(facts, ledger)
        save_facts(updated_facts, _facts_path(profile_dir))
        save_manual_skills(ledger, _ledger_path(profile_dir))
        rebuild_saved_matrix(profile_dir, updated_facts)
        return entry


def add_alias(profile_dir: str | Path, skill_id: str, alias: str) -> ManualAliasEntry:
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        target = next(
            (
                skill
                for skills in facts.skills.values()
                for skill in skills
                if skill.id == skill_id
            ),
            None,
        )
        if target is None:
            raise SkillNotFoundError(f"No skill '{skill_id}'")
        alias = alias.strip()
        if not alias:
            raise ValueError("alias text is required")
        if normalize_skill(alias) in _known_tokens(facts):
            raise SkillAlreadyExistsError(f"'{alias}' is already in your profile")

        entry = ManualAliasEntry(
            target_skill_token=normalize_skill(target.name),
            target_skill_display=target.name,
            alias_text=alias,
            added_at=_utcnow(),
        )
        ledger = load_manual_skills(_ledger_path(profile_dir))
        ledger.entries.append(entry)
        updated_facts, _warnings = apply_manual_skills(facts, ledger)
        save_facts(updated_facts, _facts_path(profile_dir))
        save_manual_skills(ledger, _ledger_path(profile_dir))
        rebuild_saved_matrix(profile_dir, updated_facts)
        return entry


def list_manual_entries(
    profile_dir: str | Path,
) -> list[ManualSkillEntry | ManualAliasEntry]:
    return load_manual_skills(_ledger_path(profile_dir)).entries


def remove_manual_entry(profile_dir: str | Path, entry_id: str) -> None:
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        ledger = load_manual_skills(_ledger_path(profile_dir))
        entry = next((e for e in ledger.entries if e.id == entry_id), None)
        if entry is None:
            raise ManualEntryNotFoundError(f"No manual entry '{entry_id}'")

        updated_facts = remove_manual_skill_entry(facts, entry)
        ledger.entries = [e for e in ledger.entries if e.id != entry_id]
        save_facts(updated_facts, _facts_path(profile_dir))
        save_manual_skills(ledger, _ledger_path(profile_dir))
        rebuild_saved_matrix(profile_dir, updated_facts)


def list_suppressed(profile_dir: str | Path) -> list[ManualSuppressEntry]:
    """Return the durable suppress entries (deleted skills awaiting restore)."""
    ledger = load_manual_skills(_ledger_path(profile_dir))
    return [e for e in ledger.entries if isinstance(e, ManualSuppressEntry)]


def delete_skill(profile_dir: str | Path, key: str) -> None:
    """Durably delete any live skill by matrix key / normalized token or alias.

    Appends a suppress entry keyed on the matched skill's canonical name token
    (so it can be listed and restored), removes the skill from live facts, and
    rebuilds the saved matrix. Any additive ``new_skill`` entry for the same
    token is intentionally left in place: ``apply_manual_skills`` always replays
    suppressions last, so the pair yields the deleted state now while keeping the
    add entry so ``restore_skill`` can bring a manually-added skill back.
    """
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        key_token = normalize_skill(key)
        match = next(
            (
                skill
                for skills in facts.skills.values()
                for skill in skills
                if normalize_skill(skill.name) == key_token
                or key_token in {normalize_skill(a) for a in skill.aliases}
            ),
            None,
        )
        if match is None:
            raise SkillNotFoundError(f"No skill '{key}'")
        # Key the suppression on the skill's own name, not the (possibly alias)
        # lookup token — replay matches skills by name, and restore uses this token.
        token = normalize_skill(match.name)
        ledger = load_manual_skills(_ledger_path(profile_dir))
        if not any(
            e.kind == "suppress" and normalize_skill(e.token) == token
            for e in ledger.entries
        ):
            ledger.entries.append(
                ManualSuppressEntry(
                    token=token, display=match.name, added_at=_utcnow()
                )
            )
        updated_facts, _warnings = apply_manual_skills(facts, ledger)
        save_facts(updated_facts, _facts_path(profile_dir))
        save_manual_skills(ledger, _ledger_path(profile_dir))
        rebuild_saved_matrix(profile_dir, updated_facts)


def restore_skill(profile_dir: str | Path, token: str) -> None:
    """Lift a suppression so the skill reappears on the next profile build."""
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        norm = normalize_skill(token)
        ledger = load_manual_skills(_ledger_path(profile_dir))
        if not any(
            e.kind == "suppress" and normalize_skill(e.token) == norm
            for e in ledger.entries
        ):
            raise ManualEntryNotFoundError(f"'{token}' is not suppressed")
        ledger.entries = [
            e
            for e in ledger.entries
            if not (e.kind == "suppress" and normalize_skill(e.token) == norm)
        ]
        updated_facts, _warnings = apply_manual_skills(facts, ledger)
        save_facts(updated_facts, _facts_path(profile_dir))
        save_manual_skills(ledger, _ledger_path(profile_dir))
        rebuild_saved_matrix(profile_dir, updated_facts)
