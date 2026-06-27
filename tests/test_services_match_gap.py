from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.match_gap import refresh_clusters, slugify_theme
from resume_agent.taxonomy.clusters import ClusterMap, load_cluster_map, save_cluster_map
from resume_agent.tracking.tables import Job, JobStatus


def _engine_with_target_skills(*skills: str):
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(
            Job(
                source="manual",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": list(skills)},
            )
        )
        session.commit()
    return engine


def test_slugify_theme_uses_lowercase_hyphenated_alphanumeric_runs():
    assert slugify_theme("  Cloud / Data & AI  ") == "cloud-data-ai"
    assert slugify_theme("C++ / .NET") == "c-net"
    assert slugify_theme("---") == ""


def test_refresh_clusters_persists_validated_aliases_and_themes(tmp_path):
    engine = _engine_with_target_skills("K8s", "Kubernetes", "Python")
    path = tmp_path / "clusters.json"

    def dedup(tokens: set[str]) -> dict[str, str]:
        assert tokens == {"k8s", "kubernetes", "python"}
        return {
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
            "python": "python",
        }

    def themer(tokens: set[str]) -> list[tuple[str, list[str]]]:
        assert tokens == {"kubernetes", "python"}
        return [
            ("Cloud / Infra", ["kubernetes"]),
            ("Backend", ["python"]),
        ]

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            dedup=dedup,
            themer=themer,
            path=path,
        )

    assert result == {"skills": 2, "themes": 2}
    assert load_cluster_map(path) == ClusterMap(
        aliases={
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
            "python": "python",
        },
        theme_of={"kubernetes": "cloud-infra", "python": "backend"},
        theme_label={"cloud-infra": "Cloud / Infra", "backend": "Backend"},
    )


def test_refresh_clusters_fills_missing_canonicalizer_keys_with_identity(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"

    with get_session(engine) as session:
        refresh_clusters(
            session,
            dedup=lambda tokens: {"python": "python"},
            themer=lambda tokens: [("Languages", ["python", "rust"])],
            path=path,
        )

    assert load_cluster_map(path).aliases == {"python": "python", "rust": "rust"}


def test_refresh_clusters_is_monotonic_and_existing_choices_win(tmp_path):
    engine = _engine_with_target_skills("K8s", "Kubernetes", "Go")
    path = tmp_path / "clusters.json"
    save_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
            theme_of={"kubernetes": "infra"},
            theme_label={"infra": "Infrastructure"},
        ),
        path,
    )

    with get_session(engine) as session:
        refresh_clusters(
            session,
            dedup=lambda tokens: {token: token for token in tokens},
            themer=lambda tokens: [
                ("Platform", ["k8s"]),
                ("Cloud", ["kubernetes"]),
                ("Languages", ["go"]),
            ],
            path=path,
        )

    assert load_cluster_map(path) == ClusterMap(
        aliases={
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
            "go": "go",
        },
        theme_of={"kubernetes": "infra", "go": "languages"},
        theme_label={
            "infra": "Infrastructure",
            "platform": "Platform",
            "cloud": "Cloud",
            "languages": "Languages",
        },
    )


def test_refresh_clusters_rejects_colliding_theme_ids(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")

    with get_session(engine) as session:
        with pytest.raises(ValueError, match="theme id"):
            refresh_clusters(
                session,
                dedup=lambda tokens: {token: token for token in tokens},
                themer=lambda tokens: [
                    ("Cloud & Infra", ["python"]),
                    ("Cloud / Infra", ["rust"]),
                ],
                path=tmp_path / "clusters.json",
            )


@pytest.mark.parametrize(
    "bad_mapping",
    [
        {"python": "invented"},
        {"python": "   "},
        {"python": 42},
        {"invented": "python"},
    ],
)
def test_refresh_clusters_rejects_invalid_canonicalizer_output(
    tmp_path, bad_mapping
):
    engine = _engine_with_target_skills("Python")

    with get_session(engine) as session:
        with pytest.raises(ValueError, match="canonicalizer"):
            refresh_clusters(
                session,
                dedup=lambda tokens: bad_mapping,
                themer=lambda tokens: [("Backend", ["python"])],
                path=tmp_path / "clusters.json",
            )


@pytest.mark.parametrize(
    "bad_themes",
    [
        [("Backend", ["python"])],
        [("Backend", ["python", "python"]), ("Systems", ["rust"])],
        [("Backend", ["python"]), ("Systems", ["python", "rust"])],
        [("Backend", ["python", "invented"])],
        [("   ", ["python", "rust"])],
    ],
)
def test_refresh_clusters_rejects_bad_theming_without_replacing_last_good_file(
    tmp_path, bad_themes
):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"
    existing = ClusterMap(
        aliases={"python": "python"},
        theme_of={"python": "backend"},
        theme_label={"backend": "Backend"},
    )
    save_cluster_map(existing, path)
    last_good = path.read_text(encoding="utf-8")

    with get_session(engine) as session:
        with pytest.raises(ValueError, match="theme"):
            refresh_clusters(
                session,
                dedup=lambda tokens: {token: token for token in tokens},
                themer=lambda tokens: bad_themes,
                path=path,
            )

    assert path.read_text(encoding="utf-8") == last_good
    assert load_cluster_map(path) == existing


def test_refresh_clusters_serializes_concurrent_calls(tmp_path):
    engine = _engine_with_target_skills("Python")
    path = tmp_path / "clusters.json"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_dedup(tokens: set[str]) -> dict[str, str]:
        first_entered.set()
        assert release_first.wait(timeout=2)
        return {"python": "python"}

    def second_dedup(tokens: set[str]) -> dict[str, str]:
        second_entered.set()
        return {"python": "python"}

    def run(dedup):
        with get_session(engine) as session:
            return refresh_clusters(
                session,
                dedup=dedup,
                themer=lambda tokens: [("Backend", ["python"])],
                path=path,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, first_dedup)
        assert first_entered.wait(timeout=2)
        second = pool.submit(run, second_dedup)
        try:
            assert not second_entered.wait(timeout=0.2)
        finally:
            release_first.set()

        assert first.result(timeout=2) == {"skills": 1, "themes": 1}
        assert second.result(timeout=2) == {"skills": 1, "themes": 1}

    assert second_entered.is_set()
    assert load_cluster_map(path).theme_of == {"python": "backend"}
