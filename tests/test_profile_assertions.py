from __future__ import annotations

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
    from resume_agent.profile.assertion_builder import build_capability_assertions

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

    with pytest.raises(ValueError, match="missing evidence fact IDs"):
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

