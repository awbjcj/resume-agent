
from resume_agent.models.profile import Contact, Education
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
    TailoredSkill,
)
from resume_agent.render.renderer import output_filename, render_pdf


def test_output_filename_slugifies():
    name = output_filename("Acme Corp, Inc.", "Senior Backend Engineer", "20260609")
    assert name == "acme_corp_inc_senior_backend_engineer_20260609.pdf"


def _full_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(
            name="Ada Lovelace",
            email="ada@example.com",
            location="London, UK",
        ),
        summary="Backend engineer with a focus on reliability.",
        experience=[
            TailoredExperience(
                company="Analytical Engines",
                title="Staff Engineer",
                start="2020",
                end="Present",
                bullets=[TailoredBullet(text="Cut p99 latency by 40%.", provenance="b1")],
                provenance="e1",
            )
        ],
        projects=[
            TailoredProject(
                name="Looms",
                description="A distributed scheduler.",
                tech=["Python", "Rust"],
                bullets=[TailoredBullet(text="Open-sourced; 1k stars.", provenance="p1b1")],
                provenance="p1",
            )
        ],
        skills={"languages": [TailoredSkill(name="Python", provenance="s1")]},
        education=[Education(institution="Cambridge", degree="BA", field="Mathematics")],
    )


def test_render_pdf_writes_a_pdf(tmp_path):
    out = tmp_path / "resume.pdf"
    result = render_pdf(_full_content(), out, template_path="templates/resume.typ")
    assert result == out
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
