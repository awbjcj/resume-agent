# ATS Backend Expansion + Server-Side Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add seven clean-API ATS backends (auto-detected via `companies.urls`) and push a coarse search-term + location filter server-side where an ATS supports it — with the local `relevance_gate` remaining the authoritative filter.

**Architecture:** Each backend follows the established recipe: detection in `detect.py` (host/path → `AtsTarget`), a `fetch_<name>(target, search, limit, skip_seen=None) -> list[RawJob]` module, and a thin adapter registered in `companies._BACKENDS`. N+1 backends (list → detail) reuse `harvest_detailed`; single-request backends map their whole payload and let `harvest`'s gate cap it. Server-side filters are best-effort query shaping (`primary_search_term`, new `primary_location`); an unsupported field is omitted, never fatal.

**Tech Stack:** Python 3, httpx, BeautifulSoup/markdownify, pytest. Offline suite — every backend is tested against a **captured real fixture**, never a live call.

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline). Lint: `ruff check`.
- **Depends on the skip-known plan** (`2026-07-01-skip-known-pull.md`): every new
  `fetch_<name>` takes `skip_seen=None` and forwards it to `harvest_detailed`. If that
  plan is not yet merged, drop the `skip_seen` parameter from the new backends and add
  it when it lands.
- **Fixture-first, no fabrication:** before writing a parser, capture one real payload
  from the live endpoint into `tests/fixtures/<name>_*.json` (or `.xml`) and commit it.
  The parser is written against that captured shape. Field names in this plan are the
  best-known shape and MUST be verified against the capture.
- Onboarding is URL-only: detection in `detect.py` + a `_BACKENDS` entry. **No new
  config sections.**
- Server-side filter push is coarse and best-effort; the local `relevance_gate` stays
  authoritative (the kept set after a pull is unchanged — only fetched volume shrinks).
- Reverse-engineered endpoints (Breezy, JazzHR, BambooHR) inherit the Tesla/Google
  caveat: a parse failure isolates to its URL via `_failure_reason`, never aborting the
  pull.
- Build order: SmartRecruiters + Workable first (they also carry Thread B), then
  Recruitee + Personio, then Breezy + JazzHR + BambooHR.

## Review corrections (2026-07-01)

This section supersedes conflicting endpoint shapes and code snippets below. The
original plan was written before its research steps were performed; implementation
must follow the captured payloads and these verified contracts instead.

- The existing text test module is `tests/test_connectors_text.py` (plural), not
  `tests/test_connector_text.py`.
- Workable's public endpoint is `GET /api/accounts/{account}?details=true`; its
  array is `jobs`, and location fields are flat (`city`, `state`, `country`) with
  an optional `locations` array. Detect `apply.workable.com/{account}` and legacy
  `{account}.workable.com`; never interpret `apply.workable.com/j/{shortcode}` as
  an account token because that URL does not contain one.
- SmartRecruiters supports `q`, `country`, `region`, and `city`, not a generic
  `location` parameter. Push only `q`: `SearchConfig.locations` contains free-form
  strings and cannot be losslessly mapped to those structured facets.
- Breezy's `/json` list does not contain a description. Treat Breezy as N+1:
  parse list cards, then fetch each card URL and extract the `JobPosting` JSON-LD
  before the full relevance gate. This also makes `skip_seen` useful before the
  detail request.
- JazzHR's proposed `/api/v1/jobs` and RSS endpoints return 404. Use the public
  `/apply/jobs` HTML listing plus `/apply/jobs/details/{id}` detail pages, parsed
  deterministically with BeautifulSoup/JSON-LD and fixture-tested. This remains
  pure HTTP with no browser or LLM, and `skip_seen` runs before detail fetches.
- BambooHR's verified detail payload is nested at
  `result.jobOpening.description`; its canonical URL is
  `result.jobOpening.jobOpeningShareUrl`.
- Personio must use BeautifulSoup's `xml` parser, preserve the HTML stored in
  each `<value>` element before passing it to `html_to_markdown`, and use
  `<subcompany>` as the display company when present.
- Recruitee descriptions and titles may be localized under `translations`; use
  the top-level fields first and fall back to the first translation.
