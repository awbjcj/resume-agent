from __future__ import annotations

from datetime import date

from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Skill
from resume_agent.profile.assertion_builder import build_capability_assertions
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


def test_profile_projection_exposes_all_layers_with_assertion_evidence_links():
    from resume_agent.profile.projections import build_profile_projection

    taxonomy = _taxonomy()
    assertions = build_capability_assertions(
        _facts(), taxonomy, today=date(2026, 8, 19)
    )
    projection = build_profile_projection(assertions, taxonomy)

    assert [layer.layer for layer in projection.layers] == [
        "career_core",
        "foundational",
        "transferable_function",
        "domain_industry",
        "occupation_role",
        "enabler",
    ]
    enablers = next(layer for layer in projection.layers if layer.layer == "enabler")
    python = next(item for item in enablers.items if item.display == "Py")
    assert python.assertion_ids
    assert set(python.evidence_fact_ids) == {"skill-python", "bullet-python"}

    domains = next(
        layer for layer in projection.layers if layer.layer == "domain_industry"
    )
    assert {item.display for item in domains.items} == {"Mentorship"}


def test_evidence_quality_and_development_needs_keep_unknown_separate():
    from resume_agent.profile.projections import build_profile_projection

    assertions = build_capability_assertions(_facts(), _taxonomy())
    projection = build_profile_projection(assertions, _taxonomy())

    assert projection.evidence_quality.counts == {"evidenced": 1, "inferred": 1}
    assert projection.evidence_quality.assertion_ids == sorted(
        assertion.id for assertion in assertions
    )
    mentorship = next(
        need for need in projection.development_needs if need.reason == "unknown_type"
    )
    assert mentorship.assertion_id == next(
        item.id for item in assertions if item.legacy_projection.key == "mentorship"
    )
