from dataclasses import dataclass

from resume_agent.discovery.url_ingest.llm import extract_fields, html_to_text
from resume_agent.discovery.url_ingest.models import ExtractedJob


def test_html_to_text_strips_scripts_and_chrome():
    html = (
        "<html><head><style>.x{}</style></head>"
        "<body><nav>Home</nav><script>var a=1;</script>"
        "<p>Real job text.</p></body></html>"
    )
    text = html_to_text(html)
    assert "Real job text." in text
    assert "var a=1" not in text
    assert "Home" not in text


@dataclass
class _Result:
    content: object


class _FakeAgent:
    def run(self, prompt):
        return _Result(ExtractedJob(title="Eng", company="Initech", jd_text="Do work."))


def test_extract_fields_returns_schema():
    job = extract_fields("page text", _FakeAgent())
    assert job.title == "Eng"
    assert job.company == "Initech"
    assert job.jd_text == "Do work."


class _BadAgent:
    def run(self, prompt):
        return _Result("not a schema")


def test_extract_fields_rejects_wrong_type():
    import pytest

    with pytest.raises(TypeError):
        extract_fields("x", _BadAgent())
