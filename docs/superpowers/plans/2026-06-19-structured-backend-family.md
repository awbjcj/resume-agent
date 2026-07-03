# Structured-Backend Family (Workday / Tesla / Google) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Workday, Tesla, and Google as structured (JSON-API) backends to the `companies` connector, behind a generalized detect→dispatch path — no Playwright, no LLM, no new config.

**Architecture:** `detect_ats` gains host-match singletons (Tesla/Google) and a complete Workday triple (tenant·datacenter·site); `AtsTarget` grows three optional fields rather than changing its positional `(ats, token)` shape. `CompaniesConnector` dispatches `ats → adapter(target, search, limit)` through a small table; Workday and Google shape API queries through one shared `primary_search_text(search)` helper; Workday/Tesla **list-gate before** N+1 detail fetches through one shared `listing_relevance_gate`. Tesla/Google are singleton adapters parsed against captured fixtures.

**Tech Stack:** Python, `httpx` (sync), `pytest` + `monkeypatch`, existing `RawJob`/`relevance_gate`/`html_to_text`/`parse_iso_datetime` helpers.

**Spec:** `docs/superpowers/specs/2026-06-19-structured-backend-family-design.md`

---

## File Structure

| File                                                 | Responsibility                                            | Action |
| ---------------------------------------------------- | --------------------------------------------------------- | ------ |
| `src/resume_agent/discovery/connectors/detect.py`    | `AtsTarget` descriptor; URL/host → target                 | Modify |
| `src/resume_agent/discovery/connectors/workday.py`   | Workday cxs list+detail fetch, request-shaping, list-gate | Create |
| `src/resume_agent/discovery/connectors/tesla.py`     | Tesla careers JSON singleton backend                      | Create |
| `src/resume_agent/discovery/connectors/google.py`    | Google careers JSON singleton backend                     | Create |
| `src/resume_agent/discovery/connectors/companies.py` | Dispatch table; thread `search`/`limit` to adapters       | Modify |
| `src/resume_agent/discovery/connectors/text.py`      | Shared `primary_search_text` and list-row relevance gate  | Modify |
| `tests/test_connector_detect.py`                     | Extend with Workday triple + singletons                   | Modify |
| `tests/test_connector_workday.py`                    | Workday parse/list-gate/fetch                             | Create |
| `tests/test_connector_tesla.py`                      | Tesla parse/fetch                                         | Create |
| `tests/test_connector_google.py`                     | Google parse/fetch                                        | Create |
| `tests/test_connector_companies.py`                  | Dispatch to new backends                                  | Modify |

No change to `config.py`, `registry.py`, or `connectors.yaml` — Workday/Tesla/Google URLs go in the existing `companies.urls`.

---

## Task 1: Extend `AtsTarget` with Workday triple + singleton support

**Files:**

- Modify: `src/resume_agent/discovery/connectors/detect.py:47-50`
- Test: `tests/test_connector_detect.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_connector_detect.py
def test_atstarget_backward_compatible_positional():
    # gh/lever/ashby keep the (ats, token) positional shape — existing call sites unchanged.
    assert AtsTarget("greenhouse", "acme") == AtsTarget("greenhouse", "acme")
    assert AtsTarget("greenhouse", "acme").tenant == ""


def test_atstarget_carries_workday_triple():
    t = AtsTarget("workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM")
    assert (t.tenant, t.datacenter, t.site) == ("generalmotors", "wd5", "Careers_GM")
    assert t.token == ""


def test_atstarget_singleton_needs_only_ats():
    assert AtsTarget("tesla").token == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connector_detect.py::test_atstarget_carries_workday_triple -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'tenant'`

- [ ] **Step 3: Add the fields**

```python
# detect.py — replace the AtsTarget dataclass
@dataclass(frozen=True)
class AtsTarget:
    ats: str
    token: str = ""        # board slug for greenhouse/lever/ashby
    tenant: str = ""       # workday tenant (e.g. "generalmotors")
    datacenter: str = ""   # workday data center (e.g. "wd5")
    site: str = ""         # workday site path segment (e.g. "Careers_GM")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_connector_detect.py -v`
