from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Skill,
)
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.graph_models import (
    CareerCapabilityGraph,
    ConceptNode,
    EffectiveCapabilitySnapshot,
    TaxonomyRevision,
)
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy


def _taxonomy() -> EffectiveTaxonomy:
    return EffectiveTaxonomy.from_parts(
        ClusterMap(
            aliases={"py": "python"},
            domain_of={"python": "languages", "mentorship": "leadership"},
        )
    )


def _facts() -> ProfileFacts:
    bullet = Bullet(
        id="bullet-python",
        text="Built Python services and mentored three engineers",
    )
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="experience-1",
                company="Acme",
                title="Senior Python Engineer",
                current=True,
                bullets=[bullet],
                tech=["Python"],
            )
        ],
        skills={
            "hard": [Skill(id="skill-python", name="Py", aliases=["Python"])],
            "soft": [
                Skill(
                    id="skill-mentorship",
                    name="Mentorship",
                    inferred=True,
                    category="soft",
                    evidence_fact_ids=[bullet.id],
                )
            ],
        },
    )


def test_assertions_are_evidence_backed_and_keep_dimensions_independent():
    from resume_agent.profile.assertion_builder import build_capability_assertions

    assertions = build_capability_assertions(
        _facts(), _taxonomy(), today=date(2026, 8, 19)
    )
    by_key = {item.legacy_projection.key: item for item in assertions}

    python = by_key["python"]
    assert python.concept_type == "tool_technology"
    assert python.assertion_status == "evidenced"
    assert python.claimability == "literal_evidenced"
    assert set(python.evidence_fact_ids) == {"skill-python", "bullet-python"}
    assert python.last_used == "current"
    assert python.proficiency_level is None
    assert python.autonomy is None
    assert python.complexity is None
    assert python.responsibility_scope is None
    assert python.influence_scope is None
    assert python.evidence_confidence == 1.0

    mentorship = by_key["mentorship"]
    assert mentorship.concept_type == "unknown"
    assert mentorship.assertion_status == "inferred"
    assert mentorship.claimability == "supported_inference"
    assert mentorship.evidence_fact_ids == ["skill-mentorship", "bullet-python"]


def test_title_alone_does_not_create_an_assertion_or_level():
    from resume_agent.profile.assertion_builder import build_capability_assertions

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="experience-1",
                company="Acme",
                title="Chief Artificial Intelligence Officer",
            )
        ],
    )

    assert build_capability_assertions(facts, _taxonomy()) == []


def test_missing_evidence_reference_is_rejected():
    from resume_agent.profile.assertion_builder import (
        InvalidEvidenceReferencesError,
        build_capability_assertions,
    )

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "soft": [
                Skill(
                    id="skill-mentorship",
                    name="Mentorship",
                    inferred=True,
                    category="soft",
                    evidence_fact_ids=["missing-bullet"],
                )
            ]
        },
    )

    with pytest.raises(
        InvalidEvidenceReferencesError, match="missing evidence fact IDs"
    ):
        build_capability_assertions(facts, _taxonomy())


def test_assertion_ids_and_order_are_deterministic():
    from resume_agent.profile.assertion_builder import build_capability_assertions

    first = build_capability_assertions(_facts(), _taxonomy())
    second = build_capability_assertions(_facts(), _taxonomy())

    assert [item.id for item in first] == [item.id for item in second]
    assert [item.legacy_projection.key for item in first] == [
        "mentorship",
        "python",
    ]


def test_never_candidate_claim_seed_is_not_bound_to_a_profile_assertion():
    from resume_agent.profile.assertion_builder import build_capability_assertions

    taxonomy = _taxonomy()
    revision = TaxonomyRevision(
        internal_graph_version="test",
        external_source_snapshots=(),
        crosswalk_revision="",
        tenant_overlay_revision="",
        generated_legacy_map_revision="",
        correction_ledger_revision="",
        lifecycle_state_revision="",
        canonicalization_override_revision="",
        correction_policy_version="",
        matching_policy_version="",
        effective_hash=taxonomy.semantic_revision,
    )
    taxonomy = replace(
        taxonomy,
        capability_snapshot=EffectiveCapabilitySnapshot(
            graph=CareerCapabilityGraph(
                model_version="test",
                nodes=[
                    ConceptNode(
                        id="internal:competency-family:communication",
                        type="competency_family",
                        preferred_label="Communication",
                        normalized_label="communication",
                        claim_policy="never_candidate_claim",
                        type_assignment_status="governed",
                        source_refs=["source:test"],
                    )
                ],
            ),
            legacy_projection=taxonomy.cluster_map,
            correction_events=(),
            revision=revision,
        ),
    )
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"soft": [Skill(id="skill-communication", name="Communication")]},
    )

    [assertion] = build_capability_assertions(facts, taxonomy)

    assert assertion.concept_id != "internal:competency-family:communication"
