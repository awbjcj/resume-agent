"""One fixture, two paths, one answer.

The Phase 0 defect: ``build_match_gap_payload`` applies taxonomy corrections
while ``_regenerate_bound_matrix`` does not. Coverage is a join across demand
graph keys and matrix row keys, so an alias correction can move one side of the
join and not the other.
"""

from __future__ import annotations

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _seed(tmp_path):
    """Facts naming ``js``; a correction aliases it to ``javascript``."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    save_cluster_map(
        ClusterMap(
            domain_of={"javascript": "web"},
            domain_label={"web": "Web"},
            category_of={"web": "languages"},
        ),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}), corrections_path
    )
    facts = ProfileFacts(
        contact=Contact(name="A"), skills={"hard": [Skill(name="js")]}
    )
    return profile_dir, corrections_path, facts


def test_matrix_and_match_gap_agree_on_one_correction(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.profile.matrix import build_matrix

    profile_dir, corrections_path, facts = _seed(tmp_path)
    taxonomy = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    matrix = build_matrix(facts, taxonomy)

    # The correction must reach the matrix row key, not only the demand graph.
    assert [row.key for row in matrix.rows] == ["javascript"]
    # Both artifacts pin the same revision.
    assert matrix.taxonomy_revision == taxonomy.semantic_revision
    assert len(taxonomy.semantic_revision) == 64


def test_regroup_timestamp_does_not_invalidate_the_matrix(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.taxonomy.state import (
        GroupingStatus,
        TaxonomyState,
        save_taxonomy_state,
    )

    profile_dir, corrections_path, _ = _seed(tmp_path)
    cluster_path = profile_dir / "cluster_map.json"
    before = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    save_taxonomy_state(
        TaxonomyState(
            maintenance_due=True,
            grouping_status={
                "rust": GroupingStatus(
                    reason="uncertain", last_attempted_at="2030-01-01T00:00:00+00:00"
                )
            },
        ),
        cluster_path,
    )
    after = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    assert after.semantic_revision == before.semantic_revision
    assert after.manifest.state != before.manifest.state
