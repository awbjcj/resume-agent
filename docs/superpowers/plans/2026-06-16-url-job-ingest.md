# Add Job by URL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `resume-agent addjob --url <URL>` fetch a LinkedIn/Greenhouse/company job page and self-extract company, title, location, and JD text, then insert through the existing dedupe path.

**Architecture:** A new `discovery/url_ingest/` package fetches a page (HTTP-first, Playwright fallback), routes to a deterministic parser for known domains (LinkedIn, Greenhouse) or a cheap-model LLM extractor for unknown sites, and returns a `RawJob`. The `addjob` CLI command calls it and feeds the result to the existing `add_job()`. A standalone one-shot `fetch_rendered()` reuses the logged-in LinkedIn `user_data_dir`; `LinkedInScraper` is left untouched.

**Tech Stack:** Python 3.13, httpx, BeautifulSoup, Playwright (sync), Agno + Claude, Typer, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-16-url-job-ingest-design.md`

---

### Task 1: Package skeleton + shared models

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/__init__.py`
- Create: `src/resume_agent/discovery/url_ingest/models.py`
- Test: `tests/url_ingest/__init__.py`, `tests/url_ingest/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/__init__.py` — empty file.

`tests/url_ingest/test_models.py`:

```python
from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent


def test_extracted_job_defaults_to_empty():
    job = ExtractedJob()
    assert job.company is None
    assert job.title is None
    assert job.location is None
    assert job.jd_text == ""


def test_page_content_carries_fetch_metadata():
    page = PageContent(html="<html></html>", final_url="https://x.test", rendered=True)
    assert page.html == "<html></html>"
    assert page.final_url == "https://x.test"
    assert page.rendered is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: resume_agent.discovery.url_ingest`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/__init__.py`:

```python
"""Add a job from a URL: fetch a posting page and self-extract its fields."""
```

`src/resume_agent/discovery/url_ingest/models.py`:

```python
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class PageContent:
    """Raw page bytes plus how they were obtained."""

    html: str
    final_url: str
    rendered: bool


class ExtractedJob(BaseModel):
    """Fields pulled from a posting page; the LLM and parsers share this shape."""

    company: str | None = None
    title: str | None = None
    location: str | None = None
    jd_text: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_models.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/__init__.py src/resume_agent/discovery/url_ingest/models.py tests/url_ingest/
git commit -m "feat(url-ingest): add package skeleton and shared models"
```

---

### Task 2: LinkedIn detail-page meta parser

**Files:**

- Modify: `src/resume_agent/discovery/scraper/models.py`
- Modify: `src/resume_agent/discovery/scraper/parser.py`
- Test: `tests/test_scraper_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scraper_parser.py`:

```python
from resume_agent.discovery.scraper.parser import parse_detail_meta

_DETAIL_HTML = """
<html><body>
  <h1 class="top-card-layout__title">Staff Data Engineer</h1>
  <a class="topcard__org-name-link" href="/company/acme">Acme Corp</a>
  <span class="topcard__flavor--bullet">Berlin, Germany</span>
  <div class="show-more-less-html__markup">Build pipelines.</div>
</body></html>
"""


def test_parse_detail_meta_reads_top_card():
    meta = parse_detail_meta(_DETAIL_HTML)
    assert meta.title == "Staff Data Engineer"
    assert meta.company == "Acme Corp"
    assert meta.location == "Berlin, Germany"


def test_parse_detail_meta_missing_fields_are_none():
    meta = parse_detail_meta("<html><body></body></html>")
    assert meta.title is None
    assert meta.company is None
    assert meta.location is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_scraper_parser.py -q`
Expected: FAIL with `ImportError: cannot import name 'parse_detail_meta'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/discovery/scraper/models.py`:

```python
@dataclass
class DetailMeta:
    """Title/company/location from a LinkedIn job-detail page's top card."""

    title: str | None
    company: str | None
    location: str | None
