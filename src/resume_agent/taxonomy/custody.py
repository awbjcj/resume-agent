"""Workspace-scoped custody for the persisted Cluster map artifact set."""

from __future__ import annotations

import hashlib
import json
import threading
import weakref
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from resume_agent.taxonomy.clusters import ClusterMap, load_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
)
from resume_agent.taxonomy.state import TaxonomyState, load_taxonomy_state


_LOCKS_GUARD = threading.Lock()
_WORKSPACE_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
    weakref.WeakValueDictionary()
)


def _identity(path: str | Path) -> Path:
    """Use one stable identity for every spelling of a Cluster map path."""

    return Path(path).resolve()


def workspace_taxonomy_lock(path: str | Path) -> threading.RLock:
    """Return the mutation lock for the Workspace containing ``path``.

    Different Workspaces must not serialize remote classification work behind
    one process-wide lock.  Every mutation of one Workspace's generated map,
    corrections, or state does share this lock.
    """

    key = _identity(path)
    with _LOCKS_GUARD:
        return _WORKSPACE_LOCKS.setdefault(key, threading.RLock())


@dataclass(frozen=True)
class TaxonomySnapshot:
    """One coherent read of the Cluster map artifact set."""

    generated: ClusterMap
    corrections: TaxonomyCorrections
    effective: ClusterMap
    state: TaxonomyState
    revision: str
    generated_sha256: str = ""
    corrections_sha256: str = ""
    state_sha256: str = ""


def _component(payload: object) -> str:
    """Fingerprint one persisted component in stable key order."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _revision(
    generated: ClusterMap,
    corrections: TaxonomyCorrections,
    state: TaxonomyState,
) -> str:
    """Fingerprint the complete persisted artifact set in stable key order."""

    payload = {
        "generated": asdict(generated),
        "corrections": corrections.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class TaxonomyCustody:
    """Own locking and coherent reads for one Workspace's Cluster map."""

    def __init__(
        self,
        cluster_path: str | Path,
        corrections_path: str | Path,
    ) -> None:
        self.cluster_path = _identity(cluster_path)
        self.corrections_path = Path(corrections_path).resolve()
        self._lock = workspace_taxonomy_lock(self.cluster_path)

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Serialize a complete mutation of this Workspace's artifact set."""

        with self._lock:
            yield

    def read(self) -> TaxonomySnapshot:
        """Read generated data, user intent, and lifecycle state coherently."""

        with self._lock:
            generated = load_cluster_map(self.cluster_path)
            corrections = load_taxonomy_corrections(self.corrections_path)
            state = load_taxonomy_state(self.cluster_path)
            return TaxonomySnapshot(
                generated=generated,
                corrections=corrections,
                effective=apply_taxonomy_corrections(generated, corrections),
                state=state,
                revision=_revision(generated, corrections, state),
                generated_sha256=_component(asdict(generated)),
                corrections_sha256=_component(corrections.model_dump(mode="json")),
                state_sha256=_component(state.model_dump(mode="json")),
            )
