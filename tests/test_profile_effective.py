from __future__ import annotations

from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _write(tmp_path, *, aliases=None, corrections=None, overrides_yaml=None):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    save_cluster_map(
        ClusterMap(aliases=aliases or {}, domain_of={"python": "backend"}),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(corrections or TaxonomyCorrections(), corrections_path)
    if overrides_yaml is not None:
        (profile_dir / "overrides.yaml").write_text(overrides_yaml, encoding="utf-8")
    return profile_dir, corrections_path


def test_reads_all_four_artifacts_into_one_snapshot(tmp_path):
    profile_dir, corrections_path = _write(
        tmp_path,
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides_yaml="ban:\n  - cobol\n",
    )

    snap = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    assert snap.cluster_map.aliases["js"] == "javascript"
    assert snap.banned_keys == frozenset({"cobol"})
    assert snap.is_populated


def test_missing_artifacts_degrade_to_an_empty_snapshot(tmp_path):
    empty = tmp_path / "profile"
    empty.mkdir()

    snap = build_effective_taxonomy(empty, corrections_path=tmp_path / "nope.json")

    assert not snap.is_populated
    assert len(snap.semantic_revision) == 64


def test_manifest_records_every_component_hash(tmp_path):
    profile_dir, corrections_path = _write(tmp_path, overrides_yaml="ban:\n  - cobol\n")

    snap = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    for component in (
        snap.manifest.generated,
        snap.manifest.corrections,
        snap.manifest.state,
        snap.manifest.overrides,
    ):
        assert len(component) == 64


def test_repeated_builds_are_deterministic(tmp_path):
    profile_dir, corrections_path = _write(tmp_path)

    first = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    second = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    assert first.semantic_revision == second.semantic_revision
    assert first.manifest == second.manifest
