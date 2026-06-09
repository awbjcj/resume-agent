from resume_agent.models.profile import (
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Project,
    Skill,
)


def make_minimal_profile() -> ProfileFacts:
    return ProfileFacts(contact=Contact(name="Ada Lovelace"))


def test_minimal_profile_only_needs_contact_name():
    p = make_minimal_profile()
    assert p.contact.name == "Ada Lovelace"
    assert p.experience == []
    assert p.skills == {}


def test_experience_bullets_get_provenance_ids():
    exp = Experience(
        company="Analytical Engines Ltd",
        title="Engineer",
        bullets=[{"text": "Wrote the first algorithm"}],
    )
    assert exp.id  # experience itself has an id
    assert exp.bullets[0].id  # each bullet has an id
    assert exp.bullets[0].text == "Wrote the first algorithm"


def test_skills_is_an_open_ended_category_map():
    p = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"languages": [{"name": "Python"}], "cloud": [Skill(name="AWS"), {"name": "GCP", "source": "manual"}]},
    )
    assert [skill.name for skill in p.skills["cloud"]] == ["AWS", "GCP"]
    assert p.skills["cloud"][0].id
    assert p.skills["cloud"][1].source.value == "manual"


def test_github_project_and_profile_signals_are_modeled():
    proj = Project(
        name="repo",
        source="github",
        repo_url="https://github.com/x/repo",
        stars=10,
        languages=["Python"],
        topics=["llm"],
        is_fork=False,
    )
    profile = GitHubProfile(username="ada", followers=42, top_languages=["Python"], total_stars=10)
    assert proj.source.value == "github"
    assert proj.stars == 10
    assert profile.source.value == "github"
    assert profile.total_stars == 10


def test_profile_round_trips_through_json():
    p = make_minimal_profile()
    restored = ProfileFacts.model_validate_json(p.model_dump_json())
    assert restored.contact.name == "Ada Lovelace"
    assert restored.schema_version == 1
