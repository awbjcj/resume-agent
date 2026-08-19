from __future__ import annotations

from resume_agent.discovery.requirements import bind_job_requirements
from resume_agent.matching.engine import match_requirement
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Skill
from resume_agent.profile.matrix import build_matrix
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy


def test_profile_build_and_requirement_binding_share_canonical_identity():
    taxonomy = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"py": "python", "python": "python"})
    )
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
        JobCriteria(tech_stack=["Python"]),
        job_id=42,
        jd_text="Python is required.",
        taxonomy_revision=taxonomy.semantic_revision,
        aliases=taxonomy.cluster_map.aliases,
    )

    requirement = criteria.typed_requirements[0]
    assertion = matrix.assertions[0]
    result = match_requirement(
        requirement,
        matrix.assertions,
        CareerCapabilityGraph(model_version="test"),
    )

    assert requirement.parsed_concept_id == assertion.concept_id
    assert result.status == "verified_exact"
    assert result.assertion_id == assertion.id
    assert result.evidence_fact_ids == ["skill-python", "bullet-python"]