Expected: PASS (all existing positional tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/detect.py tests/test_connector_detect.py
git commit -m "feat: extend AtsTarget with optional workday/singleton fields"
```

---

## Task 2: Detect the full Workday triple without emitting partial Workday targets

**Files:**

- Modify: `src/resume_agent/discovery/connectors/detect.py:44,70-73,91-93`
- Test: `tests/test_connector_detect.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_connector_detect.py
def test_l1_workday_captures_tenant_datacenter_site():
    assert detect_ats("https://generalmotors.wd5.myworkdayjobs.com/Careers_GM") == AtsTarget(
        "workday", tenant="generalmotors", datacenter="wd5", site="Careers_GM"
    )


def test_l1_workday_site_from_first_path_segment():
    t = detect_ats("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/jobs")
    assert t == AtsTarget(
        "workday", tenant="nvidia", datacenter="wd5", site="NVIDIAExternalCareerSite"
    )


def test_l2_workday_requires_full_url_with_site(monkeypatch):
    html = '<a href="https://acme.wd1.myworkdayjobs.com/Careers/jobs">Jobs</a>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") == AtsTarget(
        "workday", tenant="acme", datacenter="wd1", site="Careers"
    )


def test_l2_workday_bare_host_is_not_fetchable(monkeypatch):
    html = '<script src="https://acme.wd1.myworkdayjobs.com"></script>'
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: html)
    assert detect_ats("https://careers.acme.com") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_detect.py::test_l1_workday_captures_tenant_datacenter_site -v`
Expected: FAIL — current code returns `AtsTarget("workday", "nvidia")` (token-only, no triple)

- [ ] **Step 3: Capture the data center and site**

```python
# detect.py — widen the host regex to capture the data center; add a full URL regex for L2
_WORKDAY_HOST = re.compile(r"([a-z0-9-]+)\.([a-z0-9-]+)\.myworkdayjobs\.com", re.IGNORECASE)
_WORKDAY_URL = re.compile(
    r"https?://([a-z0-9-]+)\.([a-z0-9-]+)\.myworkdayjobs\.com/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
```

```python
# detect.py — add one helper so L1 and L2 cannot drift
def _workday_target(tenant: str, datacenter: str, site: str | None) -> AtsTarget | None:
    if not site:
        return None
    return AtsTarget("workday", tenant=tenant, datacenter=datacenter, site=site)


# detect.py — in _l1, replace the workday block
    workday = _WORKDAY_HOST.fullmatch(host)
    if workday:
        return _workday_target(workday.group(1), workday.group(2), _first_path_segment(parts.path))
```

```python
# detect.py — in _l2, replace the old host-only Workday sniff
    workday = _WORKDAY_URL.search(html)
    if workday:
        return _workday_target(workday.group(1), workday.group(2), workday.group(3))
    return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_detect.py -v`
Expected: PASS. Note `test_l1_workday_url` (`.../careers`) still passes — `ats == "workday"`, site `careers`. The old L2 host-only Workday sniff is intentionally gone because it produced un-fetchable `workday` targets.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/detect.py tests/test_connector_detect.py
git commit -m "feat: capture workday tenant/datacenter/site in L1 detection"
```

---

## Task 3: Host-match singletons for Tesla and Google

**Files:**

- Modify: `src/resume_agent/discovery/connectors/detect.py` (add `_singleton`, call it first in `detect_ats`)
- Test: `tests/test_connector_detect.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_connector_detect.py
def test_singleton_tesla_by_host(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)  # must not need network
    assert detect_ats("https://www.tesla.com/careers/search/?query=engineer") == AtsTarget("tesla")


def test_singleton_google_by_host(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://careers.google.com/jobs/results/") == AtsTarget("google")


def test_singleton_google_about_careers_by_host(monkeypatch):
    monkeypatch.setattr(detect, "_get_html", lambda url, client=None: None)
    assert detect_ats("https://www.google.com/about/careers/applications/jobs/results/") == AtsTarget(
        "google"
    )


def test_singleton_precedes_l2(monkeypatch):
    def fail(url, client=None):
        raise AssertionError("singleton match must not fetch HTML")
    monkeypatch.setattr(detect, "_get_html", fail)
    assert detect_ats("https://www.tesla.com/careers").ats == "tesla"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_detect.py::test_singleton_tesla_by_host -v`
Expected: FAIL — currently returns `None`

- [ ] **Step 3: Add `_singleton` and call it first**

```python
# detect.py — add near the host tables
_SINGLETON_HOSTS: list[tuple[str, str]] = [
    ("www.tesla.com", "tesla"),
    ("tesla.com", "tesla"),
    ("careers.google.com", "google"),
]


def _singleton(url: str) -> AtsTarget | None:
    """Bespoke portals identified by host alone (no token)."""
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()
    for known_host, ats in _SINGLETON_HOSTS:
        if host == known_host:
            if ats == "tesla" and not path.startswith("/careers"):
                continue
            return AtsTarget(ats)
    if host in {"google.com", "www.google.com"} and path.startswith("/about/careers"):
        return AtsTarget("google")
    return None
```

```python
# detect.py — detect_ats gains the singleton check first
def detect_ats(url: str, *, client: httpx.Client | None = None) -> AtsTarget | None:
    """Resolve a careers URL: bespoke singleton, then URL pattern, then HTML sniff."""
    return _singleton(url) or _l1(url) or _l2(url, client=client)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_detect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/detect.py tests/test_connector_detect.py
git commit -m "feat: detect tesla/google careers by host-match singleton"
```

---

## Task 4: Shared search/listing helpers + Workday list parsing

**Files:**

- Create: `src/resume_agent/discovery/connectors/workday.py`
- Modify: `src/resume_agent/discovery/connectors/text.py`
- Test: `tests/test_connector_workday.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_workday.py
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.workday import (
    cxs_jobs_url,
    list_request_body,
    parse_list_rows,
)
from resume_agent.discovery.connectors.text import primary_search_text, listing_relevance_gate
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers")

LIST_PAGE = {
    "total": 2,
    "jobPostings": [
        {"title": "Software Engineer", "externalPath": "/job/Austin/Software-Engineer_R-1",
         "locationsText": "Austin, TX", "postedOn": "Posted Today"},
        {"title": "Data Scientist", "externalPath": "/job/Remote/Data-Scientist_R-2",
         "locationsText": "Remote", "postedOn": "Posted 3 Days Ago"},
    ],
}


def test_cxs_jobs_url_is_built_from_triple():
    assert cxs_jobs_url(TARGET) == "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"


def test_list_request_body_shapes_search_text():
    body = list_request_body(SearchConfig(titles=["Software Engineer"]), offset=20)
    assert body == {"appliedFacets": {}, "limit": 20, "offset": 20, "searchText": "Software Engineer"}


def test_primary_search_text_uses_role_anchor_when_titles_absent():
    assert primary_search_text(SearchConfig(role_anchors=["Software Engineer"])) == "Software Engineer"


def test_listing_relevance_gate_can_match_location_before_detail_text():
    rows = parse_list_rows(TARGET, LIST_PAGE)
    kept = listing_relevance_gate(rows, SearchConfig(keywords=["Austin"]))
    assert [r.title for r in kept] == ["Software Engineer"]


def test_list_request_body_empty_search_text_when_no_terms():
    assert list_request_body(SearchConfig(), offset=0)["searchText"] == ""


def test_parse_list_rows_yields_partial_rawjobs():
    rows = parse_list_rows(TARGET, LIST_PAGE)
    assert [r.title for r in rows] == ["Software Engineer", "Data Scientist"]
    first = rows[0]
    assert first.source == "workday"
    assert first.company == "acme"
    assert first.location == "Austin, TX"
    assert first.url == "https://acme.wd5.myworkdayjobs.com/job/Austin/Software-Engineer_R-1"
    assert first.jd_text == ""           # detail not fetched yet
    assert first.external_path == "/job/Austin/Software-Engineer_R-1"


def test_parse_list_rows_skips_unfetchable_rows_without_external_path():
    rows = parse_list_rows(TARGET, {"jobPostings": [{"title": "No path"}]})
    assert rows == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_workday.py -v`
Expected: FAIL — `ModuleNotFoundError: workday`

- [ ] **Step 3: Implement shared helpers + parsing + body (no network yet)**

```python
# text.py — append below relevance_gate
def primary_search_text(search: SearchConfig) -> str:
    """Best single query string for APIs that accept one free-text search field."""
    candidates = [search.target_role, *search.titles, *search.role_anchors, *search.keywords]
    for term in candidates:
        if term and term.strip():
            return term.strip()
    return ""


def listing_relevance_gate(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Gate list rows before detail fetches, using title plus location as available text."""
    kept: list[RawJob] = []
    for job in jobs:
        probe_text = "\n".join(part for part in (job.jd_text, job.location) if part)
        probe = RawJob(
            source=job.source,
            url=job.url,
            company=job.company,
            title=job.title,
            location=job.location,
            jd_text=probe_text,
            posted_at=job.posted_at,
        )
        if relevance_gate([probe], search):
            kept.append(job)
    return kept
```

```python
# src/resume_agent/discovery/connectors/workday.py
from dataclasses import dataclass

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import primary_search_text
from resume_agent.discovery.search_config import SearchConfig

_PAGE = 20  # cxs page size


@dataclass
class WorkdayRow(RawJob):
    """A list-page RawJob that remembers its detail path for the N+1 fetch."""

    external_path: str = ""


def _base(target: AtsTarget) -> str:
    return f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com"


def _join_base_path(target: AtsTarget, path: str) -> str:
    return f"{_base(target)}/{path.lstrip('/')}"


def cxs_jobs_url(target: AtsTarget) -> str:
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/jobs"


def list_request_body(search: SearchConfig, offset: int) -> dict:
    return {"appliedFacets": {}, "limit": _PAGE, "offset": offset, "searchText": primary_search_text(search)}


def parse_list_rows(target: AtsTarget, page: dict) -> list[WorkdayRow]:
    rows: list[WorkdayRow] = []
    for item in page.get("jobPostings", []):
        path = item.get("externalPath") or ""
        if not path:
            continue
        rows.append(
            WorkdayRow(
                source="workday",
                url=_join_base_path(target, path),
                company=target.tenant,
                title=item.get("title"),
                location=item.get("locationsText"),
                jd_text="",
                external_path=path,
            )
        )
    return rows
```

> **Note:** `WorkdayRow` extends `RawJob` (a `@dataclass`) only to carry `external_path` between the list and detail passes; it is the same shape `ingest` already accepts.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_workday.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/text.py src/resume_agent/discovery/connectors/workday.py tests/test_connector_workday.py
git commit -m "feat: workday list parsing and cxs request body"
```

---

## Task 5: Workday detail parsing

**Files:**

- Modify: `src/resume_agent/discovery/connectors/workday.py`
- Test: `tests/test_connector_workday.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_connector_workday.py
from datetime import datetime, timezone
from resume_agent.discovery.connectors.workday import cxs_detail_url, apply_detail

DETAIL = {
    "jobPostingInfo": {
        "jobDescription": "<p>Build <b>things</b> with Python.</p>",
        "location": "Austin, TX",
        "startDate": "2026-06-01",
        "externalUrl": "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1",
    }
}


def test_cxs_detail_url_joins_site_and_path():
    assert cxs_detail_url(TARGET, "/job/Austin/Software-Engineer_R-1") == (
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/Austin/Software-Engineer_R-1"
    )


def test_cxs_detail_url_accepts_path_without_leading_slash():
    assert cxs_detail_url(TARGET, "job/Austin/Software-Engineer_R-1") == (
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/Austin/Software-Engineer_R-1"
    )


def test_apply_detail_fills_jd_url_posted_at():
    row = parse_list_rows(TARGET, LIST_PAGE)[0]
    apply_detail(row, DETAIL)
    assert "Python" in row.jd_text
    assert row.url == "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/R-1"
    assert row.posted_at == datetime(2026, 6, 1, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_workday.py::test_apply_detail_fills_jd_url_posted_at -v`
Expected: FAIL — `cxs_detail_url`/`apply_detail` undefined

- [ ] **Step 3: Implement detail helpers**

```python
# workday.py — add imports
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.text import html_to_text, primary_search_text
```

```python
# workday.py — append
def cxs_detail_url(target: AtsTarget, external_path: str) -> str:
    # external_path is usually "/job/...", but normalize defensively.
    path = external_path.strip().lstrip("/")
    if path.startswith("job/"):
        path = path[len("job/") :]
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/job/{path}"


def apply_detail(row: WorkdayRow, detail: dict) -> None:
    info = detail.get("jobPostingInfo") or {}
    row.jd_text = html_to_text(info.get("jobDescription", ""))
    if info.get("externalUrl"):
        row.url = info["externalUrl"]
    if info.get("location"):
        row.location = info["location"]
    row.posted_at = parse_iso_datetime(info.get("startDate"))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_workday.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/workday.py tests/test_connector_workday.py
git commit -m "feat: workday detail parsing (jd, url, posted_at)"
```

---

## Task 6: Workday fetch — paginate, list-gate before detail, honor limit

**Files:**

- Modify: `src/resume_agent/discovery/connectors/workday.py`
- Test: `tests/test_connector_workday.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_connector_workday.py
import resume_agent.discovery.connectors.workday as workday


class _Resp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


def test_fetch_workday_list_gates_before_detail(monkeypatch):
    """Only the title-matching row triggers a detail call (C: list-gate before N+1)."""
    detail_calls = []

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            return _Resp(LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        detail_calls.append(url)
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    search = SearchConfig(role_anchors=["Software Engineer"])
    jobs = workday.fetch_workday(TARGET, search)

    assert [j.title for j in jobs] == ["Software Engineer"]   # Data Scientist gated out
    assert len(detail_calls) == 1                              # detail fetched for survivor only
    assert "Python" in jobs[0].jd_text


def test_fetch_workday_request_is_search_shaped(monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            sent.setdefault("searchText", json["searchText"])
            return _Resp(LIST_PAGE if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    workday.fetch_workday(TARGET, SearchConfig(titles=["Software Engineer"], role_anchors=["Engineer"]))
    assert sent["searchText"] == "Software Engineer"


def test_fetch_workday_honors_limit(monkeypatch):
    page = {"total": 2, "jobPostings": LIST_PAGE["jobPostings"]}

    def fake_post(url, json, timeout):
        if url.endswith("/jobs"):
            return _Resp(page if json["offset"] == 0 else {"total": 2, "jobPostings": []})
        return _Resp(DETAIL)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    jobs = workday.fetch_workday(TARGET, SearchConfig(), limit=1)  # no anchors -> all pass gate
    assert len(jobs) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_workday.py::test_fetch_workday_list_gates_before_detail -v`
Expected: FAIL — `fetch_workday` / `workday.httpx` undefined

- [ ] **Step 3: Implement the orchestration**

```python
# workday.py — add imports at top
import httpx
from resume_agent.discovery.connectors.text import listing_relevance_gate
```

```python
# workday.py — append
_MAX_OFFSET = 1000  # safety ceiling: <=50 pages even if a tenant ignores searchText


def _list_pages(target: AtsTarget, search: SearchConfig):
    offset = 0
    while offset <= _MAX_OFFSET:
        body = list_request_body(search, offset)
        resp = httpx.post(cxs_jobs_url(target), json=body, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        postings = page.get("jobPostings") or []
        if not postings:
            return
        yield from parse_list_rows(target, page)
        total = page.get("total")
        offset += _PAGE
        if isinstance(total, int) and offset >= total:
            return


def fetch_workday(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    """List (request-shaped) -> gate on title/location -> detail-fetch survivors only."""
    survivors: list[WorkdayRow] = []
    for row in _list_pages(target, search):
        if listing_relevance_gate([row], search):  # (C) gate BEFORE spending a detail call
            survivors.append(row)
            if limit is not None and len(survivors) >= limit:
                break

    jobs: list[RawJob] = []
    for row in survivors:
        resp = httpx.post(cxs_detail_url(target, row.external_path), json={}, timeout=30)
        resp.raise_for_status()
        apply_detail(row, resp.json())
        jobs.append(row)
    return jobs
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_workday.py -v`
Expected: PASS (all Workday tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/workday.py tests/test_connector_workday.py
git commit -m "feat: workday fetch with request-shaping and list-gate-before-detail"
```

---

## Task 7: Tesla singleton backend

**Files:**

- Create: `src/resume_agent/discovery/connectors/tesla.py`
- Test: `tests/test_connector_tesla.py`

> **Build-time note:** confirm Tesla's exact careers endpoints from the browser network tab before running live. The parser below targets the documented shape (`/cua-api/apps/careers/state` listings + `/cua-api/apps/careers/job/{id}` detail); the tests pin the _parser_ against a fixture, so only the two URL constants need confirming.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_tesla.py
import resume_agent.discovery.connectors.tesla as tesla
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("tesla")
STATE = {"listings": [
    {"id": "1", "title": "Software Engineer", "department": "Software", "region": "Austin, TX"},
    {"id": "2", "title": "Welder", "department": "Manufacturing", "region": "Fremont, CA"},
]}
DETAIL = {"id": "1", "description": "<p>Build with Python.</p>",
          "url": "https://www.tesla.com/careers/search/job/1"}


def test_parse_tesla_listings_to_partial_rawjobs():
    rows = tesla.parse_listings(STATE)
    assert [r.title for r in rows] == ["Software Engineer", "Welder"]
    assert rows[0].source == "tesla"
    assert rows[0].company == "Tesla"
    assert rows[0].location == "Austin, TX"
    assert rows[0].listing_id == "1"
    assert rows[0].jd_text == ""


def test_fetch_tesla_gates_then_details(monkeypatch):
    detail_calls = []

    class _Resp:
        def __init__(self, p): self._p = p
        def raise_for_status(self): pass
        def json(self): return self._p

    def fake_get(url, timeout):
        if "state" in url:
            return _Resp(STATE)
        detail_calls.append(url)
        return _Resp(DETAIL)

    monkeypatch.setattr(tesla.httpx, "get", fake_get)
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(role_anchors=["Software Engineer"]))
    assert [j.title for j in jobs] == ["Software Engineer"]
    assert len(detail_calls) == 1
    assert "Python" in jobs[0].jd_text
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_tesla.py -v`
Expected: FAIL — `ModuleNotFoundError: tesla`

- [ ] **Step 3: Implement**

```python
# src/resume_agent/discovery/connectors/tesla.py
from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_text, listing_relevance_gate
from resume_agent.discovery.search_config import SearchConfig

_STATE_URL = "https://www.tesla.com/cua-api/apps/careers/state"          # confirm at build time
_JOB_URL = "https://www.tesla.com/cua-api/apps/careers/job/{id}"        # confirm at build time


@dataclass
class TeslaRow(RawJob):
    listing_id: str = ""


def parse_listings(state: dict) -> list[TeslaRow]:
    rows: list[TeslaRow] = []
    for item in state.get("listings", []):
        rows.append(
            TeslaRow(
                source="tesla",
                url=None,
                company="Tesla",
                title=item.get("title"),
                location=item.get("region"),
                jd_text="",
                listing_id=str(item.get("id") or ""),
            )
        )
    return rows


def fetch_tesla(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    resp = httpx.get(_STATE_URL, timeout=30)
    resp.raise_for_status()
    survivors: list[TeslaRow] = []
    for row in parse_listings(resp.json()):
        if listing_relevance_gate([row], search):
            survivors.append(row)
            if limit is not None and len(survivors) >= limit:
                break

    jobs: list[RawJob] = []
    for row in survivors:
        d = httpx.get(_JOB_URL.format(id=row.listing_id), timeout=30)
        d.raise_for_status()
        info = d.json()
        row.jd_text = html_to_text(info.get("description", ""))
        row.url = info.get("url") or row.url
        jobs.append(row)
    return jobs
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_tesla.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/tesla.py tests/test_connector_tesla.py
git commit -m "feat: tesla careers singleton backend (parser fixture-tested)"
```

---

## Task 8: Google singleton backend

**Files:**

- Create: `src/resume_agent/discovery/connectors/google.py`
- Test: `tests/test_connector_google.py`

> **Build-time note:** confirm Google's careers search endpoint (`careers.google.com/api/v3/search/`) and response keys from the network tab; the parser is fixture-pinned, so only the URL/keys may need adjustment.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_connector_google.py
import resume_agent.discovery.connectors.google as google
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.search_config import SearchConfig

TARGET = AtsTarget("google")
PAGE = {"count": 1, "jobs": [{
    "title": "Software Engineer",
    "locations": [{"display": "Mountain View, CA"}],
    "description": "<p>Build with Go.</p>",
    "apply_url": "https://careers.google.com/jobs/results/1/",
    "publish_date": "2026-06-01",
}]}


def test_parse_google_jobs():
    jobs = google.parse_jobs(PAGE)
    j = jobs[0]
    assert j.source == "google"
    assert j.company == "Google"
    assert j.title == "Software Engineer"
    assert j.location == "Mountain View, CA"
    assert "Go" in j.jd_text
    assert j.url == "https://careers.google.com/jobs/results/1/"


def test_fetch_google_is_search_shaped(monkeypatch):
    sent = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return PAGE if sent.setdefault("page", 0) == 0 else {"jobs": []}

    def fake_get(url, params, timeout):
        sent["q"] = params.get("q")
        sent["page"] = sent.get("page", -1) + 1
        return _Resp()

    monkeypatch.setattr(google.httpx, "get", fake_get)
    jobs = google.fetch_google(TARGET, SearchConfig(titles=["Software Engineer"]))
    assert sent["q"] == "Software Engineer"
    assert [j.title for j in jobs] == ["Software Engineer"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_google.py -v`
Expected: FAIL — `ModuleNotFoundError: google`

- [ ] **Step 3: Implement**

```python
# src/resume_agent/discovery/connectors/google.py
import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_text, primary_search_text
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://careers.google.com/api/v3/search/"   # confirm at build time
_MAX_PAGES = 20


def parse_jobs(page: dict) -> list[RawJob]:
    jobs: list[RawJob] = []
    for item in page.get("jobs", []):
        locations = item.get("locations") or []
        location = locations[0].get("display") if locations else None
        jobs.append(
            RawJob(
                source="google",
                url=item.get("apply_url"),
                company="Google",
                title=item.get("title"),
                location=location,
                jd_text=html_to_text(item.get("description", "")),
                posted_at=parse_iso_datetime(item.get("publish_date")),
            )
        )
    return jobs


def fetch_google(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    jobs: list[RawJob] = []
    for page_num in range(1, _MAX_PAGES + 1):
        resp = httpx.get(_SEARCH_URL, params={"q": primary_search_text(search), "page": page_num}, timeout=30)
        resp.raise_for_status()
        batch = parse_jobs(resp.json())
        if not batch:
            break
        jobs.extend(batch)
        if limit is not None and len(jobs) >= limit:
            return jobs[:limit]
    return jobs
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_connector_google.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/google.py tests/test_connector_google.py
git commit -m "feat: google careers singleton backend (search-shaped, fixture-tested)"
```

---

## Task 9: Wire the dispatch table in `CompaniesConnector`

**Files:**

- Modify: `src/resume_agent/discovery/connectors/companies.py`
- Test: `tests/test_connector_companies.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_connector_companies.py
from resume_agent.discovery.search_config import SearchConfig
import resume_agent.discovery.connectors.companies as companies


def test_companies_dispatches_workday(monkeypatch):
    calls = {}

    def fake_workday(target, search, limit=None):
        calls["target"] = target
        from resume_agent.discovery.connectors.base import RawJob
        return [RawJob("workday", "u", "acme", "Software Engineer", "Austin", "jd")]

    monkeypatch.setitem(companies._BACKENDS, "workday", fake_workday)
    monkeypatch.setattr(
        companies, "detect_ats",
        lambda url: companies.AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers"),
    )
    conn = companies.CompaniesConnector(["https://acme.wd5.myworkdayjobs.com/Careers"])
    jobs = conn.fetch(SearchConfig())
    assert calls["target"].tenant == "acme"
    assert [j.source for j in jobs] == ["workday"]


def test_companies_unsupported_ats_recorded(monkeypatch):
    monkeypatch.setattr(companies, "detect_ats", lambda url: companies.AtsTarget("smartrecruiters", "x"))
    conn = companies.CompaniesConnector(["https://careers.x.com"])
    conn.fetch(SearchConfig())
    assert "https://careers.x.com" in conn.failures
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_connector_companies.py::test_companies_dispatches_workday -v`
Expected: FAIL — `companies` has no `fetch_workday` / dispatch

- [ ] **Step 3: Replace the dispatch with a table that threads `search`/`limit`**

```python
# companies.py — replace the whole file body below the imports
import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.google import fetch_google
from resume_agent.discovery.connectors.greenhouse import fetch_greenhouse_board, parse_greenhouse
from resume_agent.discovery.connectors.lever import fetch_lever_board, parse_lever
from resume_agent.discovery.connectors.tesla import fetch_tesla
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.connectors.workday import fetch_workday
from resume_agent.discovery.search_config import SearchConfig


def _greenhouse(target, search, limit=None):
    return parse_greenhouse(fetch_greenhouse_board(target.token), target.token)


def _lever(target, search, limit=None):
    return parse_lever(fetch_lever_board(target.token), target.token)


def _ashby(target, search, limit=None):
    return parse_ashby(fetch_ashby_board(target.token), target.token)


# ats -> adapter(target, search, limit) -> RawJob[]
_BACKENDS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workday": fetch_workday,
    "tesla": fetch_tesla,
    "google": fetch_google,
}


class CompaniesConnector:
    """Pull openings from company careers URLs by auto-detecting their ATS."""

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
            backend = _BACKENDS.get(target.ats)
            if backend is None:
                self.failures[url] = f"{target.ats.title()} recognized, not yet supported"
                continue
            try:
                jobs.extend(backend(target, search, limit))
            except httpx.HTTPError as exc:
                self.failures[url] = board_error(exc)

        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs
```

- [ ] **Step 4: Run the full connector suite**

Run: `pytest tests/test_connector_companies.py tests/test_connector_workday.py tests/test_connector_tesla.py tests/test_connector_google.py tests/test_connector_detect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/companies.py tests/test_connector_companies.py
git commit -m "feat: dispatch companies connector to workday/tesla/google backends"
```

---

## Task 10: Full-suite regression + lint

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS, no regressions in existing connector/detect/companies tests.

- [ ] **Step 2: Lint**

Run: `ruff check src/resume_agent/discovery/connectors`
Expected: clean (fix any unused-import orphans introduced by the dispatch rewrite).

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A && git commit -m "chore: lint structured-backend family"
```

---

## Self-Review

- **Spec coverage:** AC1 → Task 2; AC2 → Task 3; AC3 → Task 9 (`_greenhouse`/`_lever`/`_ashby` call shared `fetch_*_board`); AC4 → Tasks 4-6; AC5 → Tasks 7-8; AC6 → Task 9 (`failures` for undetected/unsupported); AC7 → Task 9 (`relevance_gate` + `.filtered` unchanged) and Task 10; AC8 → Task 10 + "no config change" (no Task touches `config.py`/`registry.py`).
- **Placeholder scan:** none — every step carries runnable code; Tesla/Google URL constants are flagged build-time-confirm, not TBD, and their parsers are fully tested against fixtures.
- **Type consistency:** `AtsTarget(ats, token="", tenant="", datacenter="", site="")` used consistently; adapter signature `(target, search, limit=None) -> list[RawJob]` matches `_BACKENDS` and `fetch_workday`/`fetch_tesla`/`fetch_google`; `WorkdayRow`/`TeslaRow` extend `RawJob` so `ingest` accepts them unchanged.
- **Architecture (deletion test):** `_BACKENDS` is a small dispatch table with 6 adapters; deleting it scatters ATS dispatch back into `if/elif` across the connector. `workday.py` keeps list/detail/orchestration local to one file (locality).
