from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Publication,
)
from resume_agent.profile.validate import validate_profile


def test_clean_profile_has_no_warnings():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(company="AE", title="Eng", bullets=[Bullet(text="X")])],
    )
    report = validate_profile(facts, raw_text="Ada, Engineer at AE")
    assert report.ok is True
    assert report.warnings == []


def test_missing_name_is_flagged():
    facts = ProfileFacts(contact=Contact(name=""))
    report = validate_profile(facts, raw_text="")
    assert report.ok is False
    assert any("name" in warning for warning in report.warnings)


def test_experience_without_bullets_is_flagged():
    facts = ProfileFacts(
        contact=Contact(name="Ada"), experience=[Experience(company="AE", title="Eng")]
    )
    report = validate_profile(facts, raw_text="x")
    assert any("no bullets" in warning for warning in report.warnings)


def test_publications_in_text_but_not_extracted_is_flagged():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    report = validate_profile(
        facts, raw_text="PUBLICATIONS\nSmith, A. Great Paper. 2022."
    )
    assert any("publication" in warning.lower() for warning in report.warnings)


def test_publications_present_when_extracted():
    facts = ProfileFacts(
        contact=Contact(name="Ada"), publications=[Publication(title="Great Paper")]
    )
    report = validate_profile(
        facts, raw_text="PUBLICATIONS\nSmith, A. Great Paper. 2022."
    )
    assert not any("publication" in warning.lower() for warning in report.warnings)
