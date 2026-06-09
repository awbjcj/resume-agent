import pytest

from resume_agent.profile.resume_reader import read_resume_text


def test_reads_txt(tmp_path):
    f = tmp_path / "resume.txt"
    f.write_text("Ada Lovelace\nEngineer", encoding="utf-8")
    assert read_resume_text(f) == "Ada Lovelace\nEngineer"


def test_reads_docx(tmp_path):
    from docx import Document

    f = tmp_path / "resume.docx"
    doc = Document()
    doc.add_paragraph("Ada Lovelace")
    doc.add_paragraph("Analytical Engines Ltd")
    doc.save(str(f))

    text = read_resume_text(f)
    assert "Ada Lovelace" in text
    assert "Analytical Engines Ltd" in text


def test_unsupported_format_raises(tmp_path):
    f = tmp_path / "resume.rtf"
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        read_resume_text(f)