- Server-side narrowing is an efficiency heuristic and cannot mathematically
  guarantee an identical fetched set when a third-party search engine has
  different synonym semantics. The local gate remains authoritative over every
  row returned by the server; no connector may bypass it.
- Each backend task needs a fetch-level test (mocked HTTP) in addition to parser
  and detection tests, proving the fixture shape is actually wired through the
  public connector seam and that N+1 backends skip detail calls when requested.

---

### Task 0: `primary_location` filter helper

**Files:**
- Modify: `src/resume_agent/discovery/connectors/text.py`
- Test: `tests/test_connector_text.py` (extend, or create if absent)

**Interfaces:**
- Produces: `primary_location(search: SearchConfig) -> str` — the first non-empty
  configured location, `""` when none. Mirrors `primary_search_term`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connector_text.py  (append)
from resume_agent.discovery.connectors.text import primary_location
from resume_agent.discovery.search_config import SearchConfig


def test_primary_location_returns_first_nonempty():
    assert primary_location(SearchConfig(locations=["  Austin, TX ", "Remote"])) == "Austin, TX"


def test_primary_location_empty_when_unset():
    assert primary_location(SearchConfig()) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_text.py -k primary_location -v`
Expected: FAIL — `ImportError: cannot import name 'primary_location'`.

- [ ] **Step 3: Implement `primary_location`** (add directly below `primary_search_term` in `text.py`)

```python
def primary_location(search: SearchConfig) -> str:
    """First non-empty configured location, for a backend's server-side location filter.

    Coarse best-effort: an empty string means 'send no location param'. The local
    relevance gate remains authoritative regardless of what the server filters.
    """
    for location in search.locations:
        if location.strip():
            return location.strip()
    return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_text.py -k primary_location -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/text.py tests/test_connector_text.py
git commit -m "feat: add primary_location helper for server-side location push"
```

---

### Task 1: SmartRecruiters backend (N+1, server-side `q`) + detection + register

**Files:**
- Create: `src/resume_agent/discovery/connectors/smartrecruiters.py`
- Create: `tests/fixtures/smartrecruiters_list.json`, `tests/fixtures/smartrecruiters_detail.json`
- Modify: `src/resume_agent/discovery/connectors/detect.py`
- Modify: `src/resume_agent/discovery/connectors/companies.py`
- Test: `tests/test_connector_smartrecruiters.py`, extend `tests/test_connector_detect.py`

**Interfaces:**
- Consumes: `AtsTarget` (token = SmartRecruiters companyId), `harvest_detailed`,
  `html_to_markdown`, `primary_search_term`, `parse_iso_datetime`.
- Produces:
  - `postings_url(company) -> str`, `list_params(search, offset) -> dict`
  - `parse_postings(payload, company) -> list[SmartRecruitersRow]`
  - `detail_url(company, posting_id) -> str`, `apply_detail(row, detail) -> None`
  - `fetch_smartrecruiters(target, search, limit=None, skip_seen=None) -> list[RawJob]`
  - detection: `jobs.smartrecruiters.com/{company}` → `AtsTarget("smartrecruiters", "{company}")`

- [ ] **Step 1: Capture fixtures** (one-time, live; commit the JSON)

Run (replace `Bosch` with any real SmartRecruiters company):
```bash
curl -s "https://api.smartrecruiters.com/v1/companies/Bosch/postings?limit=2" > tests/fixtures/smartrecruiters_list.json
POSTING_ID=$(python -c "import json;print(json.load(open('tests/fixtures/smartrecruiters_list.json'))['content'][0]['id'])")
curl -s "https://api.smartrecruiters.com/v1/companies/Bosch/postings/$POSTING_ID" > tests/fixtures/smartrecruiters_detail.json
```
Open both files and confirm the field paths used in Step 3 (`content[].id/name/location`,
`jobAd.sections.*.text`, `applyUrl`). Adjust Step 3 to match reality if they differ.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_connector_smartrecruiters.py
import json
from pathlib import Path

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.smartrecruiters import (
    apply_detail,
    list_params,
    parse_postings,
    postings_url,
)
from resume_agent.discovery.search_config import SearchConfig

FIX = Path(__file__).parent / "fixtures"


def test_postings_url_from_company():
    assert postings_url("Acme") == "https://api.smartrecruiters.com/v1/companies/Acme/postings"


def test_list_params_pushes_search_term():
    params = list_params(SearchConfig(titles=["Software Engineer"]), offset=0)
    assert params["q"] == "Software Engineer"
    assert params["limit"] == 100 and params["offset"] == 0


def test_list_params_omits_q_when_no_term():
    assert "q" not in list_params(SearchConfig(), offset=0)


def test_parse_postings_maps_rows():
    payload = json.loads((FIX / "smartrecruiters_list.json").read_text(encoding="utf-8"))
    rows = parse_postings(payload, "Acme")
    assert rows and rows[0].title and rows[0].source == "smartrecruiters"
    assert rows[0].posting_id  # carried for the N+1 detail fetch


def test_apply_detail_fills_markdown_jd():
    payload = json.loads((FIX / "smartrecruiters_list.json").read_text(encoding="utf-8"))
    detail = json.loads((FIX / "smartrecruiters_detail.json").read_text(encoding="utf-8"))
    row = parse_postings(payload, "Acme")[0]
    apply_detail(row, detail)
    assert row.jd_text.strip()  # sections stitched into JD text
```

