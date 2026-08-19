from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Project,
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


def test_project_highlights_receive_stable_ids_and_source_refs():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="Tool", highlights=[Bullet(text="Automated deploys")])],
    )

    assigned = assign_fact_ids(facts, "project-source")
    project = assigned.projects[0]
    highlight = project.highlights[0]

    assert project.id
    assert highlight.id
    assert (project.source_ref, highlight.source_ref) == (
        "project-source",
        "project-source",
    )


def test_assign_fact_ids_returns_deep_copy():
    original = _facts()
    updated = assign_fact_ids(original, "resume-abc")
    assert updated is not original
    assert original.experience[0].source_ref is None


def test_assign_fact_ids_remaps_evidence_references_to_deterministic_ids():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[
            Project(
                id="project:tool",
                name="Tool",
                highlights=[
                    Bullet(id="project:tool:highlight:1", text="Automated deploys")
                ],
            )
        ],
        skills={
            "hard": [
                Skill(
                    id="skill:python",
                    name="Python",
                    evidence_fact_ids=[
                        "project:tool:highlight:1",
                        "missing-external-id",
                    ],
                )
            ]
        },
    )

    assigned = assign_fact_ids(facts, "project-source")

    assert assigned.skills["hard"][0].evidence_fact_ids == [
        assigned.projects[0].highlights[0].id,
        "missing-external-id",
    ]
    assert facts.skills["hard"][0].evidence_fact_ids == [
        "project:tool:highlight:1",
        "missing-external-id",
    ]


def test_deterministic_id_shape():
    assert deterministic_id("a", "b") == deterministic_id("a", "b")
    assert len(deterministic_id("a", "b")) == 12
