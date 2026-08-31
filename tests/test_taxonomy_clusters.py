import json
import os

import pytest

from resume_tailor_harness.taxonomy import clusters
from resume_tailor_harness.taxonomy.clusters import (
    ClusterMap,
    allocate_domain_ids,
    load_cluster_map,
    merge_cluster_map,
    prune_cluster_map,
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
                "domain_of": {
                    " Kubernetes ": " infra ",
                    "Rust": "",
                    "bad-value": 7,
                },
                "domain_label": {
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
        domain_of={"kubernetes": "infra"},
        domain_label={"infra": "Cloud / Infra"},
        category_of={"infra": "other"},
    )


def test_load_cluster_map_flattens_alias_chains_and_canonicalizes_themes(tmp_path):
    path = tmp_path / "clusters.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {"a": "b", "b": "c", "c": "c"},
                "domain_of": {"b": "terminal-theme"},
                "domain_label": {"terminal-theme": "Terminal"},
            }
        ),
        encoding="utf-8",
    )

    assert load_cluster_map(path) == ClusterMap(
        aliases={"a": "c", "b": "c", "c": "c"},
        domain_of={"c": "terminal-theme"},
        domain_label={"terminal-theme": "Terminal"},
        category_of={"terminal-theme": "other"},
    )


def test_load_cluster_map_drops_only_cyclic_alias_component(tmp_path):
    path = tmp_path / "clusters.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {"a": "b", "b": "a", "python": "python"},
                "domain_of": {"a": "cycle", "python": "scripting"},
                "domain_label": {"cycle": "Cycle", "scripting": "Scripting"},
                "category_of": {"scripting": "languages"},
            }
        ),
        encoding="utf-8",
    )

    assert load_cluster_map(path) == ClusterMap(
        aliases={"python": "python"},
        domain_of={"python": "scripting"},
        domain_label={"cycle": "Cycle", "scripting": "Scripting"},
        category_of={"cycle": "other", "scripting": "languages"},
    )


def test_load_ignores_legacy_theme_keys_but_keeps_aliases(tmp_path):
    path = tmp_path / "cluster_map.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {"js": "javascript", "javascript": "javascript"},
                "theme_of": {"javascript": "frontend"},
                "theme_label": {"frontend": "Frontend"},
            }
        ),
        encoding="utf-8",
    )

    cmap = load_cluster_map(path)

    assert cmap.aliases == {"js": "javascript", "javascript": "javascript"}
    assert cmap.domain_of == {}
    assert cmap.domain_label == {}
    assert cmap.category_of == {}


def test_load_sanitizes_categories_and_backfills_known_domains(tmp_path):
    path = tmp_path / "cluster_map.json"
    path.write_text(
        json.dumps(
            {
                "aliases": {"python": "python"},
                "domain_of": {"python": "scripting"},
                "domain_label": {"scripting": "Scripting", "orphan": "Orphan"},
                "category_of": {"scripting": "not-a-real-slug"},
            }
        ),
        encoding="utf-8",
    )

    assert load_cluster_map(path).category_of == {
        "scripting": "other",
        "orphan": "other",
    }


def test_load_cluster_map_flattens_deep_alias_chain_without_recursion(tmp_path):
    path = tmp_path / "clusters.json"
    aliases = {f"skill{index}": f"skill{index + 1}" for index in range(1500)}
    path.write_text(json.dumps({"aliases": aliases}), encoding="utf-8")

    loaded = load_cluster_map(path)

    assert len(loaded.aliases) == 1500
    assert loaded.aliases["skill0"] == "skill1500"
    assert loaded.aliases["skill1499"] == "skill1500"