Plus detection, in `tests/test_connector_detect.py`:
```python
def test_l1_smartrecruiters_url():
    assert detect_ats("https://jobs.smartrecruiters.com/Acme") == AtsTarget(
        "smartrecruiters", "Acme"
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_smartrecruiters.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement the backend**

```python
# src/resume_agent/discovery/connectors/smartrecruiters.py
from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown, primary_search_term
from resume_agent.discovery.search_config import SearchConfig

_API = "https://api.smartrecruiters.com/v1/companies"
_PAGE = 100  # SmartRecruiters postings API max page size
_MAX_OFFSET = 1000  # safety ceiling, mirrors Workday


@dataclass
class SmartRecruitersRow(RawJob):
    posting_id: str = ""


def postings_url(company: str) -> str:
    return f"{_API}/{company}/postings"


def detail_url(company: str, posting_id: str) -> str:
    return f"{_API}/{company}/postings/{posting_id}"


def list_params(search: SearchConfig, offset: int) -> dict:
    params: dict[str, str | int] = {"limit": _PAGE, "offset": offset}
    term = primary_search_term(search)
    if term:
        params["q"] = term  # coarse server-side narrow; local gate stays authoritative
    return params


def _location_text(location: dict | None) -> str | None:
    if not location:
        return None
    parts = [location.get("city"), location.get("region"), location.get("country")]
    text = ", ".join(part for part in parts if part)
    return text or None


def parse_postings(payload: dict, company: str) -> list[SmartRecruitersRow]:
    rows: list[SmartRecruitersRow] = []
    for item in payload.get("content", []):
        posting_id = item.get("id") or ""
        rows.append(
            SmartRecruitersRow(
                source="smartrecruiters",
                url=f"https://jobs.smartrecruiters.com/{company}/{posting_id}" if posting_id else None,
                company=(item.get("company") or {}).get("name") or company,
                title=item.get("name"),
                location=_location_text(item.get("location")),
                jd_text="",
                posted_at=parse_iso_datetime(item.get("releasedDate")),
                posting_id=posting_id,
            )
        )
    return rows


def apply_detail(row: SmartRecruitersRow, detail: dict) -> None:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    ordered = ["companyDescription", "jobDescription", "qualifications", "additionalInformation"]
    html_parts = [(sections.get(name) or {}).get("text") or "" for name in ordered]
    row.jd_text = html_to_markdown("\n".join(part for part in html_parts if part))
    if detail.get("applyUrl"):
        row.url = detail["applyUrl"]
    elif detail.get("postingUrl"):
        row.url = detail["postingUrl"]


