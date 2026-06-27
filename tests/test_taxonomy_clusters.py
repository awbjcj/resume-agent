import json
import os

import pytest

from resume_agent.taxonomy import clusters
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    merge_cluster_map,
    save_cluster_map,
)


def test_load_cluster_map_missing_unreadable_invalid_or_nonobject_is_empty(tmp_path):
    missing = tmp_path / "missing.json"
    assert load_cluster_map(missing) == ClusterMap.empty()

    unreadable = tmp_path / "directory"
    unreadable.mkdir()
    assert load_cluster_map(unreadable) == ClusterMap.empty()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    assert load_cluster_map(invalid) == ClusterMap.empty()

    nonobject = tmp_path / "nonobject.json"
    nonobject.write_text("[]", encoding="utf-8")
    assert load_cluster_map(nonobject) == ClusterMap.empty()


def test_load_cluster_map_validates_trims_and_normalizes_maps(tmp_path):
    path = tmp_path / "clusters.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {
                    " K8S ": " Kubernetes ",
                    "Node JS!": " Node.js ",
                    "": "python",
                    "bad-value": 3,
                },
                "theme_of": {
                    " Kubernetes ": " infra ",
                    "Rust": "",
                    "bad-value": 7,
                },
                "theme_label": {
                    " infra ": " Cloud / Infra ",
                    "": "Missing id",
                    "bad-value": None,
                },
            }
        ),
        encoding="utf-8",
    )

    assert load_cluster_map(path) == ClusterMap(
        aliases={"k8s": "kubernetes", "node js": "node.js"},
        theme_of={"kubernetes": "infra"},
        theme_label={"infra": "Cloud / Infra"},
    )


def test_save_cluster_map_roundtrips_deterministically_without_fixed_temp(tmp_path):
    path = tmp_path / "clusters.json"
    fixed_temp = tmp_path / "clusters.json.tmp"
    fixed_temp.write_text("leave me alone", encoding="utf-8")
    cmap = ClusterMap(
        aliases={"z": "zeta", "a": "alpha"},
        theme_of={"zeta": "t2", "alpha": "t1"},
        theme_label={"t2": "Zeta", "t1": "Alpha"},
    )

    save_cluster_map(cmap, path)
    first = path.read_text(encoding="utf-8")
    save_cluster_map(cmap, path)

    assert load_cluster_map(path) == cmap
    assert path.read_text(encoding="utf-8") == first
    assert first == json.dumps(
        {
            "aliases": cmap.aliases,
            "theme_of": cmap.theme_of,
            "theme_label": cmap.theme_label,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    assert fixed_temp.read_text(encoding="utf-8") == "leave me alone"


def test_save_cluster_map_atomically_replaces_and_cleans_failed_temp(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "clusters.json"
    cmap = ClusterMap(aliases={"k8s": "kubernetes"})
    real_replace = os.replace
    replaced: list[tuple[object, object]] = []

    def tracking_replace(source, destination):
        replaced.append((source, destination))
        assert source.exists()
        assert source.parent == path.parent
        real_replace(source, destination)

    monkeypatch.setattr(clusters.os, "replace", tracking_replace)
    save_cluster_map(cmap, path)

    assert len(replaced) == 1
    assert replaced[0][1] == path

    before = set(path.parent.iterdir())

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(clusters.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_cluster_map(cmap, path)
    assert set(path.parent.iterdir()) == before


def test_merge_cluster_map_is_monotonic_with_existing_values_winning():
    existing = ClusterMap(
        aliases={"k8s": "kubernetes"},
        theme_of={"kubernetes": "infra"},
        theme_label={"infra": "Infrastructure"},
    )
    new = ClusterMap(
        aliases={"k8s": "k8s", "kube": "kubernetes"},
        theme_of={"kubernetes": "platform", "react": "frontend"},
        theme_label={"infra": "Renamed", "frontend": "Frontend"},
    )

    assert merge_cluster_map(existing, new) == ClusterMap(
        aliases={"k8s": "kubernetes", "kube": "kubernetes"},
        theme_of={"kubernetes": "infra", "react": "frontend"},
        theme_label={"infra": "Infrastructure", "frontend": "Frontend"},
    )
