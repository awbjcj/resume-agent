# Company Careers-Page Connector (ATS detection) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recurring `companies` connector that turns a list of careers-page URLs into raw jobs by auto-detecting the ATS (Greenhouse/Lever/Ashby) and reusing the existing JSON board fetchers.

**Architecture:** A new `CompaniesConnector` implements the existing `Connector` protocol. Per configured URL it calls `detect_ats(url)` (L1 URL pattern → L2 one-GET HTML sniff), dispatches to the matching backend fetcher, collects `RawJob`s, runs the shared `relevance_gate`, and exposes `.failures`/`.filtered` so `run_pull` telemetry works unchanged. Greenhouse/Lever board fetches are lifted into shared module functions so the existing token-config connectors and the new one share one code path. Workday is detected but reported as unsupported; non-ATS pages are reported as undetectable. No browser in v1.

**Tech Stack:** Python, httpx, pydantic (`ExtensibleModel`), pytest. Spec: `docs/superpowers/specs/2026-06-17-company-careers-connector-design.md`.

---

## File Structure

- **Modify** `src/resume_agent/discovery/connectors/greenhouse.py` — add module function `fetch_greenhouse_board(token)`; make `GreenhouseConnector._get_board` delegate to it.
- **Modify** `src/resume_agent/discovery/connectors/lever.py` — add module function `fetch_lever_board(token)`; make `LeverConnector._get_board` delegate to it.
- **Create** `src/resume_agent/discovery/connectors/ashby.py` — `fetch_ashby_board(token)` + `parse_ashby(payload, company)`.
- **Create** `src/resume_agent/discovery/connectors/detect.py` — `AtsTarget` dataclass + `detect_ats(url)` (L1 + L2).
- **Create** `src/resume_agent/discovery/connectors/companies.py` — `CompaniesConnector`.
- **Modify** `src/resume_agent/discovery/connectors/config.py` — `CompaniesConfig` + field on `ConnectorsConfig`.
- **Modify** `src/resume_agent/discovery/connectors/registry.py` — register `CompaniesConnector`.
- **Modify** `config/connectors.yaml.example` — add a `companies:` section.
- **Create** `tests/fixtures/ashby/job_board.json`, `tests/test_connector_ashby.py`, `tests/test_connector_detect.py`, `tests/test_connector_companies.py`.
- **Modify** `tests/test_connector_greenhouse.py`, `tests/test_connector_lever.py`, `tests/test_connectors_config.py`, `tests/test_connectors_registry.py`.

Run the whole suite at any time with: `pytest -q`

---

## Task 1: Shared Greenhouse/Lever board fetchers

Lift the inlined httpx call into a module function each connector delegates to, so the new connector can reuse it. The existing subclass-and-override-`_get_board` tests must keep passing, so `_get_board` stays as a thin delegating method.

**Files:**
- Modify: `src/resume_agent/discovery/connectors/greenhouse.py:62-65`
- Modify: `src/resume_agent/discovery/connectors/lever.py:80-83`
- Test: `tests/test_connector_greenhouse.py`, `tests/test_connector_lever.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_connector_greenhouse.py`:

```python
def test_get_board_delegates_to_module_fetcher(monkeypatch):
    import resume_agent.discovery.connectors.greenhouse as gh

    called = {}

    def fake_fetch(token):
        called["token"] = token
        return {"jobs": []}

    monkeypatch.setattr(gh, "fetch_greenhouse_board", fake_fetch)
    conn = gh.GreenhouseConnector([GreenhouseBoard(token="acme")])
    assert conn._get_board("acme") == {"jobs": []}
    assert called["token"] == "acme"
```

Add to the end of `tests/test_connector_lever.py`:

```python
def test_get_board_delegates_to_module_fetcher(monkeypatch):
    import resume_agent.discovery.connectors.lever as lever

    called = {}

    def fake_fetch(token):
        called["token"] = token
        return []

    monkeypatch.setattr(lever, "fetch_lever_board", fake_fetch)
    conn = lever.LeverConnector([LeverBoard(token="acme")])
    assert conn._get_board("acme") == []
    assert called["token"] == "acme"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connector_greenhouse.py::test_get_board_delegates_to_module_fetcher tests/test_connector_lever.py::test_get_board_delegates_to_module_fetcher -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'fetch_greenhouse_board'`.

