"""Durable ledger of hand-added skills/aliases, replayed onto facts.json.

facts.json has no identity that survives a full profile rebuild --
``build_corpus_profile`` reconstructs it from source documents from scratch,
minting fresh ``Skill.id`` values every time. So this ledger references skills
by normalized name (the same identity ``profile/merge.py`` already uses for
cross-fragment dedup), not by id, and ``apply_manual_skills`` is replayed both
right after a mutation (against the live facts) and right after a rebuild
(against the freshly synthesized facts) -- one function, one definition of
what a manual entry means.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import Field

from resume_agent.models.base import ExtensibleModel, new_id
from resume_agent.models.profile import ProfileFacts, Skill
from resume_agent.tracking.match_gap import normalize_skill

_DEFAULT_CATEGORY = "hard"
_MANUAL_SKILLS_LOCKS: dict[Path, threading.RLock] = {}
_MANUAL_SKILLS_LOCKS_GUARD = threading.Lock()


@contextmanager
def manual_skills_lock(profile_dir: str | Path) -> Iterator[None]:
    """Serialize live facts, ledger, and derived-matrix mutations."""
    key = Path(profile_dir).resolve()
    with _MANUAL_SKILLS_LOCKS_GUARD:
        lock = _MANUAL_SKILLS_LOCKS.setdefault(key, threading.RLock())
    with lock:
        yield


class ManualSkillEntry(ExtensibleModel):
    id: str = Field(default_factory=new_id)
    kind: Literal["new_skill"] = "new_skill"
    name: str
    category: Literal["hard", "soft", "domain"] | None = None
    added_at: str = ""


class ManualAliasEntry(ExtensibleModel):
    id: str = Field(default_factory=new_id)
    kind: Literal["alias"] = "alias"
    target_skill_token: str
    target_skill_display: str
    alias_text: str
    added_at: str = ""


class ManualSuppressEntry(ExtensibleModel):
    id: str = Field(default_factory=new_id)
    kind: Literal["suppress"] = "suppress"
    token: str
    display: str
    added_at: str = ""


ManualEntry = Annotated[
    Union[ManualSkillEntry, ManualAliasEntry, ManualSuppressEntry],
    Field(discriminator="kind"),
]


class ManualSkillsLedger(ExtensibleModel):
    entries: list[ManualEntry] = Field(default_factory=list)


def _find_skill(facts: ProfileFacts, token: str) -> tuple[str, Skill] | None:
    for bucket, skills in facts.skills.items():
        for skill in skills:
            if normalize_skill(skill.name) == token:
                return bucket, skill
    return None


def _drop_token(facts: ProfileFacts, token: str) -> None:
    """Remove any skill matching ``token`` from every bucket, pruning empties."""
    for bucket_name in list(facts.skills):
        bucket = facts.skills[bucket_name]
        bucket[:] = [s for s in bucket if normalize_skill(s.name) != token]
        if not bucket:
            del facts.skills[bucket_name]


def apply_manual_skill_entry(
    facts: ProfileFacts,
    entry: ManualSkillEntry | ManualAliasEntry | ManualSuppressEntry,
) -> tuple[ProfileFacts, str | None]:
    """Apply one ledger entry to ``facts``, returning (facts, warning|None).

    Idempotent: reapplying an already-applied entry is a no-op, so a full
    ledger can always be replayed onto facts that already reflect it.
    """
    updated = facts.model_copy(deep=True)
    if isinstance(entry, ManualSuppressEntry):
        _drop_token(updated, normalize_skill(entry.token))
        return updated, None

    if isinstance(entry, ManualSkillEntry):
        token = normalize_skill(entry.name)
        existing = {
            normalize_skill(alias)
            for skills in updated.skills.values()
            for skill in skills
            for alias in (skill.name, *skill.aliases)
        }
        if token in existing:
            return updated, None
        category = entry.category or _DEFAULT_CATEGORY
        bucket = updated.skills.setdefault(category, [])
        bucket.append(Skill(name=entry.name, category=category))
        return updated, None

    found = _find_skill(updated, entry.target_skill_token)
    if found is None:
        return facts, (
            f"Manual alias '{entry.alias_text}' could not be reattached -- "
            f"its target skill '{entry.target_skill_display}' was not found."
        )
    _bucket, skill = found
    if normalize_skill(entry.alias_text) in {
        normalize_skill(alias) for alias in (skill.name, *skill.aliases)
    }:
        return updated, None
    skill.aliases.append(entry.alias_text)
    return updated, None


def apply_manual_skills(
    facts: ProfileFacts, ledger: ManualSkillsLedger
) -> tuple[ProfileFacts, list[str]]:
    """Replay adds/aliases first, then suppressions, collecting skip warnings.

    Suppressions run last so a deleted synthesized/inferred/manual skill stays
    gone even when an additive entry for the same token was recorded earlier.
    """
    warnings: list[str] = []
    additive = [e for e in ledger.entries if e.kind != "suppress"]
    suppressive = [e for e in ledger.entries if e.kind == "suppress"]
    for entry in (*additive, *suppressive):
        facts, warning = apply_manual_skill_entry(facts, entry)
        if warning is not None:
            warnings.append(warning)
    return facts, warnings


def save_manual_skills(ledger: ManualSkillsLedger, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(ledger.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_manual_skills(path: str | Path) -> ManualSkillsLedger:
    try:
        return ManualSkillsLedger.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except OSError:
        return ManualSkillsLedger()
