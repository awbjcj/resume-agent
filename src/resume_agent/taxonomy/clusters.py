"""Persisted synonym aliases and thematic skill grouping."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resume_agent.tracking.match_gap import normalize_skill


@dataclass
class ClusterMap:
    aliases: dict[str, str] = field(default_factory=dict)
    theme_of: dict[str, str] = field(default_factory=dict)
    theme_label: dict[str, str] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ClusterMap:
        return cls()


def _validated_map(
    value: Any,
    *,
    normalize_keys: bool = False,
    normalize_values: bool = False,
) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    validated: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            continue
        key = normalize_skill(raw_key) if normalize_keys else raw_key.strip()
        item = normalize_skill(raw_value) if normalize_values else raw_value.strip()
        if key and item:
            validated[key] = item
    return validated


def load_cluster_map(path: str | Path) -> ClusterMap:
    """Load and validate a cluster map; any unreadable boundary is empty."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ClusterMap.empty()
    if not isinstance(data, dict):
        return ClusterMap.empty()

    return ClusterMap(
        aliases=_validated_map(
            data.get("aliases"),
            normalize_keys=True,
            normalize_values=True,
        ),
        theme_of=_validated_map(data.get("theme_of"), normalize_keys=True),
        theme_label=_validated_map(data.get("theme_label")),
    )


def save_cluster_map(cmap: ClusterMap, path: str | Path) -> None:
    """Persist a cluster map deterministically via an atomic sibling replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "aliases": cmap.aliases,
        "theme_of": cmap.theme_of,
        "theme_label": cmap.theme_label,
    }
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
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
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def merge_cluster_map(existing: ClusterMap, new: ClusterMap) -> ClusterMap:
    """Monotonically add new entries while preserving existing decisions."""

    def merge_map(current: dict[str, str], proposed: dict[str, str]) -> dict[str, str]:
        merged = dict(proposed)
        merged.update(current)
        return merged

    return ClusterMap(
        aliases=merge_map(existing.aliases, new.aliases),
        theme_of=merge_map(existing.theme_of, new.theme_of),
        theme_label=merge_map(existing.theme_label, new.theme_label),
    )
