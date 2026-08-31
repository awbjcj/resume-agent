"""Persisted synonym aliases and category-parented skill domains."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from resume_tailor_harness.taxonomy.vocabulary import SKILL_GROUPS
from resume_tailor_harness.tracking.match_gap import normalize_skill

_NONALNUM = re.compile(r"[^a-z0-9]+")


@dataclass
class ClusterMap:
    aliases: dict[str, str] = field(default_factory=dict)
    domain_of: dict[str, str] = field(default_factory=dict)
    domain_label: dict[str, str] = field(default_factory=dict)
    category_of: dict[str, str] = field(default_factory=dict)

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


def _sanitize_aliases(aliases: dict[str, str]) -> dict[str, str]:
    """Flatten valid alias components while dropping paths that enter a cycle."""
    flattened: dict[str, str] = {}
    invalid: set[str] = set()
    for alias in aliases:
        if alias in flattened or alias in invalid:
            continue
        path: list[str] = []
        positions: set[str] = set()
        token = alias
        terminal: str | None = None
        while True:
            if token in flattened:
                terminal = flattened[token]
                break
            if token in invalid or token in positions:
                invalid.update(path)
                break
            target = aliases.get(token)
            if target is None:
                terminal = token
                break
            if target == token:
                flattened[token] = token
                terminal = token
                break
            positions.add(token)
            path.append(token)
            token = target
        if terminal is not None:
            for path_token in path:
                flattened[path_token] = terminal
    return {alias: flattened[alias] for alias in aliases if alias in flattened}


def _canonicalize_domain_keys(
    domain_of: dict[str, str], aliases: dict[str, str]
) -> dict[str, str]:
    """Move domains to terminal tokens, preferring an explicit terminal domain."""
    canonical: dict[str, str] = {}
    for token, domain_id in domain_of.items():
        canonical.setdefault(aliases.get(token, token), domain_id)
    for token, domain_id in domain_of.items():
        if aliases.get(token, token) == token:
            canonical[token] = domain_id
    return canonical


def _sanitized_categories(
    raw: object, domain_of: dict[str, str], domain_label: dict[str, str]
) -> dict[str, str]:
    category_of = {
        domain_id: slug
        for domain_id, slug in _validated_map(raw).items()
        if slug in SKILL_GROUPS
    }
    for domain_id in set(domain_of.values()) | set(domain_label):
        category_of.setdefault(domain_id, "other")
    return category_of


def _cluster_map_from_data(data: object) -> ClusterMap:
    if not isinstance(data, dict):
        raise ValueError("cluster map must contain a JSON object")

    raw_aliases = _validated_map(
        data.get("aliases"),
        normalize_keys=True,
        normalize_values=True,
    )
    aliases = _sanitize_aliases(raw_aliases)
    raw_domains = _validated_map(data.get("domain_of"), normalize_keys=True)
    domain_of = _canonicalize_domain_keys(
        {
            token: domain_id
            for token, domain_id in raw_domains.items()
            if token not in raw_aliases or token in aliases
        },
        aliases,
    )
    domain_label = _validated_map(data.get("domain_label"))
    return ClusterMap(
        aliases=aliases,
        domain_of=domain_of,
        domain_label=domain_label,
        category_of=_sanitized_categories(
            data.get("category_of"), domain_of, domain_label
        ),
    )


def load_cluster_map(path: str | Path) -> ClusterMap:
    """Load and validate a cluster map; any unreadable boundary is empty."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return _cluster_map_from_data(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return ClusterMap.empty()


def load_cluster_map_strict(path: str | Path) -> ClusterMap:
    """Load a mutation input, distinguishing absence from corrupt last-good data."""

    source = Path(path)
    if not source.exists():
        return ClusterMap.empty()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        return _cluster_map_from_data(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cluster map is unreadable: {source}") from exc


def save_cluster_map(cmap: ClusterMap, path: str | Path) -> None:
    """Persist a cluster map deterministically via an atomic sibling replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "aliases": cmap.aliases,
        "domain_of": cmap.domain_of,
        "domain_label": cmap.domain_label,
        "category_of": cmap.category_of,
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
    existing_domains = _canonicalize_domain_keys(existing.domain_of, aliases)
    new_domains = _canonicalize_domain_keys(new.domain_of, aliases)
    return ClusterMap(
        aliases=aliases,
        domain_of=merge_map(existing_domains, new_domains),
        domain_label=merge_map(existing.domain_label, new.domain_label),
        category_of=merge_map(existing.category_of, new.category_of),
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
    domain_of = {
        canonical: domain_id
        for canonical, domain_id in cmap.domain_of.items()
        if canonical in canonicals
    }
    used_domain_ids = set(domain_of.values())
    domain_label = {
        domain_id: label
        for domain_id, label in cmap.domain_label.items()
        if domain_id in used_domain_ids
    }
    category_of = {
        domain_id: slug
        for domain_id, slug in cmap.category_of.items()
        if domain_id in used_domain_ids
    }
    return ClusterMap(
        aliases=aliases,
        domain_of=domain_of,
        domain_label=domain_label,
        category_of=category_of,
    )


def slugify_domain(label: str) -> str:
    """Convert a domain label to a deterministic lowercase identifier."""
    return _NONALNUM.sub("-", label.lower()).strip("-")


def allocate_domain_ids(
    *,
    existing_labels: dict[str, str],
    proposed_labels: Collection[str],
) -> dict[str, str]:
    """Allocate deterministic IDs without overwriting stable existing labels."""
    existing_by_label = {
        normalize_skill(label): domain_id
        for domain_id, label in existing_labels.items()
    }
    proposed_by_key: dict[str, str] = {}
    for label in proposed_labels:
        label_key = normalize_skill(label)
        if not label_key or not slugify_domain(label):
            raise ValueError("domain label must contain an alphanumeric character")
        proposed_by_key.setdefault(label_key, label.strip())
    occupied = set(existing_labels)
    allocated: dict[str, str] = {}
    for label_key in sorted(proposed_by_key):
        if label_key in existing_by_label:
            allocated[label_key] = existing_by_label[label_key]
            continue
        base = slugify_domain(proposed_by_key[label_key])
        if not base:
            raise ValueError("domain label must contain an alphanumeric character")
        domain_id = base
        suffix = 2
        while domain_id in occupied:
            domain_id = f"{base}-{suffix}"
            suffix += 1
        occupied.add(domain_id)
        allocated[label_key] = domain_id
    return allocated
