import resume_agent.discovery.url_ingest.service as service
from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent
from resume_agent.discovery.url_ingest.service import read_linkedin_posting


def _patch_fetch(monkeypatch, html, final_url):
    monkeypatch.setattr(
        service, "fetch_page",
        lambda url, allow_browser=True: PageContent(html=html, final_url=final_url, rendered=False),
    )


class _Agent:
    def run(self, prompt):
        raise AssertionError("LLM should not run for known domains")


def test_greenhouse_url_uses_parser(monkeypatch):
    html = (
        '<html><body><h1 class="app-title">Dev</h1>'
        '<span class="company-name">at Hooli</span>'
        '<div class="location">SF</div>'
        '<div id="content"><p>Write code.</p></div></body></html>'
    )
    _patch_fetch(monkeypatch, html, "https://boards.greenhouse.io/hooli/jobs/1")

    job = service.job_from_url("https://boards.greenhouse.io/hooli/jobs/1", agent=_Agent())

    assert job is not None
    assert job.source == "url"
    assert job.company == "Hooli"
    assert job.title == "Dev"
    assert "Write code." in job.jd_text


def test_linkedin_url_uses_parser(monkeypatch):
    html = (
        '<html><body><h1 class="top-card-layout__title">SRE</h1>'
        '<a class="topcard__org-name-link">Pied Piper</a>'
        '<span class="topcard__flavor--bullet">Remote</span>'
        '<div class="show-more-less-html__markup">Keep it up.</div></body></html>'
    )
    _patch_fetch(monkeypatch, html, "https://www.linkedin.com/jobs/view/9")

    job = service.job_from_url("https://www.linkedin.com/jobs/view/9", agent=_Agent())

    assert job is not None
    assert job.company == "Pied Piper"
    assert job.title == "SRE"
    assert "Keep it up." in job.jd_text


def test_unknown_site_uses_llm(monkeypatch):
    _patch_fetch(monkeypatch, "<html><body><p>Some role.</p></body></html>", "https://acme.test/job")

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="Lead", company="Acme", jd_text="Lead the team.")
            return _R()

    job = service.job_from_url("https://acme.test/job", agent=_LLM())

    assert job is not None
    assert job.company == "Acme"
    assert job.jd_text == "Lead the team."


def test_empty_jd_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, "<html><body></body></html>", "https://boards.greenhouse.io/x")

    job = service.job_from_url("https://boards.greenhouse.io/x", agent=_Agent())

    assert job is None


def test_recognized_ats_without_a_reader_falls_back_to_llm(monkeypatch):
    # Lever is identified by detect.py but has no registered posting reader yet,
    # so url_ingest should fall through to the LLM rather than fail.
    _patch_fetch(
        monkeypatch,
        "<html><body><p>Some role.</p></body></html>",
        "https://jobs.lever.co/acme/abc-123",
    )

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="Eng", company="Acme", jd_text="real jd")
            return _R()

    job = service.job_from_url("https://jobs.lever.co/acme/abc-123", agent=_LLM())

    assert job is not None
    assert job.jd_text == "real jd"


def test_read_linkedin_posting_extracts_fields():
    html = (
        '<html><body><h1 class="top-card-layout__title">SRE</h1>'
        '<a class="topcard__org-name-link">Pied Piper</a>'
        '<span class="topcard__flavor--bullet">Remote</span>'
        '<div class="show-more-less-html__markup">Keep it up.</div></body></html>'
    )
    extracted = read_linkedin_posting(html)
    assert extracted.title == "SRE"
    assert extracted.company == "Pied Piper"
    assert "Keep it up." in extracted.jd_text


def test_spoof_host_does_not_route_to_known_parser(monkeypatch):
    _patch_fetch(
        monkeypatch,
        "<html><body><p>Some role.</p></body></html>",
        "https://notlinkedin.com.evil.io/job",
    )

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="X", company="Y", jd_text="real jd")
            return _R()

    job = service.job_from_url("https://notlinkedin.com.evil.io/job", agent=_LLM())

    assert job is not None
    assert job.jd_text == "real jd"
