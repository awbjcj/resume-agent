from resume_agent.models.cover_letter import CoverLetterContent, CoverLetterParagraph
from resume_agent.models.profile import Contact


def test_cover_letter_content_roundtrips():
    content = CoverLetterContent(
        contact=Contact(name="Ada Lovelace", email="ada@x.io"),
        recipient="Hiring Team at Acme",
        greeting="Dear Hiring Team,",
        paragraphs=[CoverLetterParagraph(text="I build payment systems.", provenance=["exp1"])],
        closing="Sincerely\nAda Lovelace",
    )
    dumped = content.model_dump(mode="json")
    again = CoverLetterContent.model_validate(dumped)
    assert again.paragraphs[0].provenance == ["exp1"]
    assert again.contact.name == "Ada Lovelace"
