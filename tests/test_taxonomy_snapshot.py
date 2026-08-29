from __future__ import annotations

import pytest

from resume_agent.profile.matrix import Overrides
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
from resume_agent.taxonomy.state import RetiredSkill, TaxonomyState


def test_correction_alias_reaches_the_effective_map():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"javascript": "web"}),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
    )

    assert snap.cluster_map.aliases["js"] == "javascript"


def test_override_alias_beats_a_correction_alias():
    """Spec precedence: generated -> corrections -> overrides."""
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )

    assert snap.cluster_map.aliases["js"] == "typescript"


def test_forbid_alias_is_terminal_and_cannot_be_re_merged():
    """A correction must not re-merge a pair the profile forbade."""
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"js": "javascript"}),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(forbid_alias=[["js", "javascript"]]),
    )

    assert snap.cluster_map.aliases.get("js") != "javascript"


def test_ban_and_retirement_are_exposed_as_semantic_sets():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        overrides=Overrides(ban=["cobol"]),
        state=TaxonomyState(retired_skills={"8 years of ml": RetiredSkill()}),
    )

    assert snap.banned_keys == frozenset({"cobol"})
    assert snap.retired_keys == frozenset({"8 years of ml"})


def test_category_and_group_are_projections_not_identity():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        overrides=Overrides(category={"rust": "hard"}, group={"rust": "languages"}),
    )

    assert snap.category_overrides == {"rust": "hard"}
    assert snap.group_overrides == {"rust": "languages"}


def test_is_populated_replaces_the_use_cluster_map_heuristic():
    assert not EffectiveTaxonomy.from_parts(ClusterMap()).is_populated
    assert EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"py": "python"})
    ).is_populated


def test_alias_cycle_raises_rather_than_picking_a_winner():
    with pytest.raises(ValueError):
        EffectiveTaxonomy.from_parts(ClusterMap(aliases={"a": "b", "b": "a"}))


def test_semantic_revision_ignores_grouping_timestamps_and_history():
    """Regroup metadata must not invalidate every derived artifact."""
    from resume_agent.taxonomy.state import GroupingStatus, TaxonomyGeneration

    base = ClusterMap(domain_of={"python": "backend"})
    quiet = EffectiveTaxonomy.from_parts(base, state=TaxonomyState())
    noisy = EffectiveTaxonomy.from_parts(
        base,
        state=TaxonomyState(
            maintenance_due=True,
            grouping_status={"rust": GroupingStatus(reason="uncertain")},
            history=[
                TaxonomyGeneration(
                    id="g1", created_at="2030-01-01", snapshot="snapshot.json"
                )
            ],
        ),
    )

    assert quiet.semantic_revision == noisy.semantic_revision


def test_retirement_reason_is_manifest_only_but_the_key_is_semantic():
    first = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        state=TaxonomyState(retired_skills={"x": RetiredSkill(reason="a")}),
    )
    reworded = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        state=TaxonomyState(retired_skills={"x": RetiredSkill(reason="b")}),
    )
    added = EffectiveTaxonomy.from_parts(
        ClusterMap(), state=TaxonomyState(retired_skills={"y": RetiredSkill()})
    )

    assert first.semantic_revision == reworded.semantic_revision
    assert first.semantic_revision != added.semantic_revision


def test_ban_is_semantic_because_it_deletes_rows():
    plain = EffectiveTaxonomy.from_parts(ClusterMap(domain_of={"cobol": "legacy"}))
    banned = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"cobol": "legacy"}),
        overrides=Overrides(ban=["cobol"]),
    )

    assert plain.semantic_revision != banned.semantic_revision


def test_category_and_group_move_projection_not_semantic():
    plain = EffectiveTaxonomy.from_parts(ClusterMap(domain_of={"rust": "systems"}))
    styled = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"rust": "systems"}),
        overrides=Overrides(category={"rust": "hard"}, group={"rust": "languages"}),
    )

    assert plain.semantic_revision == styled.semantic_revision
    assert plain.projection_revision != styled.projection_revision


def test_equivalent_inputs_in_different_order_hash_identically():
    first = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"py": "python", "js": "javascript"})
    )
    second = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"js": "javascript", "py": "python"})
    )

    assert first.semantic_revision == second.semantic_revision


def test_two_ledgers_resolving_to_the_same_taxonomy_hash_identically():
    """Hashing the effective projection avoids idempotent artifact churn."""
    direct = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"js": "javascript"}))
    via_correction = EffectiveTaxonomy.from_parts(
        ClusterMap(), corrections=TaxonomyCorrections(aliases={"js": "javascript"})
    )

    assert direct.semantic_revision == via_correction.semantic_revision


def test_revisions_are_sha256_hex_and_echoed_into_the_manifest():
    snap = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))

    assert len(snap.semantic_revision) == 64
    assert len(snap.projection_revision) == 64
    assert snap.manifest.semantic == snap.semantic_revision


def test_disagreeing_override_and_correction_records_a_conflict():
    from resume_agent.taxonomy.snapshot import OverrideConflict

    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )

    assert snap.conflicts == (
        OverrideConflict(
            token="js",
            correction_head="javascript",
            override_head="typescript",
            resolution="override",
        ),
    )


def test_agreeing_override_and_correction_is_not_a_conflict():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "javascript"}),
    )

    assert snap.conflicts == ()


def test_forbid_alias_defeating_a_correction_is_recorded_as_such():
    from resume_agent.taxonomy.snapshot import OverrideConflict

    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(forbid_alias=[["js", "javascript"]]),
    )

    assert snap.conflicts == (
        OverrideConflict(
            token="js",
            correction_head="javascript",
            override_head="",
            resolution="forbid_alias",
        ),
    )


def test_conflicts_do_not_participate_in_the_semantic_revision():
    """A conflict diagnoses the derivation; the projection already has the result."""
    conflicted = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )
    clean = EffectiveTaxonomy.from_parts(
        ClusterMap(), overrides=Overrides(alias={"js": "typescript"})
    )

    assert conflicted.semantic_revision == clean.semantic_revision
    assert conflicted.conflicts and not clean.conflicts


def test_snapshot_preserves_corrections_for_read_consumers():
    corrections = TaxonomyCorrections(
        aliases={"js": "javascript"},
        added_skills=["javascript"],
        removed_skills=["legacy js"],
    )

    snap = EffectiveTaxonomy.from_parts(ClusterMap(), corrections=corrections)

    assert snap.corrections == corrections
