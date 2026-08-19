from __future__ import annotations

from resume_agent.models.profile import (
    Certification,
    Contact,
    Education,
    Language,
    ProfileFacts,
)


def test_requirement_lane_facts_are_explicit_and_never_inferred():
    from resume_agent.profile.requirement_facts import build_requirement_facts

    facts = ProfileFacts(
        contact=Contact(
            name="Ada",
            work_authorization="Authorized to work in the United States",
        ),
        certifications=[
            Certification(
                id="cert-verified",
                name="AWS Certified Solutions Architect",
                credential_id="ABC-123",
            ),
            Certification(id="cert-asserted", name="PMP"),
        ],
        education=[
            Education(id="education-1", institution="Example", degree="BS")
        ],
        languages=[Language(id="language-1", language="English")],
    )

    requirement_facts = build_requirement_facts(facts)
    by_id = {item.evidence_fact_id: item for item in requirement_facts}

    assert by_id["cert-verified"].fact_type == "credential"
    assert by_id["cert-verified"].verification_status == "verified"
    assert by_id["cert-asserted"].verification_status == "asserted"
    assert by_id["education-1"].fact_type == "education"
    assert by_id["language-1"].fact_type == "language"
    authorization = next(
        item for item in requirement_facts if item.fact_type == "work_authorization"
    )
    assert authorization.verification_status == "asserted"
    assert authorization.display == "Authorized to work in the United States"


def test_absent_requirement_lane_values_do_not_create_placeholder_facts():
    from resume_agent.profile.requirement_facts import build_requirement_facts

    facts = ProfileFacts(contact=Contact(name="Ada"))

    assert build_requirement_facts(facts) == []