def _list_pages(target: AtsTarget, search: SearchConfig):
    offset = 0
    while offset <= _MAX_OFFSET:
        resp = httpx.get(postings_url(target.token), params=list_params(search, offset), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        rows = parse_postings(payload, target.token)
        if not rows:
            return
        yield from rows
        offset += _PAGE
        total = payload.get("totalFound")
        if isinstance(total, int) and offset >= total:
            return


def _fetch_detail(target: AtsTarget, row: SmartRecruitersRow) -> dict | None:
    if not row.posting_id:
        return None
    resp = httpx.get(detail_url(target.token, row.posting_id), timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_smartrecruiters(
    target: AtsTarget, search: SearchConfig, limit: int | None = None, skip_seen=None
) -> list[RawJob]:
    """List (q-narrowed) -> gate on title -> detail-fetch survivors only."""
    return harvest_detailed(
        _list_pages(target, search),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
```

- [ ] **Step 5: Add detection** — in `detect.py`, extend `_L1_HOSTS`:

```python
_L1_HOSTS: list[tuple[str, str]] = [
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
    ("careers.smartrecruiters.com", "smartrecruiters"),
]
```

And an L2 marker (for SmartRecruiters embedded on a custom careers domain) in `_L2_MARKERS`:
```python
    (
        "smartrecruiters",
        re.compile(rf"smartrecruiters\.com/{_TOKEN}(?=$|[/?#\"'<>\s])", re.IGNORECASE),
    ),
```

- [ ] **Step 6: Register the adapter** — in `companies.py`, add the import, adapter, and `_BACKENDS` entry:

```python
from resume_agent.discovery.connectors.smartrecruiters import fetch_smartrecruiters


def _smartrecruiters(target, search, limit=None, skip_seen=None):
    return fetch_smartrecruiters(target, search, limit, skip_seen=skip_seen)
```
```python
_BACKENDS = {
    ...
    "smartrecruiters": _smartrecruiters,
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_smartrecruiters.py tests/test_connector_detect.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/discovery/connectors/smartrecruiters.py tests/fixtures/smartrecruiters_*.json tests/test_connector_smartrecruiters.py src/resume_agent/discovery/connectors/detect.py src/resume_agent/discovery/connectors/companies.py tests/test_connector_detect.py
git commit -m "feat: add SmartRecruiters backend with server-side q narrowing"
```

---

### Tasks 2, 3, 5, 6, 7: Reverse-engineered backends (capture-first recipe)

Each of these five backends follows the **same five-step recipe** as SmartRecruiters
(capture → failing test → implement parser+fetch → detect → register → commit). They
are grouped because the *shape* is identical; only the endpoint, host pattern, and JSON
field mapping differ. Do them one at a time, each a standalone commit.

**Per-backend recipe (apply to each row below):**

1. **Capture** one real payload into `tests/fixtures/<name>_list.json` (and
   `<name>_detail.json` if the JD needs a second call). Commit the fixture. Confirm the
   field names before coding — the mappings below are best-known, not guaranteed.
2. **Failing test** `tests/test_connector_<name>.py`: load the fixture, assert
   `parse_<name>(payload, company)` yields rows with `source`, `title`, non-empty
   `jd_text` (single-request) or `apply_detail` filling it (N+1). Add a detection test
   to `tests/test_connector_detect.py`.
3. **Implement** `src/resume_agent/discovery/connectors/<name>.py` mirroring
   Greenhouse (single-request: `fetch_<name>_board` + `parse_<name>`) or SmartRecruiters
   (N+1: `_list_pages`/`_fetch_detail`/`apply_detail`). Run JD HTML through
   `html_to_markdown`. Signature: `fetch_<name>(target, search, limit=None, skip_seen=None)`.
4. **Detect + register**: add the host to `_L1_HOSTS` (token = first path segment) and,
   if the ATS embeds on custom domains, an `_L2_MARKERS` entry; add the adapter to
   `companies._BACKENDS`.
5. **Test + commit**: `pytest tests/test_connector_<name>.py tests/test_connector_detect.py`,
   then commit backend + fixture + detect + companies + tests together.

| Task | Backend | Detect host → token | Endpoint (verify live) | Shape | JD source (best-known) |
| --- | --- | --- | --- | --- | --- |
| 2 | **workable** | `apply.workable.com/j/{token}`, `{token}.workable.com` | `GET https://www.workable.com/api/accounts/{token}?details=true` | single-request | `results[].description` (HTML); title `results[].title`, url `results[].url`/`application_url`, location `results[].location.city/country` |
| 3 | **recruitee** | `{token}.recruitee.com` | `GET https://{token}.recruitee.com/api/offers/` | single-request | `offers[].description` (HTML); title `offers[].title`, url `offers[].careers_url`/`careers_apply_url`, location `offers[].city`/`country_code` |
| 5 | **breezy** | `{token}.breezy.hr` | `GET https://{token}.breezy.hr/json` | single-request (array) | `[].description` (HTML); title `[].name`, url `[].url`, location `[].location.name` (reverse-engineered — isolate parse failures) |
| 6 | **jazzhr** | `{token}.applytojob.com` | `GET https://{token}.applytojob.com/api/v1/jobs` (or the board's JSON/RSS feed — confirm) | single-request | `jobs[].description`; title `jobs[].title`, url `jobs[].url`, location `jobs[].city`,`jobs[].state` (reverse-engineered) |
| 7 | **bamboohr** | `{token}.bamboohr.com` | `GET https://{token}.bamboohr.com/careers/list` then detail `GET .../careers/{id}/detail` | N+1 | list `result[].jobOpeningName`/`location`; detail `.description` (HTML) (reverse-engineered) |

For Workable and Recruitee (Task 2, 3), also push a server-side location filter where
the endpoint supports it (Workable `details=true` widget filters minimally — if there is
no cheap param, omit it per the best-effort rule and rely on the local gate).

Example detection test to add per backend (adjust host/token):
```python
def test_l1_recruitee_url():
    assert detect_ats("https://acme.recruitee.com/o/backend-engineer") == AtsTarget(
        "recruitee", "acme"
    )
```

> Note: for `{token}.workable.com` / `{token}.recruitee.com` / `{token}.breezy.hr` /
> `{token}.applytojob.com` / `{token}.bamboohr.com`, the token is the **subdomain**, not
> a path segment. Add these to a new subdomain-detection branch in `detect.py` (a small
> regex table `_SUBDOMAIN_HOSTS: list[tuple[re.Pattern, str]]` mapping
> `^(?P<token>[a-z0-9-]+)\.recruitee\.com$` → `"recruitee"`), checked in `_l1` after the
> exact-host table and before the Workday fallback. Write one detection test per host.

---

### Task 4: Personio backend (single-request XML feed) — fully specified

**Files:**
- Create: `src/resume_agent/discovery/connectors/personio.py`
- Create: `tests/fixtures/personio_feed.xml`
- Modify: `detect.py`, `companies.py`
- Test: `tests/test_connector_personio.py`, extend `tests/test_connector_detect.py`

**Interfaces:**
- Produces: `feed_url(token) -> str`, `parse_personio(xml_text, company) -> list[RawJob]`,
  `fetch_personio(target, search, limit=None, skip_seen=None) -> list[RawJob]`.
- Detection: `{token}.jobs.personio.com` and `{token}.jobs.personio.de` → subdomain token.

- [ ] **Step 1: Capture the feed**

```bash
curl -s "https://<company>.jobs.personio.com/xml" > tests/fixtures/personio_feed.xml
```
Confirm the element names (`position`, `name`, `office`, `jobDescriptions/jobDescription/value`).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_connector_personio.py
from pathlib import Path

from resume_agent.discovery.connectors.personio import parse_personio, feed_url

FIX = Path(__file__).parent / "fixtures"


def test_feed_url_from_token():
    assert feed_url("acme") == "https://acme.jobs.personio.com/xml"


def test_parse_personio_maps_positions():
    xml_text = (FIX / "personio_feed.xml").read_text(encoding="utf-8")
    jobs = parse_personio(xml_text, "Acme")
    assert jobs and jobs[0].source == "personio"
    assert jobs[0].title and jobs[0].jd_text.strip()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_personio.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement** (Personio's XML feed is stable; parse with BeautifulSoup's XML mode)

```python
# src/resume_agent/discovery/connectors/personio.py
from bs4 import BeautifulSoup

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import gate_and_limit  # noqa: F401 (used via fetch)
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig
import httpx


def feed_url(token: str) -> str:
    return f"https://{token}.jobs.personio.com/xml"


def _text(node) -> str:
    return node.get_text(strip=True) if node is not None else ""


def parse_personio(xml_text: str, company: str) -> list[RawJob]:
    soup = BeautifulSoup(xml_text, "xml")
    jobs: list[RawJob] = []
    for position in soup.find_all("position"):
        descriptions = position.find_all("value")
        jd_html = "\n".join(_text(v) for v in descriptions) if descriptions else ""
        job_id = _text(position.find("id"))
        jobs.append(
            RawJob(
                source="personio",
                url=f"https://{company}.jobs.personio.com/job/{job_id}" if job_id else None,
                company=company,
                title=_text(position.find("name")),
                location=_text(position.find("office")) or None,
                jd_text=html_to_markdown(jd_html),
            )
        )
    return jobs


def fetch_personio(
    target: AtsTarget, search: SearchConfig, limit: int | None = None, skip_seen=None
) -> list[RawJob]:
    resp = httpx.get(feed_url(target.token), timeout=30)
    resp.raise_for_status()
    return parse_personio(resp.text, target.token)
```

> Note: `fetch_personio` returns every parsed job; the relevance gate + `limit` are
> applied by `harvest` at the CompaniesConnector level, matching Greenhouse/Lever.
> `skip_seen` is accepted for the uniform adapter shape; a single feed GET has no
> per-job step to skip.

- [ ] **Step 5: Detect + register**

In `detect.py`, add to the `_SUBDOMAIN_HOSTS` table introduced in Task 3's note (create
it if Tasks 2/3 haven't run yet):
```python
_SUBDOMAIN_HOSTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?P<token>[a-z0-9-]+)\.jobs\.personio\.(?:com|de)$", re.IGNORECASE), "personio"),
    # ... recruitee/workable/breezy/jazzhr/bamboohr entries from Tasks 2,3,5,6,7
]
```
with a `_l1` branch that returns `AtsTarget(ats, token=match.group("token"))` on match.

In `companies.py`:
```python
from resume_agent.discovery.connectors.personio import fetch_personio


def _personio(target, search, limit=None, skip_seen=None):
    return fetch_personio(target, search, limit, skip_seen=skip_seen)
```
```python
_BACKENDS = { ..., "personio": _personio }
```

Detection test:
```python
def test_subdomain_personio_url():
    assert detect_ats("https://acme.jobs.personio.com/") == AtsTarget("personio", "acme")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_personio.py tests/test_connector_detect.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/discovery/connectors/personio.py tests/fixtures/personio_feed.xml tests/test_connector_personio.py src/resume_agent/discovery/connectors/detect.py src/resume_agent/discovery/connectors/companies.py tests/test_connector_detect.py
git commit -m "feat: add Personio XML-feed backend"
```

---

### Task 8: Server-side location push for Lever

**Files:**
- Modify: `src/resume_agent/discovery/connectors/lever.py`
- Modify: `src/resume_agent/discovery/connectors/companies.py` (`_lever` adapter passes `search`)
- Test: `tests/test_connector_lever.py` (create/extend)

**Interfaces:**
- Produces: `fetch_lever_board(token, search=None) -> list` — when `search` carries a
  location, add Lever's `?location=` query param (best-effort narrow).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connector_lever.py  (append/create)
import resume_agent.discovery.connectors.lever as lever
from resume_agent.discovery.connectors.lever import fetch_lever_board
from resume_agent.discovery.search_config import SearchConfig


def test_fetch_lever_board_pushes_location(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self): ...
        def json(self): return []

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return _Resp()

    monkeypatch.setattr(lever.httpx, "get", fake_get)
    fetch_lever_board("acme", search=SearchConfig(locations=["Remote"]))
    assert captured["params"]["location"] == "Remote"
    assert captured["params"]["mode"] == "json"


def test_fetch_lever_board_omits_location_when_unset(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self): ...
        def json(self): return []

    monkeypatch.setattr(lever.httpx, "get", lambda url, params=None, timeout=None: (
        captured.__setitem__("params", params) or _Resp()))
    fetch_lever_board("acme")
    assert "location" not in captured["params"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_lever.py -v`
Expected: FAIL — `fetch_lever_board() got an unexpected keyword argument 'search'`.

- [ ] **Step 3: Edit `fetch_lever_board`**

```python
from resume_agent.discovery.connectors.text import html_to_markdown, primary_location


def fetch_lever_board(token: str, search: SearchConfig | None = None) -> list:
    """GET a Lever board's postings array in JSON mode, optionally location-narrowed."""
    params: dict[str, str] = {"mode": "json"}
    if search is not None:
        location = primary_location(search)
        if location:
            params["location"] = location  # coarse server-side narrow; local gate authoritative
    resp = httpx.get(f"{_BASE}/{token}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

Update `LeverConnector.fetch` to pass `search`:
```python
    def _get_board(self, token: str, search: SearchConfig) -> list:
        return fetch_lever_board(token, search)
```
```python
        return harvest(
            self.boards,
            lambda board: parse_lever(self._get_board(board.token, search), board.display()),
            search=search, limit=limit, key=lambda board: board.token, on_error=http_failure,
        )
```

In `companies.py`, update the `_lever` adapter to pass `search`:
```python
def _lever(target, search, limit=None, skip_seen=None):
    return parse_lever(fetch_lever_board(target.token, search), target.token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_lever.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/lever.py src/resume_agent/discovery/connectors/companies.py tests/test_connector_lever.py
git commit -m "feat: push server-side location filter to Lever boards"
```

---

### Task 9: Docs, example config, full-suite regression

**Files:**
- Modify: `CLAUDE.md` (source-priority table + hot-paths + companies dispatch note)
- Modify: `config/connectors.yaml.example` (comment the newly auto-detected hosts)
- Test: full suite + lint.

- [ ] **Step 1: Update `CLAUDE.md`** — add the new canonical sources to the source-priority
  table row (`smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`,
  `bamboohr`) and to `source_tier._CANONICAL` if not already covered.

- [ ] **Step 2: Update `source_tier._CANONICAL`** — add the seven new source strings so
  they rank as direct (0), not aggregator:

```python
_CANONICAL = {
    "greenhouse", "lever", "ashby", "workday", "tesla", "google", "companies", "url", "manual",
    "smartrecruiters", "workable", "recruitee", "personio", "breezy", "jazzhr", "bamboohr",
}
```
Add a test in `tests/test_source_tier.py`:
```python
from resume_agent.discovery.source_tier import source_rank

def test_new_ats_sources_rank_as_direct():
    for src in ("smartrecruiters", "workable", "recruitee", "personio", "breezy", "jazzhr", "bamboohr"):
        assert source_rank(src) == 0
```

- [ ] **Step 3: Comment the example config** — in `config/connectors.yaml.example`, under
  the `companies:` section, note that pasting any `jobs.smartrecruiters.com/...`,
  `*.workable.com`, `*.recruitee.com`, `*.jobs.personio.com`, `*.breezy.hr`,
  `*.applytojob.com`, or `*.bamboohr.com` careers URL is auto-detected.

- [ ] **Step 4: Full suite + lint**

Run: `.venv/Scripts/python.exe -m pytest`
Run: `ruff check`
Expected: PASS / no findings.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md src/resume_agent/discovery/source_tier.py tests/test_source_tier.py config/connectors.yaml.example
git commit -m "docs: document new ATS backends and rank them as canonical sources"
```

---

## Self-Review

- **Spec coverage:** Thread A — seven backends via detect + `_BACKENDS`, URL-only
  onboarding (Tasks 1–7); reverse-engineered isolation preserved (existing
  `_failure_reason`); fixtures per backend (each task Step 1). Thread B — `primary_location`
  (Task 0), SmartRecruiters `q` push (Task 1), Lever location push (Task 8), best-effort
  omission when unmapped (stated in each task). Canonical ranking (Task 9). All covered.
- **Type consistency:** `SmartRecruitersRow.posting_id` defined and used in Task 1;
  `fetch_<name>(target, search, limit=None, skip_seen=None)` signature uniform across all
  backends and matches the `companies._BACKENDS` adapter shape from the skip-known plan;
  `primary_location(search) -> str` defined in Task 0 and consumed in Tasks 1/8.
- **Placeholder scan:** the review-correction section above replaces every unverified
  endpoint/shape assumption. Each parser is written against a committed capture and each
  fetch path has an offline HTTP-wiring test.
- **Dependency note:** assumes the skip-known plan's `skip_seen` seam exists; if not,
  omit `skip_seen` from the new backends (see Global Constraints).
