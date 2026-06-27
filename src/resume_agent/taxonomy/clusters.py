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


def _flatten_aliases(aliases: dict[str, str]) -> dict[str, str]:
    """Resolve every alias to a terminal token; only self-cycles are valid."""
    flattened: dict[str, str] = {}
    resolving: set[str] = set()

    def terminal_for(token: str) -> str:
        if token in flattened:
            return flattened[token]
        if token in resolving:
            raise ValueError(f"alias cycle detected at {token!r}")

        target = aliases.get(token)
        if target is None:
            return token
        if target == token:
            flattened[token] = token
            return token

        resolving.add(token)
        try:
            terminal = terminal_for(target)
        finally:
            resolving.remove(token)
        flattened[token] = terminal
        return terminal

    for alias in aliases:
        terminal_for(alias)
    return flattened


def _canonicalize_theme_keys(
    theme_of: dict[str, str], aliases: dict[str, str]
) -> dict[str, str]:
    """Move themes to terminal tokens, preferring an explicit terminal theme."""
    canonical: dict[str, str] = {}
    for token, theme_id in theme_of.items():
        canonical.setdefault(aliases.get(token, token), theme_id)
    for token, theme_id in theme_of.items():
        if aliases.get(token, token) == token:
            canonical[token] = theme_id
    return canonical


def load_cluster_map(path: str | Path) -> ClusterMap:
    """Load and validate a cluster map; any unreadable boundary is empty."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ClusterMap.empty()
    if not isinstance(data, dict):
        return ClusterMap.empty()

    aliases = _validated_map(
        data.get("aliases"),
        normalize_keys=True,
        normalize_values=True,
    )
    try:
        aliases = _flatten_aliases(aliases)
    except ValueError:
        return ClusterMap.empty()
    theme_of = _canonicalize_theme_keys(
        _validated_map(data.get("theme_of"), normalize_keys=True),
        aliases,
    )
    return ClusterMap(
        aliases=aliases,
        theme_of=theme_of,
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
    """Monotonically add entries while enforcing terminal alias targets."""

    def merge_map(current: dict[str, str], proposed: dict[str, str]) -> dict[str, str]:
        merged = dict(proposed)
        merged.update(current)
        return merged

    aliases = _flatten_aliases(merge_map(existing.aliases, new.aliases))
    existing_themes = _canonicalize_theme_keys(existing.theme_of, aliases)
    new_themes = _canonicalize_theme_keys(new.theme_of, aliases)
    return ClusterMap(
        aliases=aliases,
        theme_of=merge_map(existing_themes, new_themes),
        theme_label=merge_map(existing.theme_label, new.theme_label),
    )
