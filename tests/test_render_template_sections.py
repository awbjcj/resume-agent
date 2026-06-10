from pypdf import PdfReader

from resume_agent.models.profile import Contact, Education, Language
from resume_agent.models.resume import (
    ResumeContent,
    TailoredAward,
    TailoredBullet,
    TailoredCertification,
    TailoredExperience,
    TailoredPublication,
)
from resume_agent.render.renderer import render_pdf


def _rich_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Jiajin Wu", email="x@example.com", location="Ann Arbor, MI"),
        summary="Vehicle systems engineer.",
        experience=[
            TailoredExperience(
                company="Aptiv",
                title="Triage Engineer",
                start="2023",
                end="Present",
                location="Troy, MI",
                provenance="e1",
                bullets=[TailoredBullet(text="Triaged L1-L3 ADAS issues", provenance="b1")],
            )
        ],
        education=[
            Education(
                institution="U-Mich",
                degree="M.Eng",
                field="Systems",
                end="2022",
                gpa="3.9",
                honors=["Dean's List"],
            )
        ],
        publications=[
            TailoredPublication(title="On ADAS Triage", venue="SAE", date="2022", provenance="pub1")
        ],
        certifications=[TailoredCertification(name="Six Sigma", issuer="ASQ", provenance="cer1")],
        awards=[TailoredAward(name="Best Intern", provenance="awa1")],
        languages=[Language(language="English", proficiency="native")],
        section_order=[
            "summary",
            "experience",
            "education",
            "publications",
            "certifications",
            "awards",
            "languages",
        ],
    )


def _text_of(pdf_path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf_path)).pages)


def test_template_renders_all_new_sections(tmp_path):
    out = tmp_path / "rich.pdf"
    render_pdf(_rich_content(), out, template_path="templates/resume.typ")
    assert out.read_bytes().startswith(b"%PDF")
    text = _text_of(out)
    for needle in [
        "PUBLICATIONS",
        "CERTIFICATIONS",
        "AWARDS",
        "LANGUAGES",
        "EDUCATION",
        "3.9",
        "Six Sigma",
    ]:
        assert needle in text, f"missing {needle!r} in rendered PDF"
