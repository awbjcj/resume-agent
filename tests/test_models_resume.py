import pytest
from pydantic import ValidationError

from resume_agent.models.profile import Contact, Language
from resume_agent.models.resume import (
    ResumeContent,
    TailoredAward,
    TailoredBullet,
    TailoredCertification,
    TailoredExperience,
    TailoredPublication,
    TailoredSkill,
    TailoredVolunteer,
)


def test_tailored_bullet_requires_provenance():
    b = TailoredBullet(text="Built X", provenance="abc123def456")
    assert b.provenance == "abc123def456"


def test_tailored_bullet_provenance_is_mandatory():
    with pytest.raises(ValidationError):
        TailoredBullet.model_validate({"text": "Built X"})  # no provenance -> fabrication risk


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


def test_new_sections_default_empty():
    rc = ResumeContent(contact=Contact(name="Ada"))
    assert rc.publications == []
    assert rc.certifications == []
    assert rc.awards == []
    assert rc.languages == []
    assert rc.volunteer == []
    assert rc.section_order is None


def test_tailored_publication_requires_provenance():
    with pytest.raises(ValidationError):
        TailoredPublication.model_validate({"title": "On Computable Numbers"})


def test_resume_content_carries_new_sections_round_trip():
    rc = ResumeContent(
        contact=Contact(name="Ada"),
        publications=[
            TailoredPublication(
                title="Notes on the Engine", venue="Memoirs", provenance="pub000000001"
            )
        ],
        certifications=[TailoredCertification(name="PE", issuer="NSPE", provenance="cer000000001")],
        awards=[TailoredAward(name="Best Paper", provenance="awa000000001")],
        languages=[Language(language="English", proficiency="native")],
        volunteer=[
            TailoredVolunteer(organization="OSS", role="Maintainer", provenance="vol000000001")
        ],
        section_order=["experience", "education", "publications"],
    )
    restored = ResumeContent.model_validate_json(rc.model_dump_json())
    assert restored.publications[0].title == "Notes on the Engine"
    assert restored.section_order == ["experience", "education", "publications"]
