"""Match-gap cluster refresh use-case."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlmodel import Session

from resume_agent.progress import ProgressReporter
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    merge_cluster_map,
    save_cluster_map,
)
from resume_agent.tracking.canonicalize import Themer
from resume_agent.tracking.match_gap import Canonicalizer, collect_target_skill_tokens

_NONALNUM = re.compile(r"[^a-z0-9]+")
_REFRESH_LOCK = threading.Lock()


def slugify_theme(label: str) -> str:
    """Convert a theme label to a deterministic lowercase identifier."""
    return _NONALNUM.sub("-", label.lower()).strip("-")


def _validated_aliases(raw: Any, tokens: set[str]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ValueError("canonicalizer output must be a mapping")

    aliases = {token: token for token in tokens}
    for key, value in raw.items():
        if not isinstance(key, str) or key not in tokens:
            raise ValueError("canonicalizer output contains an unknown input key")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("canonicalizer values must be nonblank strings")
        canonical = value.strip()
        if canonical not in tokens:
            raise ValueError("canonicalizer values must come from the input tokens")
        aliases[key] = canonical

    for canonical in aliases.values():
        if aliases[canonical] != canonical:
            raise ValueError("canonicalizer values must be terminal input tokens")
    return aliases


def _validated_themes(
    raw: Any,
    canonical_tokens: set[str],
) -> list[tuple[str, str, list[str]]]:
    if not isinstance(raw, list):
        raise ValueError("theme output must be a list")

    validated: list[tuple[str, str, list[str]]] = []
    assigned: set[str] = set()
    theme_ids: set[str] = set()

    for group in raw:
        if not isinstance(group, (list, tuple)) or len(group) != 2:
            raise ValueError("theme groups must be label/member pairs")
        raw_label, raw_members = group
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError("theme labels must be nonblank strings")
        label = raw_label.strip()
        theme_id = slugify_theme(label)
        if not theme_id:
            raise ValueError("theme id must be nonblank")
        if theme_id in theme_ids:
            raise ValueError(f"theme id collision: {theme_id!r}")
        theme_ids.add(theme_id)

        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("theme groups must contain at least one skill token")
        members: list[str] = []
        group_members: set[str] = set()
        for raw_member in raw_members:
            if not isinstance(raw_member, str) or not raw_member.strip():
                raise ValueError("theme skill members must be nonblank strings")
            member = raw_member.strip()
            if member not in canonical_tokens:
                raise ValueError(f"theme output contains an unknown skill: {member!r}")
            if member in group_members:
                raise ValueError(f"duplicate skill token in theme: {member!r}")
            if member in assigned:
                raise ValueError(f"skill token appears in multiple themes: {member!r}")
            group_members.add(member)
            assigned.add(member)
            members.append(member)

        validated.append((theme_id, label, members))

    missing = canonical_tokens - assigned
    if missing:
        raise ValueError(f"theme output is missing skill tokens: {sorted(missing)!r}")
    return validated


def refresh_clusters(
    session: Session,
    *,
    dedup: Canonicalizer,
    themer: Themer,
    path: str | Path,
    reporter: ProgressReporter | None = None,
) -> dict[str, int]:
    """Regenerate target-skill aliases and themes without losing prior choices."""
    with _REFRESH_LOCK:
        if reporter is not None:
            reporter.begin(2, "Refreshing skill clusters")

        try:
            tokens = collect_target_skill_tokens(session)
            if reporter is not None:
                reporter.checkpoint()
            aliases = _validated_aliases(dedup(tokens), tokens)
            canonical_tokens = set(aliases.values())
            if reporter is not None:
                reporter.step(1, label="Canonicalized target skills")
                reporter.checkpoint()

            themes = _validated_themes(themer(canonical_tokens), canonical_tokens)
            if reporter is not None:
                reporter.step(2, label="Grouped target skills into themes")

            proposed = ClusterMap(
                aliases=aliases,
                theme_of={
                    skill: theme_id
                    for theme_id, _label, members in themes
                    for skill in members
                },
                theme_label={theme_id: label for theme_id, label, _members in themes},
            )
            existing = load_cluster_map(path)
            merged = merge_cluster_map(existing, proposed)
            save_cluster_map(merged, path)
        except Exception as exc:
            if reporter is not None:
                reporter.done(error=str(exc))
            raise

        result = {"skills": len(canonical_tokens), "themes": len(themes)}
        if reporter is not None:
            reporter.done(result=result)
        return result
