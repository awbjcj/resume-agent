import pytest
from pydantic import ValidationError

from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)


def test_tailored_bullet_requires_provenance():
    b = TailoredBullet(text="Built X", provenance="abc123def456")
    assert b.provenance == "abc123def456"


def test_tailored_bullet_provenance_is_mandatory():
    with pytest.raises(ValidationError):
        TailoredBullet(text="Built X")  # no provenance -> fabrication risk


def test_tailored_skill_requires_provenance():
    skill = TailoredSkill(name="Python", provenance="skill0000001")
    assert skill.name == "Python"
    assert skill.provenance == "skill0000001"


def test_resume_content_assembles_from_facts_contact():
    rc = ResumeContent(
        contact=Contact(name="Ada Lovelace"),
        summary="Engineer",
        experience=[
            TailoredExperience(
                company="Analytical Engines Ltd",
                title="Engineer",
                provenance="exp000000001",
                bullets=[TailoredBullet(text="Wrote the first algorithm", provenance="bul000000001")],
            )
        ],
    )
    assert rc.contact.name == "Ada Lovelace"
    assert rc.experience[0].bullets[0].provenance == "bul000000001"


def test_resume_content_round_trips_json():
    rc = ResumeContent(contact=Contact(name="Ada"))
    restored = ResumeContent.model_validate_json(rc.model_dump_json())
    assert restored.contact.name == "Ada"
