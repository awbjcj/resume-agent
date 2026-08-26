"""Workspace-scoped custody for the persisted Cluster map artifact set."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import weakref
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, TypeVar

from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    load_cluster_map_strict,
)
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
    load_taxonomy_corrections,
)
from resume_agent.taxonomy.state import (
    TaxonomyState,
    load_taxonomy_state,
    taxonomy_state_path,
)


_LOCKS_GUARD = threading.Lock()
_WORKSPACE_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
    weakref.WeakValueDictionary()
)
_ARTIFACT_LOCKS: weakref.WeakValueDictionary[Path, threading.RLock] = (
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


def _restore_file(path: Path, payload: bytes | None) -> None:
    """Restore one artifact atomically after a failed multi-file commit."""

    if payload is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".rollback",
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Admit one long-running taxonomy mutation without blocking readers."""

        with self._operation_lock:
            yield

    @contextmanager
    def mutation(self) -> Iterator[None]:
        """Serialize a complete mutation of this Workspace's artifact set."""

        with self._operation_lock, self._artifact_lock:
            yield

    def _read_unlocked(self, *, strict_generated: bool) -> TaxonomySnapshot:
        generated = (
            load_cluster_map_strict(self.cluster_path)
            if strict_generated
            else load_cluster_map(self.cluster_path)
        )
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

    def read(self) -> TaxonomySnapshot:
        """Read generated data, user intent, and lifecycle state coherently."""

        with self._artifact_lock:
            return self._read_unlocked(strict_generated=False)

    def read_for_mutation(self) -> TaxonomySnapshot:
        """Read a validated mutation base without accepting corrupt data as empty."""

        with self._artifact_lock:
            return self._read_unlocked(strict_generated=True)

    def commit(
        self,
        expected: TaxonomySnapshot,
        write: Callable[[TaxonomySnapshot], T],
    ) -> T:
        """Apply one short commit only if every persisted input is unchanged."""

        with self.mutation():
            current = self._read_unlocked(strict_generated=True)
            if current.revision != expected.revision:
                raise TaxonomyConflictError(
                    "taxonomy changed during classification; retry from the latest revision"
                )
            paths = (
                self.cluster_path,
                self.corrections_path,
                taxonomy_state_path(self.cluster_path),
            )
            before = {
                path: path.read_bytes() if path.exists() else None for path in paths
            }
            try:
                return write(current)
            except BaseException:
                for path, payload in before.items():
                    _restore_file(path, payload)
                raise