def test_save_cluster_map_roundtrips_deterministically_without_fixed_temp(tmp_path):
    path = tmp_path / "clusters.json"
    fixed_temp = tmp_path / "clusters.json.tmp"
    fixed_temp.write_text("leave me alone", encoding="utf-8")
    cmap = ClusterMap(
        aliases={"z": "zeta", "a": "alpha"},
        domain_of={"zeta": "t2", "alpha": "t1"},
        domain_label={"t2": "Zeta", "t1": "Alpha"},
        category_of={"t2": "other", "t1": "languages"},
    )

    save_cluster_map(cmap, path)
    first = path.read_text(encoding="utf-8")
    save_cluster_map(cmap, path)

    assert load_cluster_map(path) == cmap
    assert path.read_text(encoding="utf-8") == first
    assert (
        first
        == json.dumps(
            {
                "aliases": cmap.aliases,
                "domain_of": cmap.domain_of,
                "domain_label": cmap.domain_label,
                "category_of": cmap.category_of,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    assert fixed_temp.read_text(encoding="utf-8") == "leave me alone"


def test_save_cluster_map_atomically_replaces_and_cleans_failed_temp(
    tmp_path, monkeypatch
):
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
        domain_of={"kubernetes": "infra"},
        domain_label={"infra": "Infrastructure"},
        category_of={"infra": "cloud-infra"},
    )
    new = ClusterMap(
        aliases={"k8s": "k8s", "kube": "k8s"},
        domain_of={"kubernetes": "platform", "react": "frontend"},
        domain_label={"infra": "Renamed", "frontend": "Frontend"},
        category_of={"infra": "tools-platforms", "frontend": "frontend-web"},
    )

    assert merge_cluster_map(existing, new) == ClusterMap(
        aliases={
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
            "kube": "kubernetes",
        },
        domain_of={"kubernetes": "infra", "react": "frontend"},
        domain_label={"infra": "Infrastructure", "frontend": "Frontend"},
        category_of={"infra": "cloud-infra", "frontend": "frontend-web"},
    )


def test_merge_cluster_map_protects_existing_terminal_from_redirection():
    merged = merge_cluster_map(
        ClusterMap(aliases={"a": "b"}),
        ClusterMap(aliases={"b": "c"}),
    )

    assert merged.aliases == {"a": "b", "b": "b"}


def test_merge_cluster_map_rejects_cycle_before_last_good_file_is_replaced(tmp_path):
    path = tmp_path / "clusters.json"
    existing = ClusterMap(aliases={"a": "b"})
    save_cluster_map(existing, path)
    last_good = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="alias cycle"):
        merged = merge_cluster_map(
            existing,
            ClusterMap(aliases={"c": "d", "d": "c"}),
        )
        save_cluster_map(merged, path)

    assert path.read_text(encoding="utf-8") == last_good
    assert load_cluster_map(path) == existing


def test_prune_keeps_terminal_required_by_a_demanded_alias():
    pruned = prune_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes", "cobol": "cobol"},
            domain_of={"kubernetes": "cloud", "cobol": "legacy"},
            domain_label={"cloud": "Cloud", "legacy": "Legacy"},
            category_of={"cloud": "cloud-infra", "legacy": "other"},
        ),
        {"k8s"},
    )

    assert pruned == ClusterMap(
        aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
        domain_of={"kubernetes": "cloud"},
        domain_label={"cloud": "Cloud"},
        category_of={"cloud": "cloud-infra"},
    )


def test_allocate_domain_ids_is_collision_safe_and_order_independent():
    forward = allocate_domain_ids(
        existing_labels={"c": "C"}, proposed_labels=["C++", "C#"]
    )
    reverse = allocate_domain_ids(
        existing_labels={"c": "C"}, proposed_labels=["C#", "C++"]
    )

    assert forward == reverse
    assert set(forward.values()) == {"c-2", "c-3"}


def test_allocate_domain_ids_reuses_equal_normalized_labels():
    allocated = allocate_domain_ids(
        existing_labels={}, proposed_labels=["Cloud / Infra", " cloud-infra "]
    )

    assert allocated == {"cloud infra": "cloud-infra"}


def test_allocate_domain_ids_rejects_empty_slug():
    with pytest.raises(ValueError, match="domain label"):
        allocate_domain_ids(existing_labels={}, proposed_labels=["---"])
