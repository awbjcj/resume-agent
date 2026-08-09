"""Durable generated taxonomy state beside the active cluster map.

The cluster map intentionally stays small and backwards compatible.  Runtime
details that explain *why* a canonical has not yet received a domain, and the
history needed to undo an automatic maintenance generation, live here instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    save_cluster_map,
)
from resume_agent.tracking.match_gap import normalize_skill


ALGORITHM_VERSION = "embedding-taxonomy-v1"
HISTORY_LIMIT = 10


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def taxonomy_root(cluster_path: str | Path) -> Path:
    """Return the tenant taxonomy directory for a profile cluster-map path."""

    profile_dir = Path(cluster_path).parent
    # Production paths are ``.../profile/cluster_map.json``.  Standalone
    # callers/tests may intentionally pass ``tmp/clusters.json`` instead;
    # keep their sidecars contained in that temporary directory.
    return (
        profile_dir.parent / "taxonomy"
        if profile_dir.name == "profile"
        else profile_dir / "taxonomy"
    )


def taxonomy_state_path(cluster_path: str | Path) -> Path:
    return taxonomy_root(cluster_path) / "taxonomy_state.json"


def taxonomy_generation_dir(cluster_path: str | Path) -> Path:
    return taxonomy_root(cluster_path) / "generations"


class GroupingStatus(ExtensibleModel):
    """Last durable grouping outcome for an unassigned canonical skill."""

    state: Literal["uncertain", "failed"] = "uncertain"
    reason: str
    last_attempted_at: str = Field(default_factory=_utcnow)


class TaxonomyGeneration(ExtensibleModel):
    """A pre-maintenance snapshot that can restore one generated generation."""

    id: str
    created_at: str
    snapshot: str


class TaxonomyState(ExtensibleModel):
    algorithm_version: str = ALGORITHM_VERSION
    generation_id: str | None = None
    maintenance_due: bool = True
    legacy_group_map_sha256: str | None = None
    grouping_status: dict[str, GroupingStatus] = Field(default_factory=dict)
    history: list[TaxonomyGeneration] = Field(default_factory=list)

    @property
    def can_undo(self) -> bool:
        return bool(self.history)


def _clean_state(value: object) -> TaxonomyState:
    if not isinstance(value, dict):
        return TaxonomyState()
    try:
        parsed = TaxonomyState.model_validate(value)
    except (TypeError, ValueError):
        return TaxonomyState()
    parsed.grouping_status = {
        token: status
        for raw_token, status in parsed.grouping_status.items()
        if (token := normalize_skill(raw_token))
    }
    parsed.history = [
        item for item in parsed.history if item.id.strip() and item.snapshot.strip()
    ][-HISTORY_LIMIT:]
    return parsed


def load_taxonomy_state(cluster_path: str | Path) -> TaxonomyState:
    try:
        payload = json.loads(
            taxonomy_state_path(cluster_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return TaxonomyState()
    return _clean_state(payload)


def save_taxonomy_state(
    state: TaxonomyState, cluster_path: str | Path
) -> TaxonomyState:
    """Atomically save a sanitized state file and clean expired snapshots."""

    destination = taxonomy_state_path(cluster_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    clean = _clean_state(state.model_dump(mode="python"))
    content = clean.model_dump_json(indent=2) + "\n"
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

    kept = {item.snapshot for item in clean.history}
    generation_dir = taxonomy_generation_dir(cluster_path)
    if generation_dir.exists():
        for candidate in generation_dir.glob("*.json"):
            if candidate.name not in kept:
                candidate.unlink(missing_ok=True)
    return clean


def set_grouping_statuses(
    cluster_path: str | Path,
    *,
    assigned: set[str],
    statuses: dict[str, GroupingStatus],
) -> TaxonomyState:
    state = load_taxonomy_state(cluster_path)
    for token in assigned:
        state.grouping_status.pop(normalize_skill(token), None)
    for token, status in statuses.items():
        normalized = normalize_skill(token)
        if normalized:
            state.grouping_status[normalized] = status
    return save_taxonomy_state(state, cluster_path)


def mark_legacy_group_map_imported(
    cluster_path: str | Path, group_map_path: str | Path
) -> TaxonomyState:
    """Record a legacy hint artifact without taking ownership of its contents."""

    try:
        digest = hashlib.sha256(Path(group_map_path).read_bytes()).hexdigest()
    except OSError:
        return load_taxonomy_state(cluster_path)
    state = load_taxonomy_state(cluster_path)
    if state.legacy_group_map_sha256 != digest:
        state.legacy_group_map_sha256 = digest
        save_taxonomy_state(state, cluster_path)
    return state


def snapshot_before_maintenance(
    cluster_path: str | Path, cmap: ClusterMap
) -> tuple[TaxonomyState, TaxonomyGeneration]:
    """Persist a pre-maintenance map and return the generation to activate."""

    generation_id = uuid4().hex
    filename = f"{generation_id}.json"
    destination = taxonomy_generation_dir(cluster_path) / filename
    save_cluster_map(cmap, destination)
    state = load_taxonomy_state(cluster_path)
    generation = TaxonomyGeneration(
        id=generation_id,
        created_at=_utcnow(),
        snapshot=filename,
    )
    state.history.append(generation)
    state.history = state.history[-HISTORY_LIMIT:]
    state.generation_id = generation_id
    state.maintenance_due = False
    save_taxonomy_state(state, cluster_path)
    return state, generation


def undo_last_maintenance(cluster_path: str | Path) -> tuple[ClusterMap, TaxonomyState]:
    """Restore the last pre-maintenance snapshot, leaving corrections to replay later."""

    state = load_taxonomy_state(cluster_path)
    if not state.history:
        raise ValueError("no taxonomy maintenance generation is available to undo")
    generation = state.history.pop()
    snapshot = taxonomy_generation_dir(cluster_path) / generation.snapshot
    restored = load_cluster_map(snapshot)
    if not (restored.aliases or restored.domain_of or restored.domain_label):
        raise ValueError("taxonomy maintenance snapshot is unreadable")
    state.generation_id = state.history[-1].id if state.history else None
    state.maintenance_due = True
    save_taxonomy_state(state, cluster_path)
    return restored, state