- [ ] **Step 3: Add the module functions and delegate**

In `src/resume_agent/discovery/connectors/greenhouse.py`, add after the `_BASE` constant (line 9):

```python
def fetch_greenhouse_board(token: str) -> dict:
    """GET a Greenhouse board's jobs payload (with content). Raises on HTTP error."""
    resp = httpx.get(f"{_BASE}/{token}/jobs", params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

Replace the body of `GreenhouseConnector._get_board` (lines 62-65) with:

```python
    def _get_board(self, token: str) -> dict:
        return fetch_greenhouse_board(token)
```

In `src/resume_agent/discovery/connectors/lever.py`, add after the `_BASE` constant (line 9):

```python
def fetch_lever_board(token: str) -> list:
    """GET a Lever board's postings array (json mode). Raises on HTTP error."""
    resp = httpx.get(f"{_BASE}/{token}", params={"mode": "json"}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

Replace the body of `LeverConnector._get_board` (lines 80-83) with:

```python
    def _get_board(self, token: str) -> list:
        return fetch_lever_board(token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_connector_greenhouse.py tests/test_connector_lever.py -v`
Expected: PASS (the new delegation tests and all existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/greenhouse.py src/resume_agent/discovery/connectors/lever.py tests/test_connector_greenhouse.py tests/test_connector_lever.py
git commit -m "refactor: extract shared greenhouse/lever board fetchers"
```

---

## Task 2: Ashby backend (`ashby.py`)

A new ATS backend: fetch a board's JSON and map it to `RawJob`s, mirroring `greenhouse.py`.

**Files:**
- Create: `src/resume_agent/discovery/connectors/ashby.py`
- Create: `tests/fixtures/ashby/job_board.json`
- Test: `tests/test_connector_ashby.py`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/ashby/job_board.json`:

```json
{
  "apiVersion": "1",
  "jobs": [
    {
      "title": "Senior ML Engineer",
      "location": "Remote - US",
      "descriptionPlain": "Build LLM systems. 5+ years of Python.",
      "descriptionHtml": "<p>Build LLM systems. 5+ years of Python.</p>",
      "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123",
      "publishedAt": "2026-06-01T00:00:00Z"
    },
    {
      "title": "Class A CDL Driver",
      "location": "Detroit, MI",
      "descriptionPlain": "Drive a truck.",
      "descriptionHtml": "<p>Drive a truck.</p>",
      "jobUrl": "https://jobs.ashbyhq.com/acme/def-456",
      "publishedAt": null
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_connector_ashby.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ashby" / "job_board.json").read_text())


def test_parse_ashby_maps_fields():
    jobs = parse_ashby(FIXTURE, company="Acme")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "ashby"
    assert first.company == "Acme"
    assert first.title == "Senior ML Engineer"
    assert first.location == "Remote - US"
    assert first.url == "https://jobs.ashbyhq.com/acme/abc-123"
    assert "Python" in first.jd_text
    assert first.posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_parse_ashby_posted_at_none_when_absent():
    jobs = parse_ashby(FIXTURE, company="Acme")
    assert jobs[1].posted_at is None


def test_parse_ashby_falls_back_to_html_description():
    payload = {"jobs": [{"title": "Eng", "jobUrl": "u", "descriptionHtml": "<p>hello</p>"}]}
    jobs = parse_ashby(payload, "Acme")
    assert jobs[0].jd_text == "hello"


def test_fetch_ashby_board_hits_posting_api(monkeypatch):
    import resume_agent.discovery.connectors.ashby as ashby

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return FIXTURE

    def fake_get(url, timeout):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(ashby.httpx, "get", fake_get)
    assert fetch_ashby_board("acme") == FIXTURE
    assert captured["url"] == "https://api.ashbyhq.com/posting-api/job-board/acme"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_connector_ashby.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.ashby'`.

- [ ] **Step 4: Write the implementation**

Create `src/resume_agent/discovery/connectors/ashby.py`:

```python
import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.text import html_to_text

_BASE = "https://api.ashbyhq.com/posting-api/job-board"


def parse_ashby(payload: dict, company: str) -> list[RawJob]:
    """Map an Ashby posting-api `jobs` payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        jd_text = item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml", ""))
        jobs.append(
            RawJob(
                source="ashby",
                url=item.get("jobUrl"),
                company=company,
                title=item.get("title"),
                location=item.get("location"),
                jd_text=jd_text,
                posted_at=parse_iso_datetime(item.get("publishedAt")),
            )
        )
    return jobs


def fetch_ashby_board(token: str) -> dict:
    """GET an Ashby job board's postings payload. Raises on HTTP error."""
    resp = httpx.get(f"{_BASE}/{token}", timeout=30)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_connector_ashby.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/connectors/ashby.py tests/test_connector_ashby.py tests/fixtures/ashby/job_board.json
git commit -m "feat: add ashby ATS backend (fetch + parse)"
```

---

## Task 3: ATS detection (`detect.py`)

Resolve a careers URL to `(ats, token)` via L1 URL pattern, then L2 one-GET HTML sniff. Pure logic plus a single injectable HTML fetch.

**Files:**
- Create: `src/resume_agent/discovery/connectors/detect.py`
- Test: `tests/test_connector_detect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_connector_detect.py`:

```python
import resume_agent.discovery.connectors.detect as detect
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats


def test_l1_greenhouse_url():
    assert detect_ats("https://boards.greenhouse.io/acme") == AtsTarget("greenhouse", "acme")


def test_l1_greenhouse_job_boards_host():
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/1") == AtsTarget("greenhouse", "acme")


def test_l1_lever_url():
    assert detect_ats("https://jobs.lever.co/acme") == AtsTarget("lever", "acme")


def test_l1_ashby_url():
    assert detect_ats("https://jobs.ashbyhq.com/acme") == AtsTarget("ashby", "acme")


def test_l1_workday_url():
    target = detect_ats("https://acme.wd1.myworkdayjobs.com/careers")
    assert target is not None and target.ats == "workday"


def test_l2_detects_embedded_greenhouse(monkeypatch):
    html = '<div id="grnhse_app"></div><script src="https://boards.greenhouse.io/embed/job_board?for=acme"></script>'
    monkeypatch.setattr(detect, "_get_html", lambda url: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("greenhouse", "acme")


def test_l2_detects_embedded_lever(monkeypatch):
    html = '<script src="https://jobs.lever.co/acme/embed"></script>'
    monkeypatch.setattr(detect, "_get_html", lambda url: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget("lever", "acme")


def test_l2_returns_none_for_unknown(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url: "<html><body>no ats here</body></html>")
    assert detect_ats("https://careers.acme.com") is None


def test_l2_fails_open_on_fetch_error(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url: None)
    assert detect_ats("https://careers.acme.com") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connector_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.detect'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/discovery/connectors/detect.py`:

```python
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

_TOKEN = r"([A-Za-z0-9_-]+)"

# L1: direct ATS URLs. (host predicate, compiled path-token pattern, ats name).
_L1_HOSTS: list[tuple[str, str]] = [
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
]

# L2: embed markers in raw HTML, checked in order. (ats name, compiled pattern).
_L2_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(rf"greenhouse\.io/embed/job_board\?for={_TOKEN}")),
    ("greenhouse", re.compile(rf"boards\.greenhouse\.io/{_TOKEN}")),
    ("lever", re.compile(rf"jobs\.lever\.co/{_TOKEN}")),
    ("ashby", re.compile(rf"jobs\.ashbyhq\.com/{_TOKEN}")),
]

_WORKDAY_HOST = re.compile(r"([a-z0-9-]+)\.[a-z0-9-]+\.myworkdayjobs\.com", re.IGNORECASE)


@dataclass(frozen=True)
class AtsTarget:
    ats: str
    token: str


def _first_path_segment(path: str) -> str | None:
    segs = [s for s in path.split("/") if s]
    return segs[0] if segs else None


def _l1(url: str) -> AtsTarget | None:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    for known_host, ats in _L1_HOSTS:
        if host == known_host:
            token = _first_path_segment(parts.path)
            return AtsTarget(ats, token) if token else None
    workday = _WORKDAY_HOST.match(host)
    if workday:
        return AtsTarget("workday", workday.group(1))
    return None


def _get_html(url: str) -> str | None:
    """Fetch a page's raw HTML for the L2 sniff. None on any error (fail-open)."""
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        return None


def _l2(url: str) -> AtsTarget | None:
    html = _get_html(url)
    if not html:
        return None
    for ats, pattern in _L2_MARKERS:
        match = pattern.search(html)
        if match:
            return AtsTarget(ats, match.group(1))
    if _WORKDAY_HOST.search(html):
        return AtsTarget("workday", _WORKDAY_HOST.search(html).group(1))
    return None


def detect_ats(url: str) -> AtsTarget | None:
    """Resolve a careers URL to an ATS target: L1 URL pattern, then L2 HTML sniff."""
    return _l1(url) or _l2(url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_connector_detect.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/detect.py tests/test_connector_detect.py
git commit -m "feat: add ATS detection (L1 url pattern + L2 html sniff)"
```

---

## Task 4: `CompaniesConfig` + example file

Add the config section that holds careers URLs. Coexists with existing sections; default-off.

**Files:**
- Modify: `src/resume_agent/discovery/connectors/config.py:44-53`
- Modify: `config/connectors.yaml.example`
- Test: `tests/test_connectors_config.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_connectors_config.py`:

```python
def test_companies_defaults_to_disabled_empty():
    cfg = ConnectorsConfig()
    assert cfg.companies.enabled is False
    assert cfg.companies.urls == []


def test_companies_loads_urls():
    cfg = ConnectorsConfig.model_validate(
        {"companies": {"enabled": True, "urls": ["https://careers.acme.com"]}}
    )
    assert cfg.companies.enabled is True
    assert cfg.companies.urls == ["https://careers.acme.com"]


def test_example_file_has_companies_section():
    cfg = load_connectors_config(Path("config/connectors.yaml.example"))
    assert cfg.companies.urls  # at least one example URL present
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connectors_config.py::test_companies_defaults_to_disabled_empty tests/test_connectors_config.py::test_companies_loads_urls tests/test_connectors_config.py::test_example_file_has_companies_section -v`
Expected: FAIL with `AttributeError: 'ConnectorsConfig' object has no attribute 'companies'`.

- [ ] **Step 3: Add the config model**

In `src/resume_agent/discovery/connectors/config.py`, add a class before `ConnectorsConfig` (after `LinkedInConfig`, line 45):

```python
class CompaniesConfig(ExtensibleModel):
    enabled: bool = False
    urls: list[str] = Field(default_factory=list)
```

Then add the field to `ConnectorsConfig` (after the `linkedin` field, line 53):

```python
    companies: CompaniesConfig = Field(default_factory=CompaniesConfig)
```

- [ ] **Step 4: Add the example section**

Append to `config/connectors.yaml.example`:

```yaml

# Company careers pages by URL. The connector auto-detects the ATS
# (Greenhouse / Lever / Ashby) and pulls all current openings. A direct
# board URL works too; Workday is recognized but not yet fetched.
companies:
  enabled: false
  urls:
    - https://jobs.ashbyhq.com/someorg
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_connectors_config.py -v`
Expected: PASS (all, including the 3 new tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/connectors/config.py config/connectors.yaml.example tests/test_connectors_config.py
git commit -m "feat: add companies connector config section"
```

---

## Task 5: `CompaniesConnector` + registry wiring

The connector itself: detect → dispatch → collect → gate, with per-URL fail isolation and `.failures`/`.filtered` telemetry. Then register it.

**Files:**
- Create: `src/resume_agent/discovery/connectors/companies.py`
- Modify: `src/resume_agent/discovery/connectors/registry.py`
- Test: `tests/test_connector_companies.py`, `tests/test_connectors_registry.py`

- [ ] **Step 1: Write the failing tests for the connector**

Create `tests/test_connector_companies.py`:

```python
import resume_agent.discovery.connectors.companies as companies
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

_GH = {
    "jobs": [
        {"title": "AI Engineer", "absolute_url": "u1", "content": "build llm systems"},
        {"title": "Class A CDL Driver", "absolute_url": "u2", "content": "drive a truck"},
    ]
}


def _patch(monkeypatch, *, detect, gh=None, lever=None, ashby=None):
    monkeypatch.setattr(companies, "detect_ats", detect)
    if gh is not None:
        monkeypatch.setattr(companies, "fetch_greenhouse_board", gh)
    if lever is not None:
        monkeypatch.setattr(companies, "fetch_lever_board", lever)
    if ashby is not None:
        monkeypatch.setattr(companies, "fetch_ashby_board", ashby)


def test_fetches_detected_greenhouse_and_gates(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("greenhouse", "acme"),
        gh=lambda token: _GH,
    )
    conn = CompaniesConnector(["https://careers.acme.com"])
    cfg = SearchConfig(role_anchors=["engineer", "ai"], exclude_terms=["driver", "cdl"])
    jobs = conn.fetch(cfg)
    assert [j.title for j in jobs] == ["AI Engineer"]
    assert conn.name == "companies"
    assert conn.filtered == 1
    assert conn.failures == {}


def test_undetectable_url_recorded_and_isolated(monkeypatch):
    def detect(url):
        return AtsTarget("greenhouse", "acme") if "acme" in url else None

    _patch(monkeypatch, detect=detect, gh=lambda token: _GH)
    conn = CompaniesConnector(["https://mystery.example", "https://careers.acme.com"])
    jobs = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert {j.title for j in jobs} == {"AI Engineer"}
    assert "https://mystery.example" in conn.failures
    assert "no known ATS" in conn.failures["https://mystery.example"]


def test_workday_recognized_but_unsupported(monkeypatch):
    _patch(monkeypatch, detect=lambda url: AtsTarget("workday", "acme"))
    conn = CompaniesConnector(["https://acme.wd1.myworkdayjobs.com/careers"])
    jobs = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert jobs == []
    reason = conn.failures["https://acme.wd1.myworkdayjobs.com/careers"]
    assert "not yet supported" in reason


def test_http_error_on_one_board_is_isolated(monkeypatch):
    import httpx

    def gh(token):
        raise httpx.HTTPStatusError(
            "404", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
        )

    _patch(monkeypatch, detect=lambda url: AtsTarget("greenhouse", "dead"), gh=gh)
    conn = CompaniesConnector(["https://careers.dead.com"])
    jobs = conn.fetch(SearchConfig(keywords=["engineer"]))
    assert jobs == []
    assert "404" in conn.failures["https://careers.dead.com"]


def test_limit_caps_results(monkeypatch):
    _patch(
        monkeypatch,
        detect=lambda url: AtsTarget("greenhouse", "acme"),
        gh=lambda token: _GH,
    )
    conn = CompaniesConnector(["https://careers.acme.com"])
    jobs = conn.fetch(SearchConfig(keywords=["a"]), limit=1)
    assert len(jobs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connector_companies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.companies'`.

- [ ] **Step 3: Write the connector**

Create `src/resume_agent/discovery/connectors/companies.py`:

```python
import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.greenhouse import fetch_greenhouse_board, parse_greenhouse
from resume_agent.discovery.connectors.lever import fetch_lever_board, parse_lever
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.search_config import SearchConfig


class CompaniesConnector:
    """Pulls openings from company careers URLs by auto-detecting their ATS.

    Each URL is isolated: an undetectable page, an unsupported ATS (Workday),
    or an HTTP error is recorded in ``failures`` and skipped so the remaining
    URLs still contribute jobs. Greenhouse/Lever/Ashby are fetched via the
    shared backend fetchers; Workday is detected but not yet fetched.
    """

    name = "companies"

    def __init__(self, urls: list[str]):
        self.urls = urls
        self.failures: dict[str, str] = {}
        self.filtered = 0

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs: list[RawJob] = []
        self.failures = {}
        self.filtered = 0
        for url in self.urls:
            target = detect_ats(url)
            if target is None:
                self.failures[url] = "no known ATS detected"
                continue
            try:
                jobs.extend(self._fetch_target(url, target))
            except httpx.HTTPError as exc:
                self.failures[url] = board_error(exc)
        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs

    def _fetch_target(self, url: str, target: AtsTarget) -> list[RawJob]:
        company = target.token
        if target.ats == "greenhouse":
            return parse_greenhouse(fetch_greenhouse_board(target.token), company)
        if target.ats == "lever":
            return parse_lever(fetch_lever_board(target.token), company)
        if target.ats == "ashby":
            return parse_ashby(fetch_ashby_board(target.token), company)
        # Recognized but no backend yet (Workday).
        self.failures[url] = f"{target.ats.title()} recognized, not yet supported"
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_connector_companies.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing registry test**

Add to the end of `tests/test_connectors_registry.py`:

```python
def test_companies_connector_built_when_enabled_with_urls():
    cfg = ConnectorsConfig.model_validate(
        {"companies": {"enabled": True, "urls": ["https://jobs.ashbyhq.com/acme"]}}
    )
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == ["companies"]


def test_companies_skipped_when_enabled_without_urls():
    cfg = ConnectorsConfig.model_validate({"companies": {"enabled": True, "urls": []}})
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == []


def test_companies_ordered_after_lever():
    cfg = ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "stripe"}]},
            "lever": {"enabled": True, "boards": [{"token": "palantir"}]},
            "companies": {"enabled": True, "urls": ["https://jobs.ashbyhq.com/acme"]},
        }
    )
    names = [c.name for c in build_connectors(cfg, _settings())]
    assert names == ["greenhouse", "lever", "companies"]
