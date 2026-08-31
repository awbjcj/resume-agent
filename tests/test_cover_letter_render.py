from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.cover_letter.render import render_cover_letter
from resume_tailor_harness.discovery.ingest import add_job
from resume_tailor_harness.tracking.repository import get_cover_letter, save_cover_letter
from resume_tailor_harness.tracking.tables import CoverLetter


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_render_cover_letter_writes_pdf_path(tmp_path):
    calls = {}

    def fake_render(content, output_path, template_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        calls["path"] = Path(output_path)
        return Path(output_path)

    with _session() as s:
        job = add_job(
            s,
            source="manual",
            jd_text="jd",
            company="Acme Corp",
            title="Backend Engineer",
        )
        assert job is not None and job.id is not None
        cover = save_cover_letter(
            s,
            CoverLetter(
                job_id=job.id,
                content_json={
                    "contact": {"name": "Ada"},
                    "greeting": "Hi",
                    "paragraphs": [],
                    "closing": "Bye",
                },
            ),
        )
        assert cover.id is not None
        out = render_cover_letter(
            s, cover.id, output_dir=str(tmp_path), render_fn=fake_render
        )
        assert out == calls["path"]
        fetched = get_cover_letter(s, cover.id)
        assert fetched is not None
        assert fetched.pdf_path == str(out)
        assert out is not None
        assert out.name == f"cover-letter-v{cover.id}-draft.pdf"
        assert "acme_corp-backend_engineer" in out.parent.name


def test_render_missing_cover_letter_returns_none(tmp_path):
    with _session() as s:
        assert (
            render_cover_letter(s, 999, output_dir=str(tmp_path))
            is None
        )
