from resume_agent.cover_letter.provenance import (
    collect_fact_ids,
    unsupported_provenance,
)
from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact, Experience, ProfileFacts, Skill


def _facts():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer")],
        skills={"languages": [Skill(id="sk1", name="Python")]},
    )


def _letter(*provenances):
    return CoverLetterContent(
        contact=Contact(name="Ada"),
        greeting="Hi,",
        paragraphs=[
            CoverLetterParagraph(text="p", provenance=list(p)) for p in provenances
        ],
        closing="Bye",
    )


def test_collect_fact_ids_includes_experiences_and_skills():
    ids = collect_fact_ids(_facts())
    assert "exp1" in ids and "sk1" in ids


def test_supported_letter_has_no_unsupported_ids():
    assert (
        unsupported_provenance(_letter(["exp1"], ["sk1"]), collect_fact_ids(_facts()))
        == []
    )


def test_fabricated_provenance_is_flagged():
    bad = unsupported_provenance(
        _letter(["exp1"], ["GHOST"]), collect_fact_ids(_facts())
    )
    assert bad == ["GHOST"]
