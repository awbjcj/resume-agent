from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.models.base import Source
import pytest
from pydantic import ValidationError


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
        bullets=[Bullet(text="Wrote the first algorithm")],
    )
    assert exp.id  # experience itself has an id
    assert exp.bullets[0].id  # each bullet has an id
    assert exp.bullets[0].text == "Wrote the first algorithm"


def test_skills_is_an_open_ended_category_map():
    p = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "languages": [Skill(name="Python")],
            "cloud": [Skill(name="AWS"), Skill(name="GCP", source=Source.manual)],
        },
    )
    assert [skill.name for skill in p.skills["cloud"]] == ["AWS", "GCP"]
    assert p.skills["cloud"][0].id
    assert p.skills["cloud"][1].source.value == "manual"


def test_github_project_and_profile_signals_are_modeled():
    proj = Project(
        name="repo",
        source=Source.github,
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


def test_skill_inference_fields_default_off():
    skill = Skill(name="Python")
    assert skill.inferred is False
    assert skill.evidence_fact_ids == []
    assert skill.category is None
    assert skill.source_ref is None


def test_inferred_skill_round_trips():
    skill = Skill(
        name="Mentorship",
        inferred=True,
        evidence_fact_ids=["abc123def456"],
        category="soft",
    )
    loaded = Skill.model_validate_json(skill.model_dump_json())
    assert loaded.inferred is True
    assert loaded.evidence_fact_ids == ["abc123def456"]
    assert loaded.category == "soft"


def test_inferred_skill_requires_category_and_evidence():
    with pytest.raises(ValidationError):
        Skill(name="Mentorship", inferred=True, category="soft")
    with pytest.raises(ValidationError):
        Skill(name="Mentorship", inferred=True, evidence_fact_ids=["fact-1"])


def test_legacy_facts_json_still_loads():
    legacy = {
        "contact": {"name": "Ada"},
        "skills": {"Languages": [{"name": "Python"}]},
    }
    facts = ProfileFacts.model_validate(legacy)
    skill = facts.skills["Languages"][0]
    assert skill.inferred is False and skill.source_ref is None
