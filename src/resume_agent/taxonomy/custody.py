"""Workspace-scoped custody for the persisted Cluster map artifact set."""

from __future__ import annotations

import hashlib
import json
import threading
import weakref
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, TypeVar

from filelock import FileLock

from resume_agent.rollback import rollback_scope
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    load_cluster_map_strict,
)
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
    load_taxonomy_corrections_strict,
)
from resume_agent.taxonomy.state import (
    TaxonomyState,
    load_taxonomy_state,
    load_taxonomy_state_strict,
    taxonomy_state_path,
)


_LOCKS_GUARD = threading.Lock()
_WORKSPACE_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
    weakref.WeakValueDictionary()
)
_ARTIFACT_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
    weakref.WeakValueDictionary()
)
_PROCESS_LOCKS: weakref.WeakValueDictionary[Path, FileLock] = (
    weakref.WeakValueDictionary()
)
T = TypeVar("T")


class TaxonomyConflictError(RuntimeError):
    """A persisted taxonomy input changed after remote classification began."""


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


def _workspace_artifact_lock(path: str | Path) -> threading.RLock:
    key = _identity(path)
    with _LOCKS_GUARD:
        return _ARTIFACT_LOCKS.setdefault(key, threading.RLock())


def _workspace_process_lock(path: str | Path) -> FileLock:
    key = _identity(path)
    lock_path = key.with_name(f".{key.name}.lock")
    with _LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(
            key,
            FileLock(lock_path, is_singleton=True),
        )


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
    effective_sha256: str = ""


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
        self._operation_lock = workspace_taxonomy_lock(self.cluster_path)
        self._artifact_lock = _workspace_artifact_lock(self.cluster_path)
        self._process_lock = _workspace_process_lock(self.cluster_path)

    @contextmanager
    def _artifacts(self) -> Iterator[None]:
        """Hold the in-process and on-disk guards for one artifact transaction."""

        with self._artifact_lock:
            self.cluster_path.parent.mkdir(parents=True, exist_ok=True)
            with self._process_lock:
                yield

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Admit one long-running taxonomy mutation without blocking readers."""

        with self._operation_lock:
            yield

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Serialize a complete mutation of this Workspace's artifact set."""

        with self._operation_lock:
            with self._artifacts():
                self._read_unlocked(strict_generated=True)
                yield

    def _read_unlocked(self, *, strict_generated: bool) -> TaxonomySnapshot:
        generated = (
            load_cluster_map_strict(self.cluster_path)
            if strict_generated
            else load_cluster_map(self.cluster_path)
        )
        corrections = (
            load_taxonomy_corrections_strict(self.corrections_path)
            if strict_generated
            else load_taxonomy_corrections(self.corrections_path)
        )
        state = (
            load_taxonomy_state_strict(self.cluster_path)
            if strict_generated
            else load_taxonomy_state(self.cluster_path)
        )
        effective = apply_taxonomy_corrections(generated, corrections)
        return TaxonomySnapshot(
            generated=generated,
            corrections=corrections,
            effective=effective,
            state=state,
            revision=_revision(generated, corrections, state),
            generated_sha256=_component(asdict(generated)),
            corrections_sha256=_component(corrections.model_dump(mode="json")),
            state_sha256=_component(state.model_dump(mode="json")),
            effective_sha256=_component(asdict(effective)),
        )

    def read(self) -> TaxonomySnapshot:
        """Read generated data, user intent, and lifecycle state coherently."""

        with self._artifacts():
            return self._read_unlocked(strict_generated=False)

    def read_for_mutation(self) -> TaxonomySnapshot:
        """Read a validated mutation base without accepting corrupt data as empty."""

        with self._artifacts():
            return self._read_unlocked(strict_generated=True)

    def commit(
        self,
        expected: TaxonomySnapshot,
        write: Callable[[TaxonomySnapshot], T],
    ) -> T:
        """Apply one short commit only if every persisted input is unchanged."""

        with self._operation_lock:
            with self._artifacts():
                current = self._read_unlocked(strict_generated=True)
                if current.revision != expected.revision:
                    raise TaxonomyConflictError(
                        "taxonomy changed during classification; "
                        "retry from the latest revision"
                    )
                paths = (
                    self.cluster_path,
                    self.corrections_path,
                    taxonomy_state_path(self.cluster_path),
                )
                with rollback_scope(paths):
                    return write(current)
