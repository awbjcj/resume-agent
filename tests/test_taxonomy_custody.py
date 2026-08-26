from __future__ import annotations

import threading
import time

import pytest

from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)
from resume_agent.taxonomy.custody import TaxonomyCustody
from resume_agent.taxonomy.custody import TaxonomyConflictError
from resume_agent.taxonomy.state import taxonomy_state_path


def test_read_returns_one_correction_applied_snapshot(tmp_path):
    cluster_path = tmp_path / "one" / "cluster_map.json"
    corrections_path = tmp_path / "one" / "taxonomy_corrections.json"
    save_cluster_map(
        ClusterMap(
            aliases={"py": "python"},
            domain_of={"python": "languages"},
            domain_label={"languages": "Languages"},
            category_of={"languages": "languages"},
        ),
        cluster_path,
    )
    save_taxonomy_corrections(
        TaxonomyCorrections(skill_domain={"python": "backend"}),
        corrections_path,
    )

    snapshot = TaxonomyCustody(cluster_path, corrections_path).read()

    assert snapshot.generated.domain_of["python"] == "languages"
    # Unknown correction targets are safely ignored by the existing replay rule.
    assert snapshot.effective.domain_of["python"] == "languages"
    assert snapshot.corrections.skill_domain == {"python": "backend"}
    assert len(snapshot.revision) == 64
    assert len(snapshot.generated_sha256) == 64
    assert len(snapshot.corrections_sha256) == 64
    assert len(snapshot.state_sha256) == 64

    save_taxonomy_corrections(
        TaxonomyCorrections(skill_domain={"python": "languages"}),
        corrections_path,
    )
    assert TaxonomyCustody(cluster_path, corrections_path).read().revision != snapshot.revision


def test_same_workspace_mutations_serialize(tmp_path):
    custody = TaxonomyCustody(
        tmp_path / "one" / "cluster_map.json",
        tmp_path / "one" / "taxonomy_corrections.json",
    )
    entered = threading.Event()
    released = threading.Event()

    def first() -> None:
        with custody.mutation():
            entered.set()
            released.wait(timeout=2)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=1)

    acquired = threading.Event()

    def second() -> None:
        with custody.mutation():
            acquired.set()

    follower = threading.Thread(target=second)
    follower.start()
    time.sleep(0.05)
    assert not acquired.is_set()
    released.set()
    thread.join(timeout=1)
    follower.join(timeout=1)
    assert acquired.is_set()


def test_different_workspaces_do_not_serialize(tmp_path):
    first = TaxonomyCustody(
        tmp_path / "one" / "cluster_map.json",
        tmp_path / "one" / "taxonomy_corrections.json",
    )
    second = TaxonomyCustody(
        tmp_path / "two" / "cluster_map.json",
        tmp_path / "two" / "taxonomy_corrections.json",
    )

    with first.mutation():
        acquired = threading.Event()

        def enter_second() -> None:
            with second.mutation():
                acquired.set()

        thread = threading.Thread(target=enter_second)
        thread.start()
        assert acquired.wait(timeout=0.5)
        thread.join(timeout=1)


def test_long_operation_does_not_block_coherent_reads(tmp_path):
    custody = TaxonomyCustody(
        tmp_path / "one" / "cluster_map.json",
        tmp_path / "one" / "taxonomy_corrections.json",
    )
    save_cluster_map(ClusterMap(aliases={"python": "python"}), custody.cluster_path)

    with custody.operation():
        completed = threading.Event()

        def read() -> None:
            custody.read()
            completed.set()

        thread = threading.Thread(target=read)
        thread.start()
        assert completed.wait(timeout=0.5)
        thread.join(timeout=1)


def test_mutation_snapshot_rejects_a_corrupt_existing_cluster_map(tmp_path):
    cluster_path = tmp_path / "one" / "cluster_map.json"
    cluster_path.parent.mkdir(parents=True)
    cluster_path.write_text("{not-json", encoding="utf-8")
    custody = TaxonomyCustody(
        cluster_path,
        tmp_path / "one" / "taxonomy_corrections.json",
    )

    with pytest.raises(ValueError, match="cluster map"):
        custody.read_for_mutation()
    assert custody.read().generated == ClusterMap.empty()


@pytest.mark.parametrize("sidecar", ["corrections", "state"])
def test_mutation_snapshot_rejects_corrupt_sidecars(tmp_path, sidecar):
    cluster_path = tmp_path / "one" / "cluster_map.json"
    corrections_path = tmp_path / "one" / "taxonomy_corrections.json"
    save_cluster_map(ClusterMap(aliases={"python": "python"}), cluster_path)
    target = (
        corrections_path
        if sidecar == "corrections"
        else taxonomy_state_path(cluster_path)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not-json", encoding="utf-8")
    custody = TaxonomyCustody(cluster_path, corrections_path)

    with pytest.raises(ValueError, match="taxonomy (corrections|state)"):
        custody.read_for_mutation()
    with pytest.raises(ValueError, match="taxonomy (corrections|state)"):
        with custody.mutation():
            raise AssertionError("corrupt artifact entered mutation body")


def test_revision_checked_commit_refuses_stale_generated_data(tmp_path):
    cluster_path = tmp_path / "one" / "cluster_map.json"
    custody = TaxonomyCustody(
        cluster_path,
        tmp_path / "one" / "taxonomy_corrections.json",
    )
    save_cluster_map(ClusterMap(aliases={"python": "python"}), cluster_path)
    snapshot = custody.read_for_mutation()
    save_cluster_map(ClusterMap(aliases={"rust": "rust"}), cluster_path)

    called = False

    def write(_current):
        nonlocal called
        called = True

    with pytest.raises(TaxonomyConflictError, match="changed during classification"):
        custody.commit(snapshot, write)
    assert called is False


def test_commit_rolls_back_artifacts_when_a_writer_fails(tmp_path):
    cluster_path = tmp_path / "one" / "cluster_map.json"
    custody = TaxonomyCustody(
        cluster_path,
        tmp_path / "one" / "taxonomy_corrections.json",
    )
    original = ClusterMap(aliases={"python": "python"})
    save_cluster_map(original, cluster_path)
    snapshot = custody.read_for_mutation()

    def write(_current):
        save_cluster_map(ClusterMap(aliases={"rust": "rust"}), cluster_path)
        raise RuntimeError("state write failed")

    with pytest.raises(RuntimeError, match="state write failed"):
        custody.commit(snapshot, write)

    assert custody.read_for_mutation().generated == original
