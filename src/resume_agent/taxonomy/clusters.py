"""Persisted synonym aliases and thematic skill grouping."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resume_agent.tracking.match_gap import normalize_skill

_NONALNUM = re.compile(r"[^a-z0-9]+")


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

    for alias in aliases:
        if alias in flattened:
            continue

        path: list[str] = []
        seen: set[str] = set()
        token = alias
        while True:
            if token in flattened:
                terminal = flattened[token]
                break
            if token in seen:
                raise ValueError(f"alias cycle detected at {token!r}")

            target = aliases.get(token)
            if target is None:
                terminal = token
                break
            if target == token:
                flattened[token] = token
                terminal = token
                break

            seen.add(token)
            path.append(token)
            token = target

        for path_token in path:
            flattened[path_token] = terminal

    return {alias: flattened[alias] for alias in aliases}


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
    """Add entries without redirecting existing terminal canonical tokens."""

    def merge_map(current: dict[str, str], proposed: dict[str, str]) -> dict[str, str]:
        merged = dict(proposed)
        merged.update(current)
        return merged

    existing_aliases = _flatten_aliases(existing.aliases)
    protected_aliases = dict(existing_aliases)
    for terminal in existing_aliases.values():
        protected_aliases.setdefault(terminal, terminal)
    aliases = _flatten_aliases(merge_map(protected_aliases, new.aliases))
    existing_themes = _canonicalize_theme_keys(existing.theme_of, aliases)
    new_themes = _canonicalize_theme_keys(new.theme_of, aliases)
    return ClusterMap(
        aliases=aliases,
        theme_of=merge_map(existing_themes, new_themes),
        theme_label=merge_map(existing.theme_label, new.theme_label),
    )


def prune_cluster_map(cmap: ClusterMap, demanded_tokens: set[str]) -> ClusterMap:
    """Remove entries no current target job needs while keeping live terminals."""
    aliases = {
        token: canonical
        for token, canonical in cmap.aliases.items()
        if token in demanded_tokens
    }
    canonicals = set(aliases.values())
    for canonical in canonicals:
        aliases.setdefault(canonical, canonical)
    theme_of = {
        canonical: theme_id
        for canonical, theme_id in cmap.theme_of.items()
        if canonical in canonicals
    }
    used_theme_ids = set(theme_of.values())
    theme_label = {
        theme_id: label
        for theme_id, label in cmap.theme_label.items()
        if theme_id in used_theme_ids
    }
    return ClusterMap(aliases=aliases, theme_of=theme_of, theme_label=theme_label)


def slugify_theme(label: str) -> str:
    """Convert a theme label to a deterministic lowercase identifier."""
    return _NONALNUM.sub("-", label.lower()).strip("-")


def allocate_theme_ids(
    *,
    existing_labels: dict[str, str],
    proposed_labels: Collection[str],
) -> dict[str, str]:
    """Allocate deterministic IDs without overwriting stable existing labels."""
    existing_by_label = {
        normalize_skill(label): theme_id for theme_id, label in existing_labels.items()
    }
    proposed_by_key: dict[str, str] = {}
    for label in proposed_labels:
        label_key = normalize_skill(label)
        if not label_key or not slugify_theme(label):
            raise ValueError("theme label must contain an alphanumeric character")
        proposed_by_key.setdefault(label_key, label.strip())
    occupied = set(existing_labels)
    allocated: dict[str, str] = {}
    for label_key in sorted(proposed_by_key):
        if label_key in existing_by_label:
            allocated[label_key] = existing_by_label[label_key]
            continue
        base = slugify_theme(proposed_by_key[label_key])
        if not base:
            raise ValueError("theme label must contain an alphanumeric character")
        theme_id = base
        suffix = 2
        while theme_id in occupied:
            theme_id = f"{base}-{suffix}"
            suffix += 1
        occupied.add(theme_id)
        allocated[label_key] = theme_id
    return allocated
