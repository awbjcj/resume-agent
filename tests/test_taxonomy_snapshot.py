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
        overrides=Overrides(
            category={"rust": "hard"}, group={"rust": "languages"}
        ),
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
