"""Durable user corrections for derived skill-group assignments."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.taxonomy.vocabulary import LEGACY_GROUP_REMAP, SKILL_GROUPS
from resume_tailor_harness.tracking.match_gap import normalize_skill


def corrections_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / "group_corrections.json"


class GroupCorrection(ExtensibleModel):
    group: str
    corrected_at: str = ""


class GroupCorrections(ExtensibleModel):
    corrections: dict[str, GroupCorrection] = Field(default_factory=dict)

    def as_map(self) -> dict[str, str]:
        return {token: entry.group for token, entry in self.corrections.items()}


def load_group_corrections(path: str | Path) -> GroupCorrections:
    try:
        ledger = GroupCorrections.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return GroupCorrections()

    clean: dict[str, GroupCorrection] = {}
    for raw_token, entry in ledger.corrections.items():
        token = normalize_skill(raw_token)
        entry.group = LEGACY_GROUP_REMAP.get(entry.group, entry.group)
        if token and entry.group in SKILL_GROUPS:
            clean.setdefault(token, entry)
    ledger.corrections = clean
    return ledger


def save_group_corrections(ledger: GroupCorrections, path: str | Path) -> None:
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
