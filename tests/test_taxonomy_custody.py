from __future__ import annotations

import threading
import time

from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)
from resume_agent.taxonomy.custody import TaxonomyCustody


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
