"""One immutable, fully resolved read of a profile's effective taxonomy.

This module holds only taxonomy-layer types plus plain collections, so it never
imports from ``profile``. Precedence lives here and nowhere else.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol, runtime_checkable

from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
)
from resume_agent.taxonomy.state import TaxonomyState
from resume_agent.tracking.match_gap import normalize_skill


@runtime_checkable
class OverrideView(Protocol):
    """Structural view of ``profile.matrix.Overrides``.

    Declaring the protocol here lets the taxonomy package consume profile
    overrides without importing the profile package and inverting the layering.
    """

    alias: dict[str, str]
    forbid_alias: list[list[str]]
    ban: list[str]
    category: dict[str, str]
    group: dict[str, str]


@dataclass(frozen=True)
class TaxonomyManifest:
    """Component hashes for traceability. Never compared for freshness."""

    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""


@dataclass(frozen=True)
class OverrideConflict:
    """A token where a correction and an override disagree."""

    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]


def _flatten(aliases: dict[str, str]) -> dict[str, str]:
    """Resolve each alias to a terminal token; a cycle is corrupt input."""
    flattened: dict[str, str] = {}
    for start in set(aliases) | set(aliases.values()):
        token = start
        seen: set[str] = set()
        while token in aliases and aliases[token] != token:
            if token in seen:
                raise ValueError(f"alias cycle detected at {token!r}")
            seen.add(token)
            token = aliases[token]
        if start != token:
            flattened[start] = token
    return flattened


def _normalized_aliases(*sources: Mapping[str, str]) -> dict[str, str]:
    """Normalize aliases before cycle validation without changing precedence."""
    normalized: dict[str, str] = {}
    for source in sources:
        for raw_token, raw_head in source.items():
            token = normalize_skill(raw_token)
            head = normalize_skill(raw_head)
            if token and head:
                normalized[token] = head
    return normalized


def _digest(payload: object) -> str:
    """Return a deterministic SHA-256 over canonical JSON."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _semantic_digest(
    effective: ClusterMap,
    banned: frozenset[str],
    retired: frozenset[str],
) -> str:
    """Hash the projections that change derived artifact content."""
    return _digest(
        {
            "effective": asdict(effective),
            "banned": sorted(banned),
            "retired": sorted(retired),
        }
    )


@dataclass(frozen=True)
class EffectiveTaxonomy:
    cluster_map: ClusterMap
    banned_keys: frozenset[str] = frozenset()
    retired_keys: frozenset[str] = frozenset()
    category_overrides: Mapping[str, str] = field(default_factory=dict)
    group_overrides: Mapping[str, str] = field(default_factory=dict)
    state: TaxonomyState = field(default_factory=TaxonomyState)
    conflicts: tuple[OverrideConflict, ...] = ()
    semantic_revision: str = ""
    projection_revision: str = ""
    manifest: TaxonomyManifest = field(default_factory=TaxonomyManifest)

    @property
    def is_populated(self) -> bool:
        """Whether a usable taxonomy exists."""
        return bool(self.cluster_map.aliases or self.cluster_map.domain_of)

    @classmethod
    def from_parts(
        cls,
        cluster_map: ClusterMap,
        *,
        corrections: TaxonomyCorrections | None = None,
        overrides: OverrideView | None = None,
        state: TaxonomyState | None = None,
    ) -> "EffectiveTaxonomy":
        """Resolve generated -> corrections -> overrides -> forbid_alias.

        This is pure: ``profile.effective.build_effective_taxonomy`` is the
        I/O shell around it.
        """
        corrections = corrections or TaxonomyCorrections()
        state = state or TaxonomyState()

        # ``apply_taxonomy_corrections`` sanitizes persisted input. The public
        # constructor must instead surface a direct corrupt cycle to callers.
        _flatten(_normalized_aliases(cluster_map.aliases, corrections.aliases))

        resolved = apply_taxonomy_corrections(cluster_map, corrections)
        aliases = dict(resolved.aliases)
        if overrides is not None:
            aliases.update(_normalized_aliases(overrides.alias))
        aliases = _flatten(aliases)

        if overrides is not None:
            for pair in overrides.forbid_alias:
                if len(pair) != 2:
                    continue
                first, second = (normalize_skill(token) for token in pair)
                if not first or not second or first == second:
                    continue
                if aliases.get(first) == second:
                    aliases.pop(first, None)
                if aliases.get(second) == first:
                    aliases.pop(second, None)

        conflicts: list[OverrideConflict] = []
        if overrides is not None:
            override_aliases = _normalized_aliases(overrides.alias)
            for token, raw_correction_head in _normalized_aliases(
                corrections.aliases
            ).items():
                correction_head = resolved.aliases.get(token, raw_correction_head)
                override_head = override_aliases.get(token, "")
                if override_head and override_head != correction_head:
                    conflicts.append(
                        OverrideConflict(
                            token=token,
                            correction_head=correction_head,
                            override_head=override_head,
                            resolution="override",
                        )
                    )
                elif aliases.get(token) != correction_head:
                    conflicts.append(
                        OverrideConflict(
                            token=token,
                            correction_head=correction_head,
                            override_head="",
                            resolution="forbid_alias",
                        )
                    )

        domain_of = {
            aliases.get(token, token): domain
            for token, domain in resolved.domain_of.items()
        }
        effective = ClusterMap(
            aliases=aliases,
            domain_of=domain_of,
            domain_label=dict(resolved.domain_label),
            category_of=dict(resolved.category_of),
        )
        banned = frozenset(
            aliases.get(token, token)
            for raw in (overrides.ban if overrides is not None else [])
            if (token := normalize_skill(raw))
        )
        retired = frozenset(state.retired_skills)
        semantic = _semantic_digest(effective, banned, retired)
        projection = _digest(
            {
                "category": dict(overrides.category) if overrides else {},
                "group": dict(overrides.group) if overrides else {},
                "semantic": semantic,
            }
        )
        return cls(
            cluster_map=effective,
            banned_keys=banned,
            retired_keys=retired,
            category_overrides=dict(overrides.category) if overrides else {},
            group_overrides=dict(overrides.group) if overrides else {},
            state=state,
            conflicts=tuple(sorted(conflicts, key=lambda item: item.token)),
            semantic_revision=semantic,
            projection_revision=projection,
            manifest=TaxonomyManifest(semantic=semantic),
        )