```

In `src/resume_agent/discovery/scraper/parser.py`, change the models import and add the function. Replace:

```python
from resume_agent.discovery.scraper.models import ScrapedCard
```

with:

```python
from resume_agent.discovery.scraper.models import DetailMeta, ScrapedCard
```

Append at the end of `parser.py`:

```python
def parse_detail_meta(html: str) -> DetailMeta:
    """Read title/company/location from a LinkedIn job-detail page's top card."""
    soup = BeautifulSoup(html, "html.parser")
    return DetailMeta(
        title=_text(soup.select_one("h1.top-card-layout__title")),
        company=_text(soup.select_one("a.topcard__org-name-link")),
        location=_text(soup.select_one("span.topcard__flavor--bullet")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_scraper_parser.py -q`
Expected: PASS (all existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/scraper/models.py src/resume_agent/discovery/scraper/parser.py tests/test_scraper_parser.py
git commit -m "feat(scraper): parse title/company/location from LinkedIn detail page"
```

---

### Task 3: Greenhouse parser

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/greenhouse.py`
- Test: `tests/url_ingest/test_greenhouse.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/test_greenhouse.py`:

```python
from resume_agent.discovery.url_ingest.greenhouse import parse_greenhouse

_HTML = """
<html><body>
  <h1 class="app-title">Senior Platform Engineer</h1>
  <span class="company-name">at Globex</span>
  <div class="location">Remote - US</div>
  <div id="content">
    <p>You will own our deploy tooling.</p>
    <p>Requirements: 5 years of Go.</p>
  </div>
</body></html>
"""


def test_parse_greenhouse_extracts_all_fields():
    job = parse_greenhouse(_HTML)
    assert job.title == "Senior Platform Engineer"
    assert job.company == "Globex"
    assert job.location == "Remote - US"
    assert "deploy tooling" in job.jd_text
    assert "5 years of Go" in job.jd_text


def test_parse_greenhouse_missing_content_yields_empty_jd():
    job = parse_greenhouse("<html><body></body></html>")
    assert job.jd_text == ""
    assert job.company is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_greenhouse.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/greenhouse.py`:

```python
from bs4 import BeautifulSoup
from bs4.element import Tag

from resume_agent.discovery.url_ingest.models import ExtractedJob


def _text(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if not isinstance(node, Tag):
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def parse_greenhouse(html: str) -> ExtractedJob:
    """Parse a boards.greenhouse.io posting into structured fields."""
    soup = BeautifulSoup(html, "html.parser")
    company = _text(soup, "span.company-name")
    if company and company.lower().startswith("at "):
        company = company[3:].strip() or None
    body = soup.select_one("div#content")
    jd_text = ""
    if isinstance(body, Tag):
        lines = [ln.strip() for ln in body.get_text("\n", strip=True).splitlines()]
        jd_text = "\n".join(ln for ln in lines if ln)
    return ExtractedJob(
        title=_text(soup, "h1.app-title"),
        company=company,
        location=_text(soup, "div.location"),
        jd_text=jd_text,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_greenhouse.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/greenhouse.py tests/url_ingest/test_greenhouse.py
git commit -m "feat(url-ingest): add deterministic Greenhouse parser"
```

---

### Task 4: HTML cleaner + LLM extractor

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/llm.py`
- Test: `tests/url_ingest/test_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/test_llm.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_llm.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/llm.py`:

```python
from agno.agent import Agent
from agno.models.anthropic import Claude
from bs4 import BeautifulSoup

from resume_agent.config import get_settings
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import AgentRunner, Runner

_INSTRUCTIONS = [
    "Extract the company, job title, location, and full job-description text.",
    "Use only what the page text supports; leave unknown fields null.",
    "Put the complete responsibilities and requirements prose in jd_text.",
]


def build_url_extract_agent(model_id: str | None = None) -> Runner:
    resolved = model_id or get_settings().cheap_model
    return AgentRunner(
        Agent(
            model=Claude(id=resolved),
            description="You extract a job posting's fields from page text.",
            instructions=_INSTRUCTIONS,
            output_schema=ExtractedJob,
        )
    )


def extract_fields(text: str, agent: Runner) -> ExtractedJob:
    result = agent.run(text)
    extracted = result.content
    if not isinstance(extracted, ExtractedJob):
        raise TypeError(f"Expected ExtractedJob from agent, got {type(extracted).__name__}")
    return extracted


def html_to_text(html: str) -> str:
    """Reduce a page to readable text: drop scripts, styles, and nav chrome."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    lines = [ln.strip() for ln in soup.get_text("\n", strip=True).splitlines()]
    return "\n".join(ln for ln in lines if ln)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_llm.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/llm.py tests/url_ingest/test_llm.py
git commit -m "feat(url-ingest): add HTML cleaner and LLM field extractor"
```

---

### Task 5: One-shot rendered fetch (Playwright)

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/browser.py`
- Test: `tests/url_ingest/test_browser.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/test_browser.py`:

```python
import resume_agent.discovery.url_ingest.browser as browser


class _FakePage:
    def __init__(self):
        self.goto_url = None

    def goto(self, url, wait_until=None):
        self.goto_url = url

    def wait_for_selector(self, selector, timeout=None):
        return None

    def content(self):
        return "<html>rendered</html>"


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, context):
        self._context = context
        self.data_dir = None

    def launch_persistent_context(self, data_dir, headless=False):
        self.data_dir = data_dir
        return self._context


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_rendered_navigates_and_returns_content(monkeypatch):
    page = _FakePage()
    context = _FakeContext(page)
    chromium = _FakeChromium(context)
    monkeypatch.setattr(browser, "sync_playwright", lambda: _FakePlaywright(chromium))

    html = browser.fetch_rendered(
        "https://job.test/x", user_data_dir="/tmp/p", pace_seconds=0.0
    )

    assert html == "<html>rendered</html>"
    assert page.goto_url == "https://job.test/x"
    assert chromium.data_dir == "/tmp/p"
    assert context.closed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_browser.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/browser.py`:

```python
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings


def fetch_rendered(
    url: str,
    *,
    user_data_dir: str | None = None,
    wait_selector: str | None = None,
    headless: bool = False,
    render_timeout_ms: int = 8000,
    pace_seconds: float = 1.0,
) -> str:
    """Render one URL in the logged-in persistent browser and return its HTML.

    A one-shot lifecycle (launch, navigate, close) distinct from the scraper's
    reused session: this fetches a single page, optionally waiting for a content
    selector. Reuses the same ``user_data_dir`` so a LinkedIn login carries over.
    """
    data_dir = user_data_dir or get_settings().linkedin_user_data_dir
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(data_dir, headless=headless)
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            if wait_selector is not None:
                try:
                    page.wait_for_selector(wait_selector, timeout=render_timeout_ms)
                except PlaywrightTimeoutError:
                    pass
            time.sleep(pace_seconds)
            return page.content()
        finally:
            context.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_browser.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/browser.py tests/url_ingest/test_browser.py
git commit -m "feat(url-ingest): add one-shot rendered fetch via Playwright"
```

---

### Task 6: Fetch routing (HTTP-first, browser fallback)

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/fetch.py`
- Test: `tests/url_ingest/test_fetch.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/test_fetch.py`:

```python
import resume_agent.discovery.url_ingest.fetch as fetch


class _Resp:
    def __init__(self, text, url):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


def _patch_browser(monkeypatch, marker="<html>browser</html>"):
    calls = {}

    def fake_rendered(url, **kwargs):
        calls["url"] = url
        calls["wait_selector"] = kwargs.get("wait_selector")
        return marker

    monkeypatch.setattr(fetch, "fetch_rendered", fake_rendered)
    return calls


def test_static_page_uses_http(monkeypatch):
    body = "<html><body>" + "x " * 200 + "</body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(body, "https://boards.greenhouse.io/x")
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://boards.greenhouse.io/x")

    assert page.rendered is False
    assert "x x" in page.html
    assert browser_calls == {}


def test_linkedin_host_uses_browser(monkeypatch):
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(AssertionError("no http"))
    )
    browser_calls = _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://www.linkedin.com/jobs/view/123")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"
    assert browser_calls["url"] == "https://www.linkedin.com/jobs/view/123"


def test_js_shell_falls_back_to_browser(monkeypatch):
    shell = "<html><body><div id='root'></div></body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(shell, "https://acme.test/job")
    )
    _patch_browser(monkeypatch)

    page = fetch.fetch_page("https://acme.test/job")

    assert page.rendered is True
    assert page.html == "<html>browser</html>"


def test_no_browser_flag_skips_fallback(monkeypatch):
    shell = "<html><body></body></html>"
    monkeypatch.setattr(
        fetch.httpx, "get", lambda url, **kw: _Resp(shell, "https://acme.test/job")
    )
    monkeypatch.setattr(
        fetch, "fetch_rendered", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no browser"))
    )

    page = fetch.fetch_page("https://acme.test/job", allow_browser=False)

    assert page.rendered is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_fetch.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/fetch.py`:

```python
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from resume_agent.discovery.url_ingest.browser import fetch_rendered
from resume_agent.discovery.url_ingest.models import PageContent

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; resume-agent/1.0)"}
_LINKEDIN_DETAIL_SELECTOR = "div.show-more-less-html__markup, .description__text"
_SHELL_TEXT_THRESHOLD = 200


def _is_linkedin(host: str) -> bool:
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _looks_like_js_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    return len(body.get_text(" ", strip=True)) < _SHELL_TEXT_THRESHOLD


def fetch_page(url: str, *, allow_browser: bool = True) -> PageContent:
    """Fetch a posting page. HTTP-first; render in-browser for LinkedIn or JS shells."""
    host = urlsplit(url).netloc.lower()
    if allow_browser and _is_linkedin(host):
        html = fetch_rendered(url, wait_selector=_LINKEDIN_DETAIL_SELECTOR)
        return PageContent(html=html, final_url=url, rendered=True)
    resp = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=20.0)
    resp.raise_for_status()
    html = resp.text
    final_url = str(resp.url)
    if allow_browser and _looks_like_js_shell(html):
        rendered = fetch_rendered(url)
        return PageContent(html=rendered, final_url=final_url, rendered=True)
    return PageContent(html=html, final_url=final_url, rendered=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_fetch.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/fetch.py tests/url_ingest/test_fetch.py
git commit -m "feat(url-ingest): route fetching HTTP-first with browser fallback"
```

---

### Task 7: Service orchestrator (`job_from_url`)

**Files:**

- Create: `src/resume_agent/discovery/url_ingest/service.py`
- Test: `tests/url_ingest/test_service.py`

- [ ] **Step 1: Write the failing test**

`tests/url_ingest/test_service.py`:

```python
import resume_agent.discovery.url_ingest.service as service
from resume_agent.discovery.url_ingest.models import ExtractedJob, PageContent


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_service.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

`src/resume_agent/discovery/url_ingest/service.py`:

```python
from urllib.parse import urlsplit

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.parser import parse_detail_meta, parse_job_detail
from resume_agent.discovery.url_ingest.fetch import fetch_page
from resume_agent.discovery.url_ingest.greenhouse import parse_greenhouse
from resume_agent.discovery.url_ingest.llm import extract_fields, html_to_text
from resume_agent.discovery.url_ingest.models import ExtractedJob
from resume_agent.llm_runner import Runner


def job_from_url(url: str, *, agent: Runner, allow_browser: bool = True) -> RawJob | None:
    """Fetch a posting URL, route to the right extractor, and build a RawJob.

    Returns None when no job-description text could be extracted.
    """
    page = fetch_page(url, allow_browser=allow_browser)
    host = urlsplit(page.final_url).netloc.lower()
    if "linkedin.com" in host:
        meta = parse_detail_meta(page.html)
        extracted = ExtractedJob(
            title=meta.title,
            company=meta.company,
            location=meta.location,
            jd_text=parse_job_detail(page.html),
        )
    elif "greenhouse.io" in host:
        extracted = parse_greenhouse(page.html)
    else:
        extracted = extract_fields(html_to_text(page.html), agent)
    jd_text = (extracted.jd_text or "").strip()
    if not jd_text:
        return None
    return RawJob(
        source="url",
        url=url,
        company=extracted.company,
        title=extracted.title,
        location=extracted.location,
        jd_text=jd_text,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/url_ingest/test_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/url_ingest/service.py tests/url_ingest/test_service.py
git commit -m "feat(url-ingest): add job_from_url orchestrator with domain routing"
```

---

### Task 8: Wire `addjob --url` into the CLI

**Files:**

- Modify: `src/resume_agent/cli.py:14` (imports) and `src/resume_agent/cli.py:93-112` (`addjob`)
- Test: `tests/test_cli_addjob_url.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_addjob_url.py`:

```python
import resume_agent.cli as cli
from resume_agent.discovery.connectors.base import RawJob
from typer.testing import CliRunner

runner = CliRunner()


def _fake_job_from_url(url, *, agent, allow_browser=True):
    return RawJob(
        source="url", url=url, company="Acme", title="Engineer",
        location="Remote", jd_text="Build things.",
    )


def test_addjob_url_extracts_and_inserts(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", _fake_job_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db]
    )

    assert result.exit_code == 0, result.output
    assert "Added job" in result.output
    assert "Acme" in result.output


def test_addjob_url_flags_override_extracted(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", _fake_job_from_url)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app,
        ["addjob", "--url", "https://acme.test/job", "--company", "Globex", "--db-url", db],
    )

    assert result.exit_code == 0, result.output
    assert "Globex" in result.output


def test_addjob_url_no_extraction_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(cli, "job_from_url", lambda *a, **k: None)
    db = f"sqlite:///{tmp_path/'t.db'}"

    result = runner.invoke(
        cli.app, ["addjob", "--url", "https://acme.test/job", "--db-url", db]
    )

    assert result.exit_code == 1
    assert "Couldn't extract" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cli_addjob_url.py -q`
Expected: FAIL with `AttributeError: module 'resume_agent.cli' has no attribute 'job_from_url'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/cli.py`, add imports next to the other discovery imports (near line 14):

```python
from resume_agent.discovery.url_ingest.llm import build_url_extract_agent
from resume_agent.discovery.url_ingest.service import job_from_url
```

Replace the whole `addjob` function (lines 93-112) with:

```python
@app.command("addjob")
def addjob(
    url: str = typer.Option(None, help="Posting URL. With no JD source, the page is fetched and fields are auto-extracted."),
    company: str = typer.Option(None, help="Company name (overrides extracted)."),
    title: str = typer.Option(None, help="Job title (overrides extracted)."),
    location: str = typer.Option(None, help="Location (overrides extracted)."),
    jd_file: str = typer.Option(None, help="Read the JD from this file instead of stdin/URL."),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Force HTTP-only fetching (skip the Playwright fallback)."
    ),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Add a job: from a URL (auto-extract), a --jd-file, or JD pasted on stdin."""
    if url and not jd_file:
        raw = job_from_url(url, agent=build_url_extract_agent(), allow_browser=not no_browser)
        if raw is None:
            typer.echo("Couldn't extract a job description from that URL.")
            raise typer.Exit(code=1)
        jd_text = raw.jd_text
        company = company or raw.company
        title = title or raw.title
        location = location or raw.location
        source = "url"
        typer.echo(f"Extracted: {title or '?'} @ {company or '?'} ({location or '?'})")
    else:
        jd_text = (
            Path(jd_file).read_text(encoding="utf-8")
            if jd_file
            else typer.get_text_stream("stdin").read()
        )
        source = "manual"
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = add_job(
            session, source=source, jd_text=jd_text, url=url,
            company=company, title=title, location=location,
        )
    if job is None:
        typer.echo("Duplicate job (same URL or JD already present); not added.")
        raise typer.Exit(code=0)
    typer.echo(f"Added job #{job.id} ({company or '?'} — status={job.status}).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_cli_addjob_url.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_addjob_url.py
git commit -m "feat(cli): addjob --url fetches and auto-extracts a posting"
```

---

### Task 9: Full-suite + lint gate

**Files:** none (verification only)

- [ ] **Step 1: Run the whole test suite**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: PASS (all green, including the new `tests/url_ingest/` modules and prior suites).

- [ ] **Step 2: Lint the new and changed files**

Run: `uvx ruff check src/resume_agent/discovery/url_ingest/ src/resume_agent/cli.py src/resume_agent/discovery/scraper/`
Expected: `All checks passed!`

- [ ] **Step 3: Smoke-test the CLI help**

Run: `.venv/Scripts/python -m resume_agent.cli addjob --help`
Expected: help text shows `--url`, `--no-browser`, `--jd-file`, and override options.

- [ ] **Step 4: Commit any lint fixes (if needed)**

```bash
git add -A
git commit -m "chore(url-ingest): lint and suite fixes"
```

---

## Self-Review Notes

- **Spec coverage:** Fetch routing → Task 6; LinkedIn/Greenhouse parsers → Tasks 2/3; LLM fallback + cleaner → Task 4; one-shot browser helper → Task 5; `job_from_url` + `RawJob`/`source="url"` → Task 7; CLI `--url`/`--no-browser`/flag-override/dedupe message → Task 8; error handling (empty → None → message+exit) → Tasks 7 & 8; testing strategy → every task. Out-of-scope items (dashboard form, preview step) correctly absent.
- **Type consistency:** `ExtractedJob` (company/title/location/jd_text) and `PageContent` (html/final_url/rendered) defined in Task 1 and used unchanged in Tasks 3/4/6/7. `DetailMeta` (title/company/location) defined Task 2, consumed Task 7. `fetch_page(url, *, allow_browser)` (Task 6) called with same signature in Task 7. `job_from_url(url, *, agent, allow_browser)` (Task 7) called identically in Task 8. `fetch_rendered(...)` keyword args match between Tasks 5 and 6.
- **Placeholder scan:** none — every code step contains complete, runnable code.
