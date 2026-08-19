from __future__ import annotations

import pytest

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


def test_modes_keep_the_legacy_projection_stable(tmp_path):
    profile_dir, corrections_path = _write(
        tmp_path,
        aliases={"py": "python"},
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
    )

    legacy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="legacy"
    )
    shadow = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="shadow"
    )
    uccm = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="uccm"
    )

    assert legacy.cluster_map == shadow.cluster_map == uccm.cluster_map
    assert legacy.capability_snapshot is None
    assert shadow.capability_snapshot is not None
    assert uccm.capability_snapshot is not None
    assert legacy.manifest.capability_status == "disabled"
    assert shadow.manifest.capability_status == "shadow"
    assert uccm.manifest.capability_status == "fallback"
    assert uccm.manifest.capability_error_code == "activation_report_missing"


def test_uccm_mode_becomes_active_only_after_the_release_policy_approves(
    monkeypatch, tmp_path
):
    from resume_agent.matching.activation import UccmActivationDecision
    from resume_agent.profile import effective as effective_module

    profile_dir, corrections_path = _write(tmp_path, aliases={"py": "python"})
    monkeypatch.setattr(effective_module, "load_activation_report", lambda path: object())

    def approve(requested_mode, report, **expected):
        return UccmActivationDecision(
            requested_mode=requested_mode,
            effective_mode="uccm",
            eligible=True,
            reason_code="activation_eligible",
            report_revision="release-report-v1",
            **expected,
        )

    monkeypatch.setattr(effective_module, "decide_uccm_activation", approve)
    taxonomy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="uccm"
    )

    assert taxonomy.manifest.capability_status == "active"
    assert taxonomy.manifest.capability_error_code is None
    assert taxonomy.manifest.capability_activation_report_revision == "release-report-v1"


def test_uccm_validation_failure_falls_back_without_changing_the_map(
    monkeypatch, tmp_path
):
    from resume_agent.profile import effective as effective_module
    from resume_agent.taxonomy.graph_validation import GraphValidationError

    profile_dir, corrections_path = _write(tmp_path, aliases={"py": "python"})
    legacy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="legacy"
    )

    def reject(*args, **kwargs):
        raise GraphValidationError.single("invalid_graph", "test rejection")

    monkeypatch.setattr(effective_module, "build_capability_snapshot", reject)
    fallback = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="uccm"
    )

    assert fallback.cluster_map == legacy.cluster_map
    assert fallback.semantic_revision == legacy.semantic_revision
    assert fallback.capability_snapshot is None
    assert fallback.manifest.capability_status == "fallback"
    assert fallback.manifest.capability_error_code == "invalid_graph"


def test_legacy_mode_skips_graph_construction(monkeypatch, tmp_path):
    from resume_agent.profile import effective as effective_module

    profile_dir, corrections_path = _write(tmp_path, aliases={"py": "python"})

    def reject(*args, **kwargs):
        raise AssertionError("legacy mode must not build the capability graph")

    monkeypatch.setattr(effective_module, "build_capability_snapshot", reject)
    taxonomy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="legacy"
    )

    assert taxonomy.capability_snapshot is None
    assert taxonomy.manifest.capability is not None
    assert taxonomy.manifest.capability.internal_graph_version == ""


def test_uccm_mode_does_not_hide_programming_errors(monkeypatch, tmp_path):
    from resume_agent.profile import effective as effective_module

    profile_dir, corrections_path = _write(tmp_path, aliases={"py": "python"})

    def reject(*args, **kwargs):
        raise RuntimeError("unexpected defect")

    monkeypatch.setattr(effective_module, "build_capability_snapshot", reject)
    with pytest.raises(RuntimeError, match="unexpected defect"):
        build_effective_taxonomy(
            profile_dir, corrections_path=corrections_path, mode="uccm"
        )
