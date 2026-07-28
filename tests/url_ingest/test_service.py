from resume_agent.discovery.url_ingest import service
from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent
from resume_agent.discovery.url_ingest.service import read_linkedin_posting


def _patch_fetch(monkeypatch, html, final_url):
    """Patch both fetch paths: fetch_static for known-ATS/unknown-host dispatch,
    fetch_page for the LinkedIn / JS-shell-upgrade branches."""
    monkeypatch.setattr(
        service, "fetch_static",
        lambda url: PageContent(html=html, final_url=final_url, rendered=False),
    )
    monkeypatch.setattr(
        service, "fetch_page",
        lambda url, allow_browser=True: PageContent(html=html, final_url=final_url, rendered=False),
    )


class _Agent:
    def run(self, prompt):
        raise AssertionError("LLM should not run for known domains")

    async def arun(self, prompt):
        return self.run(prompt)


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

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://acme.test/job", agent=_LLM())

    assert job is not None
    assert job.company == "Acme"
    assert job.jd_text == "Lead the team."


def test_empty_jd_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, "<html><body></body></html>", "https://boards.greenhouse.io/x")

    job = service.job_from_url("https://boards.greenhouse.io/x", agent=_Agent())

    assert job is None


def test_recognized_ats_without_a_reader_falls_back_to_llm(monkeypatch):
    # A host detect.py resolves but with no registered ats_readers entry (or
    # whose reader can't locate this specific job) falls through to the LLM
    # on the static HTML -- never the browser.
    _patch_fetch(
        monkeypatch,
        "<html><body><p>Some role.</p></body></html>",
        "https://jobs.example.com/acme/abc-123",
    )
    from resume_agent.discovery.connectors.detect import AtsTarget

    monkeypatch.setattr(
        service, "identify_host", lambda url: AtsTarget("unregistered-ats", token="acme")
    )

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="Eng", company="Acme", jd_text="real jd")
            return _R()

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://jobs.example.com/acme/abc-123", agent=_LLM())

    assert job is not None
    assert job.jd_text == "real jd"


def test_reader_returning_none_falls_back_to_llm_not_browser(monkeypatch):
    # A registered reader that can't resolve this specific job (e.g. a
    # mismatched id) falls back to the LLM on the same static HTML; fetch_page
    # (the only browser-capable path) must never be called.
    _patch_fetch(
        monkeypatch,
        "<html><body><p>Some role.</p></body></html>",
        "https://jobs.ashbyhq.com/acme/missing-id",
    )
    monkeypatch.setattr(
        service, "fetch_page",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("browser must not be used")),
    )
    monkeypatch.setitem(service.ATS_READERS, "ashby", lambda target, url, html: None)

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="Eng", company="Acme", jd_text="real jd")
            return _R()

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://jobs.ashbyhq.com/acme/missing-id", agent=_LLM())

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

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://notlinkedin.com.evil.io/job", agent=_LLM())

    assert job is not None
    assert job.jd_text == "real jd"