```

- [ ] **Step 6: Run registry test to verify it fails**

Run: `pytest tests/test_connectors_registry.py::test_companies_connector_built_when_enabled_with_urls -v`
Expected: FAIL — `companies` not built (no registration yet).

- [ ] **Step 7: Register the connector**

In `src/resume_agent/discovery/connectors/registry.py`, add the import after the Lever import (line 6):

```python
from resume_agent.discovery.connectors.companies import CompaniesConnector
```

Add the registration block immediately after the Lever block (after line 19, before the RemoteOK block):

```python
    if config.companies.enabled and config.companies.urls:
        connectors.append(CompaniesConnector(config.companies.urls))
```

- [ ] **Step 8: Run registry tests to verify they pass**

Run: `pytest tests/test_connectors_registry.py -v`
Expected: PASS (all, including the 3 new tests; existing order tests unaffected since companies needs its own config).

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent/discovery/connectors/companies.py src/resume_agent/discovery/connectors/registry.py tests/test_connector_companies.py tests/test_connectors_registry.py
git commit -m "feat: add companies connector with ATS auto-detection"
```

---

## Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `pytest -q`
Expected: PASS — all tests green, including every pre-existing test (no existing connector, config, or test required changes).

- [ ] **Step 2: Lint**

Run: `ruff check src/resume_agent/discovery/connectors/`
Expected: no errors.

