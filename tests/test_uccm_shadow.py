from __future__ import annotations

import pytest

from resume_agent.discovery.requirements import bind_job_requirements
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Skill
from resume_agent.profile.matrix import build_matrix
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy


def _artifacts():
    cluster_map = ClusterMap(aliases={"py": "python", "python": "python"})
    taxonomy = EffectiveTaxonomy.from_parts(cluster_map)
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="experience-1",
                company="Acme",
                title="Engineer",
                current=True,
                bullets=[Bullet(id="bullet-python", text="Built Python services")],
            )
        ],
        skills={"hard": [Skill(id="skill-python", name="Py")]},
    )
    matrix = build_matrix(facts, taxonomy)
    criteria = bind_job_requirements(
        JobCriteria(tech_stack=["Python"], remote_policy="remote"),
        job_id=42,
        jd_text="Python is required for this remote role.",
        taxonomy_revision=taxonomy.semantic_revision,
        aliases=cluster_map.aliases,
    )
    return taxonomy, matrix, criteria


def test_shadow_batch_uses_actual_legacy_match_and_precise_v2_result():
    from resume_agent.matching.shadow import build_shadow_matches

    taxonomy, matrix, criteria = _artifacts()
    results = build_shadow_matches(
        criteria,
        matrix,
        taxonomy.cluster_map,
        CareerCapabilityGraph(model_version="test"),
        expected_taxonomy_revision=taxonomy.semantic_revision,
    )
    by_requirement = {
        result.v2.requirement_label.casefold(): result for result in results
    }

    assert by_requirement["python"].legacy_coverage == "covered"
    assert by_requirement["python"].v2.status == "verified_exact"
    assert by_requirement["remote"].legacy_coverage == "not_evaluated"


def test_shadow_batch_rejects_a_mixed_profile_taxonomy_revision():
    from resume_agent.matching.shadow import (
        StaleUccmArtifactError,
        build_shadow_matches,
    )

    taxonomy, matrix, criteria = _artifacts()

    with pytest.raises(StaleUccmArtifactError, match="profile matrix taxonomy revision"):
        build_shadow_matches(
            criteria,
            matrix,
            taxonomy.cluster_map,
            CareerCapabilityGraph(model_version="test"),
            expected_taxonomy_revision="different",
        )
