from __future__ import annotations

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.matrix import build_matrix
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _seed(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    save_cluster_map(
        ClusterMap(
            aliases={"js": "javascript"},
            domain_of={"javascript": "web-langs", "react": "web-frameworks"},
            domain_label={
                "web-langs": "Web Languages",
                "web-frameworks": "Web Frameworks",
            },
            category_of={
                "web-langs": "languages",
                "web-frameworks": "frontend-web",
            },
        ),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(
            aliases={"reactjs": "react"},
            domain_merges={"web-frameworks": "web-langs"},
            domain_renames={"web-langs": "Web Development"},
        ),
        corrections_path,
    )
    facts = ProfileFacts(
        contact=Contact(name="Candidate"),
        skills={"hard": [Skill(name="ReactJS"), Skill(name="JavaScript")]},
    )
    return profile_dir, corrections_path, facts


def test_uccm_mode_round_trips_the_effective_taxonomy_without_row_drift(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.taxonomy.graph_adapter import graph_to_cluster_map

    profile_dir, corrections_path, facts = _seed(tmp_path)
    legacy = build_effective_taxonomy(
        profile_dir,
        corrections_path=corrections_path,
        mode="legacy",
    )
    uccm = build_effective_taxonomy(
        profile_dir,
        corrections_path=corrections_path,
        mode="uccm",
    )

    assert uccm.capability_snapshot is not None
    assert graph_to_cluster_map(uccm.capability_snapshot.graph) == legacy.cluster_map
    assert uccm.cluster_map == legacy.cluster_map
    assert {event.operation for event in uccm.capability_snapshot.correction_events} >= {
        "alias",
        "merge_domain",
        "rename_domain",
    }
    assert uccm.capability_snapshot.revision.internal_graph_version
    assert uccm.manifest.capability is not None
    assert uccm.manifest.capability.effective_hash == uccm.semantic_revision

    legacy_rows = [row.model_dump() for row in build_matrix(facts, legacy).rows]
    uccm_rows = [row.model_dump() for row in build_matrix(facts, uccm).rows]
    assert uccm_rows == legacy_rows