- [ ] **Step 3: Sanity-check detection against the spec acceptance criteria**

Confirm by reading the tests that all eight acceptance criteria in the spec are covered:
1. direct GH/Lever/Ashby by pattern → `test_l1_*` (Task 3)
2. embedded Greenhouse via L2 → `test_l2_detects_embedded_greenhouse` (Task 3)
3. Workday detected, reported unsupported → `test_workday_recognized_but_unsupported` (Task 5)
4. undetectable URL isolated → `test_undetectable_url_recorded_and_isolated` (Task 5)
5. Ashby payload mapped → `test_parse_ashby_maps_fields` (Task 2)
6. shared GH/Lever fetchers → `test_get_board_delegates_to_module_fetcher` (Task 1) + connector reuse (Task 5)
7. relevance gate + telemetry fields → `test_fetches_detected_greenhouse_and_gates` (Task 5)
8. full suite green → Step 1 above

- [ ] **Step 4: Commit (only if Steps 1-2 produced fixes)**

```bash
git add -A
git commit -m "test: verify company careers connector end-to-end"
```

(If Steps 1-2 were clean with nothing to commit, skip this step.)

---

## Self-Review Notes

- **Spec coverage:** All eight acceptance criteria map to tasks (see Task 6 Step 3). The `companies:` config shape, deferral of the generic non-ATS scrape, and the shared GH/Lever fetcher are all implemented (Tasks 4, none-needed, 1 respectively).
- **Type consistency:** `AtsTarget(ats, token)` is defined in Task 3 and used identically in Task 5. `fetch_greenhouse_board`/`fetch_lever_board` defined in Task 1, `fetch_ashby_board`/`parse_ashby` in Task 2, all consumed by `CompaniesConnector._fetch_target` in Task 5. `.failures: dict[str,str]` and `.filtered: int` match the attributes `run_pull._run_note` reads.
- **Monkeypatch seam:** `CompaniesConnector` references `detect_ats` and `fetch_*_board` as module globals in `companies.py`, so tests patch `companies.detect_ats` etc. — consistent with the existing `monkeypatch.setattr(conn, "_get_board", ...)` style used in the Greenhouse/Lever tests.
