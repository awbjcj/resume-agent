from types import SimpleNamespace
from typing import cast

from resume_tailor_harness.services.match_gap import (
    maintain_taxonomy,
    undo_taxonomy_maintenance,
)
from resume_tailor_harness.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    save_cluster_map,
)
from resume_tailor_harness.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)
from resume_tailor_harness.taxonomy.embeddings import EmbeddingUnavailable
from resume_tailor_harness.taxonomy.state import load_taxonomy_state, snapshot_before_maintenance
from resume_tailor_harness.tracking.canonicalize import (
    TaxonomyMaintenanceAction,
    TaxonomyMaintenancePlan,
)


class _Judge:
    def __init__(self, *actions: TaxonomyMaintenanceAction) -> None:
        self.actions = list(actions)
        self.calls = 0

    async def arun(self, prompt):
        self.calls += 1
        return SimpleNamespace(content=TaxonomyMaintenancePlan(actions=self.actions))

    def run(self, prompt):
        raise AssertionError("async path expected")


class _OfflineEmbeddings:
    model_id = "openai:text-embedding-3-small"

    async def embed(self, texts):
        raise EmbeddingUnavailable("offline fixture")


def _two_domain_map() -> ClusterMap:
    target_members = (
        "flask",
        "django",
        "starlette",
        "sanic",
        "tornado",
        "bottle",
        "falcon",
        "pyramid",
    )
    return ClusterMap(
        aliases={
            "python": "python",
            "fastapi": "fastapi",
            **{token: token for token in target_members},
        },
        domain_of={
            "python": "backend-a",
            "fastapi": "backend-a",
            **{token: "backend-b" for token in target_members},
        },
        domain_label={"backend-a": "Backend APIs", "backend-b": "Backend API"},
        category_of={"backend-a": "backend-apis", "backend-b": "backend-apis"},
    )


def test_maintenance_merge_creates_a_generation_and_undo_restores_it(tmp_path):
    path = tmp_path / "cluster_map.json"
    before = _two_domain_map()
    save_cluster_map(before, path)
    judge = _Judge(
        TaxonomyMaintenanceAction(
            kind="merge",
            domain_id="backend-a",
            target_domain_id="backend-b",
            confidence="high",
        )
    )

    result = maintain_taxonomy(
        None,
        judge=judge,
        path=path,
        embedding_provider=_OfflineEmbeddings(),
    )

    assert result["changed"] is True
    assert result["undoAvailable"] is True
    assert set(load_cluster_map(path).domain_of.values()) == {"backend-b"}
    assert load_taxonomy_state(path).history

    restored = undo_taxonomy_maintenance(None, path=path)

    assert restored["restored"] is True
    assert load_cluster_map(path) == before


def test_maintenance_keeps_user_pinned_domains_and_aliases_unchanged(tmp_path):
    path = tmp_path / "cluster_map.json"
    corrections_path = tmp_path / "taxonomy_corrections.json"
    save_cluster_map(_two_domain_map(), path)
    save_taxonomy_corrections(
        TaxonomyCorrections(
            domain_renames={"backend-a": "Pinned Backend"},
            aliases={"py": "python"},
        ),
        corrections_path,
    )

    result = maintain_taxonomy(
        None,
        judge=_Judge(
            TaxonomyMaintenanceAction(
                kind="merge",
                domain_id="backend-a",
                target_domain_id="backend-b",
                confidence="high",
            )
        ),
        path=path,
        corrections_path=corrections_path,
        embedding_provider=_OfflineEmbeddings(),
    )

    after = load_cluster_map(path)
    assert result["changed"] is False
    assert after.domain_of["python"] == "backend-a"
    assert any(
        "pinned" in reason for reason in cast(list[str], result["rejectedActions"])
    )


def test_maintenance_can_rename_reparent_and_split_model_owned_domains(tmp_path):
    path = tmp_path / "cluster_map.json"
    members = (
        "postgres",
        "mysql",
        "redis",
        "mongodb",
        "sqlite",
        "elasticsearch",
        "clickhouse",
        "snowflake",
        "kafka",
        "rabbitmq",
    )
    save_cluster_map(
        ClusterMap(
            aliases={token: token for token in members},
            domain_of={token: "backend" for token in members},
            domain_label={"backend": "Backend"},
            category_of={"backend": "backend-apis"},
        ),
        path,
    )
    judge = _Judge(
        TaxonomyMaintenanceAction(
            kind="rename",
            domain_id="backend",
            label="Data and Messaging",
            confidence="high",
        ),
        TaxonomyMaintenanceAction(
            kind="reparent",
            domain_id="backend",
            category="data-analytics",
            confidence="high",
        ),
        TaxonomyMaintenanceAction(
            kind="split",
            domain_id="backend",
            clusters=[
                [
                    "postgres",
                    "mysql",
                    "redis",
                    "mongodb",
                    "sqlite",
                    "elasticsearch",
                    "clickhouse",
                    "snowflake",
                ],
                ["kafka", "rabbitmq"],
            ],
            labels=["Databases", "Messaging"],
            categories=["databases-storage", "backend-apis"],
            confidence="high",
        ),
    )

    result = maintain_taxonomy(
        None, judge=judge, path=path, embedding_provider=_OfflineEmbeddings()
    )

    after = load_cluster_map(path)
    assert result["changed"] is True
    assert len(set(after.domain_of.values())) == 2
    assert after.domain_of["postgres"] == after.domain_of["mysql"]
    assert after.domain_of["kafka"] == after.domain_of["rabbitmq"]
    assert after.domain_of["postgres"] != after.domain_of["kafka"]
    assert set(after.category_of.values()) == {"databases-storage", "backend-apis"}


def test_maintenance_rejects_churn_above_twenty_percent(tmp_path):
    path = tmp_path / "cluster_map.json"
    aliases = {f"skill-{index}": f"skill-{index}" for index in range(10)}
    save_cluster_map(
        ClusterMap(
            aliases=aliases,
            domain_of={
                **{f"skill-{index}": "left" for index in range(5)},
                **{f"skill-{index}": "right" for index in range(5, 10)},
            },
            domain_label={"left": "Backend", "right": "Backend APIs"},
            category_of={"left": "backend-apis", "right": "backend-apis"},
        ),
        path,
    )

    result = maintain_taxonomy(
        None,
        judge=_Judge(
            TaxonomyMaintenanceAction(
                kind="merge",
                domain_id="left",
                target_domain_id="right",
                confidence="high",
            )
        ),
        path=path,
        embedding_provider=_OfflineEmbeddings(),
    )

    assert result["changed"] is False
    assert any(
        "maintenance churn exceeds" in reason
        for reason in cast(list[str], result["rejectedActions"])
    )


def test_maintenance_history_retains_only_ten_snapshots(tmp_path):
    path = tmp_path / "cluster_map.json"
    cmap = _two_domain_map()
    save_cluster_map(cmap, path)

    for _ in range(11):
        snapshot_before_maintenance(path, cmap)

    state = load_taxonomy_state(path)
    assert len(state.history) == 10
    assert len(list((tmp_path / "taxonomy" / "generations").glob("*.json"))) == 10
