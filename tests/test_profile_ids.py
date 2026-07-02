from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Skill,
)
from resume_agent.profile.ids import assign_fact_ids, deterministic_id


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                bullets=[
                    Bullet(text="Shipped the thing"),
                    Bullet(text="Shipped the thing"),
                ],
            )
        ],
        skills={"Languages": [Skill(name="Python")]},
        github_profile=GitHubProfile(username="ada"),
    )


def test_ids_are_stable_across_calls():
    first = assign_fact_ids(_facts(), "resume-abc")
    second = assign_fact_ids(_facts(), "resume-abc")
    assert first.experience[0].id == second.experience[0].id
    assert [item.id for item in first.experience[0].bullets] == [
        item.id for item in second.experience[0].bullets
    ]
    assert first.skills["Languages"][0].id == second.skills["Languages"][0].id


def test_ids_differ_by_doc():
    first = assign_fact_ids(_facts(), "resume-abc")
    second = assign_fact_ids(_facts(), "deck-def")
    assert first.experience[0].id != second.experience[0].id


def test_duplicate_content_gets_unique_ids():
    facts = assign_fact_ids(_facts(), "resume-abc")
    first, second = facts.experience[0].bullets
    assert first.id != second.id


def test_source_ref_set_everywhere():
    facts = assign_fact_ids(_facts(), "resume-abc")
    assert facts.experience[0].source_ref == "resume-abc"
    assert facts.experience[0].bullets[0].source_ref == "resume-abc"
    assert facts.skills["Languages"][0].source_ref == "resume-abc"
    assert facts.github_profile is not None
    assert facts.github_profile.source_ref == "resume-abc"


def test_assign_fact_ids_returns_deep_copy():
    original = _facts()
    updated = assign_fact_ids(original, "resume-abc")
    assert updated is not original
    assert original.experience[0].source_ref is None


def test_deterministic_id_shape():
    assert deterministic_id("a", "b") == deterministic_id("a", "b")
    assert len(deterministic_id("a", "b")) == 12
