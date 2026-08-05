from resume_agent.models.profile import (
    Award,
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredAward,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
)
from resume_agent.models.review import Severity
from resume_agent.tailor.numeric_evidence import (
    NUMERIC_EVIDENCE_REVIEWER,
    claim_numbers,
    fact_numbers,
    numeric_evidence_critique,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Engineer",
                start="2023-02",
                bullets=[
                    Bullet(id="b1", text="Triaged 267 tickets across 9 programs"),
                    Bullet(id="b2", text="Facilitated the test procedures"),
                ],
            )
        ],
        projects=[
            Project(id="p1", name="Looms", highlights=["Cut p95 latency to 500ms"])
        ],
        awards=[Award(id="a1", name="Innovation Award")],
    )


def _resume(**kwargs) -> ResumeContent:
    return ResumeContent(contact=Contact(name="Ada"), **kwargs)


def _bullet_resume(text: str, provenance: str) -> ResumeContent:
    return _resume(
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[TailoredBullet(text=text, provenance=provenance)],
            )
        ]
    )


def test_number_present_in_the_cited_fact_passes():
    content = _bullet_resume("Triaged 267 tickets", "b1")

    critique = numeric_evidence_critique(content, _facts())

    assert critique.reviewer == NUMERIC_EVIDENCE_REVIEWER
    assert critique.passed is True
    assert critique.score == 100
    assert critique.issues == []


def test_number_absent_from_the_cited_fact_blocks():
    content = _bullet_resume("Reduced test planning effort by 40%", "b2")

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert critique.score == 0
    assert [i.severity for i in critique.issues] == [Severity.blocking]
    assert "40" in critique.issues[0].message


def test_a_currency_amount_is_checked_like_any_other_quantity():
    # "$50K saved" is the invented-outcome class the gate exists to catch; a
    # leading currency symbol must not carry it past the tokenizer unexamined.
    content = _bullet_resume("Saved $50K in licensing", "b2")

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert "50" in critique.issues[0].message


def test_a_currency_amount_the_cited_fact_states_passes():
    facts = _facts()
    facts.experience[0].bullets[1].text = "Renegotiated a $50K licensing contract"
    content = _bullet_resume("Saved $50K in licensing", "b2")

    assert numeric_evidence_critique(content, facts).passed is True


def test_a_sibling_bullets_number_does_not_license_the_claim():
    """Citing b2 must not inherit b1's numbers."""
    content = _bullet_resume("Triaged 267 tickets", "b2")

    assert numeric_evidence_critique(content, _facts()).passed is False


def test_summary_numbers_check_against_summary_provenance():
    content = _resume(
        summary="3+ years building automation", summary_provenance=["b2"]
    )

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert critique.issues[0].location == "summary"


def test_unresolvable_provenance_is_left_to_the_provenance_gate():
    content = _bullet_resume("Shipped 12 releases", "nope")

    assert numeric_evidence_critique(content, _facts()).issues == []


def test_project_description_and_bullets_are_checked():
    content = _resume(
        projects=[
            TailoredProject(
                name="Looms",
                description="Cut latency to 500ms",
                provenance="p1",
                bullets=[TailoredBullet(text="Served 4000 users", provenance="p1")],
            )
        ]
    )

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    messages = " ".join(i.message for i in critique.issues)
    assert "4000" in messages
    assert "500" not in messages, "500ms is stated by the project highlight"


def test_award_description_numbers_are_checked():
    content = _resume(
        awards=[
            TailoredAward(
                name="Innovation Award",
                description="Top 10 performer",
                provenance="a1",
            )
        ]
    )

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert "10" in critique.issues[0].message


def test_claim_numbers_skips_numbers_welded_to_letters():
    assert claim_numbers("Cut p95 latency on GPT-4 and L1-L3 in C++") == []


def test_claim_numbers_reads_standalone_values_with_units():
    assert claim_numbers("Handled 430+ tickets, 95% clean, in 500ms (1,200 runs)") == [
        "430",
        "95",
        "500",
        "1200",
    ]


def test_fact_numbers_ignores_child_bullets():
    experience = _facts().experience[0]

    numbers = fact_numbers(experience)

    assert "267" not in numbers
    assert "2023" in numbers
