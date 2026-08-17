from resume_agent.discovery.url_ingest import service
from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent
from resume_agent.discovery.url_ingest.service import read_linkedin_posting


def _patch_fetch(monkeypatch, html, final_url):
    """Patch every fetch path: fetch_static for known-ATS/unknown-host dispatch,
    fetch_page for LinkedIn, and upgrade_if_shell for the browser upgrade a
    short static page would otherwise trigger against the real network."""
    monkeypatch.setattr(
        service, "fetch_static",
        lambda url: PageContent(html=html, final_url=final_url, rendered=False),
    )
    monkeypatch.setattr(
        service, "fetch_page",
        lambda url, allow_browser=True: PageContent(html=html, final_url=final_url, rendered=False),
    )
    monkeypatch.setattr(
        service, "upgrade_if_shell", lambda page, allow_browser=True: page
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


class _EmptyLLM:
    """The LLM ran but recovered no posting -- the documented empty-jd_text case."""

    def run(self, prompt):
        class _R:
            content = ExtractedJob(jd_text="")

        return _R()

    async def arun(self, prompt):
        return self.run(prompt)


def test_empty_jd_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, "<html><body></body></html>", "https://boards.greenhouse.io/x")

    job = service.job_from_url("https://boards.greenhouse.io/x", agent=_EmptyLLM())

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


def test_singleton_portal_may_still_be_rendered(monkeypatch):
    # careers.google.com is recognized by host but builds its listing in JS --
    # its JD lives in an AF_initDataCallback script tag that html_to_text
    # decomposes. Locking it out of the browser left the LLM nothing to read.
    shell = "<html><body><script>AF_initDataCallback({data:'...'})</script></body></html>"
    _patch_fetch(monkeypatch, shell, "https://careers.google.com/jobs/results/123")
    monkeypatch.setattr(
        service, "upgrade_if_shell",
        lambda page, allow_browser=True: PageContent(
            html="<html><body><p>Rendered JD body.</p></body></html>",
            final_url=page.final_url,
            rendered=True,
        ),
    )
    seen: list[str] = []

    class _LLM:
        def run(self, prompt):
            seen.append(prompt)

            class _R:
                content = ExtractedJob(title="SWE", company="Google", jd_text="Rendered JD body.")

            return _R()

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://careers.google.com/jobs/results/123", agent=_LLM())

    assert job is not None
    assert "Rendered JD body." in seen[0]


def test_unknown_host_is_fetched_exactly_once(monkeypatch):
    # fetch_static to route + fetch_page to read meant two outbound requests
    # against the same host, doubling the chance of tripping its bot gate.
    calls: list[str] = []

    def _static(url):
        calls.append(url)
        return PageContent(
            html="<html><body><p>Some role.</p></body></html>", final_url=url, rendered=False
        )

    monkeypatch.setattr(service, "fetch_static", _static)
    monkeypatch.setattr(service, "upgrade_if_shell", lambda page, allow_browser=True: page)
    monkeypatch.setattr(
        service, "fetch_page",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not re-fetch")),
    )

    class _LLM:
        def run(self, prompt):
            class _R:
                content = ExtractedJob(title="Lead", company="Acme", jd_text="Lead the team.")

            return _R()

        async def arun(self, prompt):
            return self.run(prompt)

    job = service.job_from_url("https://acme.test/job", agent=_LLM())

    assert job is not None
    assert calls == ["https://acme.test/job"]


def test_a_link_redirecting_to_linkedin_uses_the_linkedin_reader(monkeypatch):
    # Routing moved from page.final_url to the pasted url, so a tracking or
    # shortened link that lands on LinkedIn stopped reaching its parser.
    html = (
        '<html><body><h1 class="top-card-layout__title">SRE</h1>'
        '<a class="topcard__org-name-link">Pied Piper</a>'
        '<div class="show-more-less-html__markup">Keep it up.</div></body></html>'
    )
    monkeypatch.setattr(
        service, "fetch_static",
        lambda url: PageContent(
            html="<html></html>", final_url="https://www.linkedin.com/jobs/view/9", rendered=False
        ),
    )
    monkeypatch.setattr(
        service, "fetch_page",
        lambda url, allow_browser=True: PageContent(html=html, final_url=url, rendered=True),
    )

    job = service.job_from_url("https://tracking.example/r/abc123", agent=_Agent())

    assert job is not None
    assert job.company == "Pied Piper"
    assert "Keep it up." in job.jd_text


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


_STRIPE_SHAPED_PAGE = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"Staff Software Engineer, Link",
 "description":"<p>Body.</p>",
 "hiringOrganization":{"@type":"Organization","name":"Stripe"},
 "employmentType":"FULL_TIME",
 "jobLocation":[{"@type":"Place","address":{"@type":"PostalAddress",
   "addressLocality":"Toronto","addressCountry":"CA"}}],
 "baseSalary":{"@type":"MonetaryAmount","currency":"CAD","value":
   {"@type":"QuantitativeValue","minValue":208000,"maxValue":312000,"unitText":"YEAR"}}}
</script></head><body><p>Long enough body text to avoid the JS-shell upgrade path.</p>
</body></html>
"""


def test_unknown_host_recovers_sidebar_facts_from_json_ld(monkeypatch):
    """An employer-hosted posting (stripe.com) is not a detectable ATS, so it
    falls to the LLM -- which is told to drop site chrome and therefore loses
    the sidebar. The page's own JSON-LD restores those facts deterministically."""
    _patch_fetch(monkeypatch, _STRIPE_SHAPED_PAGE, "https://stripe.com/careers/listing/x/1")

    class _LLM:
        def run(self, prompt):
            class R:
                content = ExtractedJob(
                    company="Stripe",
                    title="Staff Software Engineer, Link",
                    location=None,
                    jd_text="Who we are\nIn-office expectations\nPay and benefits",
                )

            return R()

    job = service.job_from_url("https://stripe.com/careers/listing/x/1", agent=_LLM())

    assert job is not None
    assert "Location: Toronto, CA" in job.jd_text
    assert "Employment Type: Full time" in job.jd_text
    assert "Compensation: CAD 208,000 - 312,000 per year" in job.jd_text
    # the LLM's richer body survives -- it is not replaced by the markup blurb
    assert "In-office expectations" in job.jd_text
    assert "Pay and benefits" in job.jd_text
    # a scalar the LLM could not resolve fills from the markup
    assert job.location == "Toronto, CA"
