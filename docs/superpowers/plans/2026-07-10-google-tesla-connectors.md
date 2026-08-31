# Google + Tesla Connector Rebuild Implementation Plan

> **Execution:** Implement inline, task-by-task, with a red-green-refactor test cycle. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Google and Tesla connectors work against the live portals: Google via httpx + embedded `AF_initDataCallback` JSON parsing (old API is 404), Tesla via the shared visible Playwright browser (API is Akamai-gated, 403 to any bare HTTP client).

**Architecture:** Both connectors keep their exact `_BACKENDS` dispatch signatures — only the transport and parsing change. Google becomes list-only (the results page embeds full JDs; verified live 2026-07-10). Tesla gets a `TeslaPortal` browser seam: one visible tab captures the state JSON the page itself fetches, then detail fetches run same-origin inside that tab via `page.evaluate`, so `harvest_detailed` keeps owning gate/limit/skip logic. `CompaniesConnector` grows a `concurrent_fetch` property so a Tesla URL serializes the connector with other browser connectors in the pull runner.

**Tech Stack:** Python 3.13, httpx, Playwright (sync API, lazy-imported), pytest (offline — browser and httpx faked).

## Reviewed corrections (authoritative)

- Google parsing is pinned to the live-shaped `ds:1` callback fixture. A valid
  empty jobs payload returns `[]`; a missing or malformed `ds:1` payload raises
  `ValueError` so companies failure isolation records portal drift instead of
  silently ending pagination.
- Google uses the live portal's valid stable id-only result URL. When `limit` is
  set, paging stops only after the connector has found that many relevant,
  unseen rows; off-target and `skip_seen` rows do not consume the cap.
- Google and Tesla tests load minimized fixtures from
  `tests/fixtures/google/` and `tests/fixtures/tesla/` instead of relying only
  on hand-built inline payloads.
- Tesla follows the repository's browser serialization contract:
  `CompaniesConnector.concurrent_fetch` becomes false when Tesla is present,
  and the pull runner's browser lock serializes it with Adzuna, LinkedIn, and
  dashboard scraping. The portal opens the canonical US search URL because the
  singleton `AtsTarget` intentionally carries no source URL.
- Actual adjacent suites are `tests/test_connector_detect.py` and
  `tests/test_pull_runner_concurrency.py`.

## Global Constraints

- Offline suite green with **no API key and no network**: `.venv/Scripts/python.exe -m pytest`
- Lint clean: `ruff check`
- No wire-contract change: `git diff main --stat -- contracts/` stays empty for this plan
- Per-URL failure isolation: a parse/transport failure in one careers URL records to `FetchResult.failures` via `companies._failure_reason`, never aborts a pull
- Playwright must be imported lazily (inside the function that uses it) — a pull with no Tesla URL must never import it
- Spec: `docs/superpowers/specs/2026-07-10-discovery-precision-design.md`

## Blob format reference (verified live 2026-07-10)

`GET https://www.google.com/about/careers/applications/jobs/results?q=<term>&page=<n>`
returns HTML containing `<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:[...], sideChannel: {}});</script>`. The `data` payload is `[rows, null, total, page_size]` where each row is a ~21-element list:

| index | content |
| ----- | ------- |
| 0 | job id (string of digits) |
| 1 | title |
| 2 | apply/signin URL |
| 3 | `[null, "<responsibilities html>"]` |
| 4 | `[null, "<qualifications html>"]` |
| 7 | `"Google"` (company) |
| 9 | locations: `[["Sunnyvale, CA, USA", [addresses], "City", …], …]` |
| 10 | `[null, "<about-the-team html>"]` |
| 12 | publish time `[epoch_seconds, nanos]` |

## File Structure

| Path | Role |
| ---- | ---- |
| `src/resume_tailor_harness/discovery/connectors/google.py` | Rewritten: blob extraction + row parsing + paging fetch |
| `src/resume_tailor_harness/discovery/connectors/tesla.py` | Rewritten: `TeslaPortal` browser seam + portal-backed fetch |
| `src/resume_tailor_harness/discovery/connectors/companies.py` | `concurrent_fetch` becomes a property |
| `tests/test_connector_google.py` | Rewritten for the blob format |
| `tests/test_connector_tesla.py` | Rewritten for the portal seam |
| `tests/fixtures/google/results.html` | Minimized live-shaped Google callback |
| `tests/fixtures/tesla/state.json`, `detail-*.json` | Tesla state/detail payloads |
| `tests/test_connector_companies.py` | + property tests (if the companies tests live in a differently named file, `grep -l CompaniesConnector tests/*.py` and append there) |
| `CLAUDE.md` | Design-note updates |

---

### Task 1: Google blob extraction and row parsing

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/google.py` (full rewrite)
- Test: `tests/test_connector_google.py` (full rewrite)

**Interfaces:**

- Consumes: `RawJob`, `SkipSeen` (`connectors/base.py`), `html_to_markdown`, `primary_search_term` (`connectors/text.py`), `AtsTarget`, `SearchConfig`
- Produces: `extract_job_rows(html: str) -> list[list]`, `parse_job_rows(rows: list[list]) -> list[RawJob]`, `fetch_google(target, search, limit=None, skip_seen=None) -> list[RawJob]` — same dispatch signature `companies.py` already calls

- [ ] **Step 1: Rewrite the test file with failing tests**

Replace the whole of `tests/test_connector_google.py` with:

```python
import json
from datetime import timezone

import resume_tailor_harness.discovery.connectors.google as google
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.search_config import SearchConfig

TARGET = AtsTarget("google")


def _row(
    job_id="123",
    title="Software Engineer",
    location="Austin, TX, USA",
    about="<p>About the team.</p>",
    quals="<p>Python required.</p>",
    resp="<p>Build systems.</p>",
    posted=1782808699,
):
    row = [None] * 21
    row[0] = job_id
    row[1] = title
    row[2] = "https://www.google.com/about/careers/applications/signin?jobId=x"
    row[3] = [None, resp]
    row[4] = [None, quals]
    row[7] = "Google"
    row[9] = [[location, ["street address"], "City", "ST"]]
    row[10] = [None, about]
    row[12] = [posted, 0]
    return row


def _page_html(rows):
    payload = json.dumps([rows, None, 1745, 20])
    return (
        "<html><script>AF_initDataCallback({key: 'ds:0', hash: '1', "
        'data:["irrelevant"], sideChannel: {}});</script>'
        "<script>AF_initDataCallback({key: 'ds:1', hash: '2', data:"
        + payload
        + ", sideChannel: {}});</script></html>"
    )


def test_extract_job_rows_finds_the_jobs_blob():
    rows = google.extract_job_rows(_page_html([_row(), _row(job_id="456", title="SRE")]))
    assert [r[1] for r in rows] == ["Software Engineer", "SRE"]


def test_extract_job_rows_empty_on_blobless_html():
    assert google.extract_job_rows("<html><body>no data</body></html>") == []


def test_parse_job_rows_maps_fields():
    job = google.parse_job_rows([_row()])[0]
    assert job.source == "google"
    assert job.company == "Google"
    assert job.title == "Software Engineer"
    assert job.location == "Austin, TX, USA"
    assert job.url == (
        "https://www.google.com/about/careers/applications/jobs/results/123"
    )
    # All three description sections land in the JD.
    assert "About the team." in job.jd_text
    assert "Python required." in job.jd_text
    assert "Build systems." in job.jd_text
    assert job.posted_at is not None
    assert job.posted_at.tzinfo == timezone.utc


def test_parse_job_rows_strips_material_icon_tokens():
    job = google.parse_job_rows(
        [_row(about="<p>Google _corporate_fare_ Google _place_ Austin</p>")]
    )[0]
    assert "corporate_fare" not in job.jd_text
    assert "_place_" not in job.jd_text


def test_parse_job_rows_skips_malformed_rows():
    good = _row()
    jobs = google.parse_job_rows([["", None], "not-a-row", good, [None]])
    assert [j.title for j in jobs] == ["Software Engineer"]


def test_fetch_google_pages_until_empty(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(url, params, headers, timeout):
        calls.append(dict(params))
        if params["page"] == 1:
            return _Resp(_page_html([_row(), _row(job_id="456", title="SRE")]))
        return _Resp(_page_html([]))

    monkeypatch.setattr(google.httpx, "get", fake_get)
    jobs = google.fetch_google(TARGET, SearchConfig(titles=["Software Engineer"]))
    assert [j.title for j in jobs] == ["Software Engineer", "SRE"]
    assert calls[0]["q"] == "Software Engineer"
    assert [c["page"] for c in calls] == [1, 2]


def test_fetch_google_limit_stops_paging(monkeypatch):
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(url, params, headers, timeout):
        calls.append(params["page"])
        return _Resp(_page_html([_row(job_id=str(params["page"]))]))

    monkeypatch.setattr(google.httpx, "get", fake_get)
    jobs = google.fetch_google(TARGET, SearchConfig(), limit=1)
    assert len(jobs) == 1
    assert calls == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_google.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'extract_job_rows'`

- [ ] **Step 3: Rewrite google.py**

Replace the whole of `src/resume_tailor_harness/discovery/connectors/google.py` with:

```python
"""Google Careers via the public results page's embedded AF_initDataCallback
blobs. The old careers.google.com/api/v3 endpoint is dead (404, 2026-07-10);
the results page itself embeds full job rows — description sections included —
so this connector is list-only. Reverse-engineered: a blob-shape change raises
a parse error that companies._failure_reason isolates to this URL."""

import json
import re
from datetime import datetime, timezone

import httpx

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.text import html_to_markdown, primary_search_term
from resume_tailor_harness.discovery.search_config import SearchConfig

_RESULTS_URL = "https://www.google.com/about/careers/applications/jobs/results"
_MAX_PAGES = 20
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) resume-tailor-harness",
}

_BLOB = re.compile(r"AF_initDataCallback\((\{.*?\})\);", re.S)
_BLOB_DATA = re.compile(r"data:\s*(\[.*)\s*,\s*sideChannel", re.S)


def extract_job_rows(html: str) -> list[list]:
    """Job rows from the AF_initDataCallback blob that carries them.

    The jobs blob's data is ``[rows, null, total, page_size]``; a row is a
    list of 11+ cells. Identified structurally, not by ds: key, so a key
    renumbering does not break parsing.
    """
    for blob in _BLOB.findall(html):
        data_match = _BLOB_DATA.search(blob)
        if not data_match:
            continue
        try:
            data = json.loads(data_match.group(1))
        except ValueError:
            continue
        if (
            isinstance(data, list)
            and data
            and isinstance(data[0], list)
            and data[0]
            and isinstance(data[0][0], list)
            and len(data[0][0]) >= 11
        ):
            return data[0]
    return []


def _html_cell(row: list, index: int) -> str:
    """Description cells are ``[null, "<html>"]``; anything else is ''."""
    cell = row[index] if index < len(row) else None
    if isinstance(cell, list) and len(cell) >= 2 and isinstance(cell[1], str):
        return cell[1]
    return ""


def _first_location(row: list) -> str | None:
    cell = row[9] if len(row) > 9 else None
    if isinstance(cell, list) and cell and isinstance(cell[0], list) and cell[0]:
        display = cell[0][0]
        if isinstance(display, str):
            return display
    return None


def _posted_at(row: list) -> datetime | None:
    cell = row[12] if len(row) > 12 else None
    if isinstance(cell, list) and cell and isinstance(cell[0], (int, float)):
        return datetime.fromtimestamp(cell[0], tz=timezone.utc)
    return None


def parse_job_rows(rows: list[list]) -> list[RawJob]:
    """Map jobs-blob rows to RawJobs, skipping rows that lost their shape."""
    jobs: list[RawJob] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        job_id = str(row[0] or "")
        title = row[1]
        if not job_id or not isinstance(title, str):
            continue
        description = "\n".join(
            part
            for part in (_html_cell(row, 10), _html_cell(row, 4), _html_cell(row, 3))
            if part
        )
        jobs.append(
            RawJob(
                source="google",
                url=f"{_RESULTS_URL}/{job_id}",
                company="Google",
                title=title,
                location=_first_location(row),
                jd_text=html_to_markdown(description),
                posted_at=_posted_at(row),
            )
        )
    return jobs


def fetch_google(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    jobs: list[RawJob] = []
    query = primary_search_term(search)  # invariant across pages
    for page_num in range(1, _MAX_PAGES + 1):
        resp = httpx.get(
            _RESULTS_URL,
            params={"q": query, "page": page_num},
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        batch = parse_job_rows(extract_job_rows(resp.text))
        if not batch:
            break
        jobs.extend(batch)
        if limit is not None and len(jobs) >= limit:
            return jobs[:limit]
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_google.py -v`
Expected: PASS (all 7)

- [ ] **Step 5: Run the companies + detect suites (dispatch conformance)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py tests/test_connector_detect.py -v`
(Adjust filenames via `ls tests | grep -i -e companies -e detect` if they differ.)
Expected: PASS — `fetch_google`'s signature is unchanged.

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_tailor_harness/discovery/connectors/google.py tests/test_connector_google.py
git add src/resume_tailor_harness/discovery/connectors/google.py tests/test_connector_google.py
git commit -m "Rebuilds the Google connector on the careers results page blobs"
```

---

### Task 2: Tesla portal seam and browser-backed fetch

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/tesla.py` (full rewrite)
- Test: `tests/test_connector_tesla.py` (full rewrite)

**Interfaces:**

- Consumes: `harvest_detailed` (unchanged), `parse_listings` / `apply_tesla_detail` (kept as-is), `get_settings().linkedin_user_data_dir` (the shared persistent browser profile, same one `url_ingest/browser.py` uses)
- Produces: `open_portal() -> ContextManager[TeslaPortal]` (module seam tests monkeypatch), `TeslaPortal.state: dict`, `TeslaPortal.job_detail(listing_id: str) -> dict`, `fetch_tesla(target, search, limit=None, skip_seen=None) -> list[RawJob]` — dispatch signature unchanged. Task 3 relies on nothing here; the companies property in Task 3 keys off `detect.identify_host`, not this module.

- [ ] **Step 1: Rewrite the test file with failing tests**

Replace the whole of `tests/test_connector_tesla.py` with:

```python
from contextlib import nullcontext

import resume_tailor_harness.discovery.connectors.tesla as tesla
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.search_config import SearchConfig

TARGET = AtsTarget("tesla")
STATE = {"listings": [
    {"id": "1", "title": "Software Engineer", "department": "Software", "region": "Austin, TX"},
    {"id": "2", "title": "Welder", "department": "Manufacturing", "region": "Fremont, CA"},
]}
DETAILS = {
    "1": {"id": "1", "description": "<p>Build with Python.</p>",
          "url": "https://www.tesla.com/careers/search/job/1"},
    "2": {"id": "2", "description": "<p>Build fixtures.</p>",
          "url": "https://www.tesla.com/careers/search/job/2"},
}


class _FakePortal:
    def __init__(self, state=STATE, details=DETAILS, fail_ids=()):
        self.state = state
        self._details = details
        self._fail = set(fail_ids)
        self.detail_calls = []

    def job_detail(self, listing_id):
        self.detail_calls.append(listing_id)
        if listing_id in self._fail:
            raise RuntimeError("detail 403")
        return self._details[listing_id]


def _use(monkeypatch, portal):
    monkeypatch.setattr(tesla, "open_portal", lambda: nullcontext(portal))
    return portal


def test_parse_tesla_listings_to_partial_rawjobs():
    rows = tesla.parse_listings(STATE)
    assert [r.title for r in rows] == ["Software Engineer", "Welder"]
    assert rows[0].source == "tesla"
    assert rows[0].company == "Tesla"
    assert rows[0].location == "Austin, TX"
    assert rows[0].listing_id == "1"
    assert rows[0].jd_text == ""


def test_parse_tesla_listings_compact_keys():
    """State endpoint may emit compact keys: t=title, l=location."""
    compact_state = {"listings": [{"id": "3", "t": "ML Engineer", "l": "Palo Alto, CA"}]}
    rows = tesla.parse_listings(compact_state)
    assert rows[0].title == "ML Engineer"
    assert rows[0].location == "Palo Alto, CA"


def test_fetch_tesla_gates_then_details(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(role_anchors=["Software Engineer"]))
    assert [j.title for j in jobs] == ["Software Engineer"]
    assert portal.detail_calls == ["1"]
    assert "Python" in jobs[0].jd_text


def test_fetch_tesla_applies_keyword_filter_after_detail(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(keywords=["Python"]))
    assert [j.title for j in jobs] == ["Software Engineer"]
    assert portal.detail_calls == ["1", "2"]


def test_fetch_tesla_isolates_failed_detail_fetch(monkeypatch):
    """A failing in-page detail fetch skips only that listing."""
    _use(monkeypatch, _FakePortal(fail_ids={"1"}))
    jobs = tesla.fetch_tesla(TARGET, SearchConfig())
    assert [j.title for j in jobs] == ["Welder"]


def test_fetch_tesla_respects_limit(monkeypatch):
    portal = _use(monkeypatch, _FakePortal())
    jobs = tesla.fetch_tesla(TARGET, SearchConfig(), limit=1)
    assert len(jobs) == 1
    assert portal.detail_calls == ["1"]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_tesla.py -v`
Expected: the parse tests PASS (unchanged code paths), every `fetch_tesla` test FAILS (`AttributeError: ... 'open_portal'`)

- [ ] **Step 3: Rewrite tesla.py**

Replace the whole of `src/resume_tailor_harness/discovery/connectors/tesla.py` with:

```python
"""Tesla careers via the shared visible browser. The cua-api endpoints are
Akamai-gated (403 to httpx even with browser headers, verified 2026-07-10), so
one real tab loads the careers search page, captures the state JSON the page
itself fetches, and runs detail fetches same-origin inside that tab. A pull
whose companies list includes Tesla pops a browser window (Adzuna precedent)."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from resume_tailor_harness.config import get_settings
from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.harvest import harvest_detailed
from resume_tailor_harness.discovery.connectors.text import html_to_markdown
from resume_tailor_harness.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.tesla.com/careers/search/?site=US"
_STATE_MARKER = "cua-api/apps/careers/state"
_JOB_URL = "https://www.tesla.com/cua-api/apps/careers/job/{id}"
_STATE_TIMEOUT_MS = 45_000


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
                title=item.get("title") or item.get("t"),
                location=item.get("region") or item.get("l"),
                jd_text="",
                listing_id=str(item.get("id") or ""),
            )
        )
    return rows


class TeslaPortal:
    """One live careers tab: the captured state payload plus same-origin
    detail fetches that ride the tab's Akamai cookies."""

    def __init__(self, page: Any, state: dict):
        self._page = page
        self.state = state

    def job_detail(self, listing_id: str) -> dict:
        return self._page.evaluate(
            """async (url) => {
                const resp = await fetch(url, { headers: { accept: "application/json" } });
                if (!resp.ok) throw new Error(`detail ${resp.status}`);
                return await resp.json();
            }""",
            _JOB_URL.format(id=listing_id),
        )


@contextmanager
def open_portal() -> Iterator[TeslaPortal]:
    """Open the careers page in the shared visible profile and capture the
    state response the page issues. Lazy playwright import: a pull with no
    Tesla URL never imports it."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            get_settings().linkedin_user_data_dir, headless=False
        )
        try:
            page = context.new_page()
            with page.expect_response(
                lambda r: _STATE_MARKER in r.url, timeout=_STATE_TIMEOUT_MS
            ) as captured:
                page.goto(_SEARCH_URL, wait_until="domcontentloaded")
            yield TeslaPortal(page, captured.value.json())
        finally:
            context.close()


def apply_tesla_detail(row: TeslaRow, info: dict) -> None:
    row.jd_text = html_to_markdown(info.get("description", ""))
    row.url = info.get("url") or row.url


def _fetch_detail(portal: TeslaPortal, row: TeslaRow) -> dict | None:
    try:
        return portal.job_detail(row.listing_id)
    except Exception:  # noqa: BLE001 - one bad detail skips its row, never the batch
        return None


def fetch_tesla(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    with open_portal() as portal:
        return harvest_detailed(
            parse_listings(portal.state),
            lambda row: _fetch_detail(portal, row),
            apply_tesla_detail,
            search=search,
            limit=limit,
            skip_seen=skip_seen,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_tesla.py -v`
Expected: PASS (all 6)

- [ ] **Step 5: Confirm no eager playwright import**

Run: `.venv/Scripts/python.exe -c "import sys; import resume_tailor_harness.discovery.connectors.tesla; assert 'playwright' not in sys.modules, 'playwright imported eagerly'; print('lazy OK')"`
Expected: `lazy OK`

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_tailor_harness/discovery/connectors/tesla.py tests/test_connector_tesla.py
git add src/resume_tailor_harness/discovery/connectors/tesla.py tests/test_connector_tesla.py
git commit -m "Drives the Tesla connector through a visible browser portal"
```

---

### Task 3: Companies serialization when Tesla is aboard

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/companies.py:149` (`concurrent_fetch` class attribute → property)
- Test: `tests/test_connector_companies.py` (append; locate via `grep -l CompaniesConnector tests/*.py` if named differently)

**Interfaces:**

- Consumes: `identify_host(url) -> AtsTarget | None` (`detect.py` — pure, no network)
- Produces: `CompaniesConnector.concurrent_fetch: bool` (property) — the runner reads it via `getattr(connector, "concurrent_fetch", True)` (`runner.py:85`), so a property is transparent

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connector_companies.py`:

```python
def test_companies_concurrent_without_browser_portals():
    connector = CompaniesConnector(["https://boards.greenhouse.io/acme"])
    assert connector.concurrent_fetch is True


def test_companies_serializes_when_tesla_is_aboard():
    connector = CompaniesConnector(
        [
            "https://boards.greenhouse.io/acme",
            "https://www.tesla.com/careers/search/?site=US",
        ]
    )
    assert connector.concurrent_fetch is False
```

(`CompaniesConnector` is already imported by the existing tests in that file; if not, add `from resume_tailor_harness.discovery.connectors.companies import CompaniesConnector`.)

- [ ] **Step 2: Run tests to verify one fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py -v -k concurrent`
Expected: the greenhouse-only test PASSES (class attribute is `True`); the Tesla test FAILS

- [ ] **Step 3: Implement the property**

In `src/resume_tailor_harness/discovery/connectors/companies.py`, extend the detect import
(line 12) to `from resume_tailor_harness.discovery.connectors.detect import AtsTarget, detect_ats, identify_host`, then replace the class attribute line `concurrent_fetch = True` inside `CompaniesConnector` with:

```python
    @property
    def concurrent_fetch(self) -> bool:
        """False when a browser-driven portal (Tesla) is among the URLs, so the
        runner serializes this connector with other browser connectors instead
        of racing two visible browser sessions."""
        return not any(
            (target := identify_host(url)) is not None and target.ats == "tesla"
            for url in self.urls
        )
```

- [ ] **Step 4: Run the companies + runner suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py tests/test_pull_runner_concurrency.py -v`
(Locate the runner tests with `grep -l run_pull tests/*.py` if the name differs.)
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/discovery/connectors/companies.py tests/test_connector_companies.py
git add src/resume_tailor_harness/discovery/connectors/companies.py tests/test_connector_companies.py
git commit -m "Serializes companies pulls that include the Tesla browser portal"
```

---

### Task 4: Documentation sweep

**Files:**

- Modify: `CLAUDE.md` (two spots)

**Interfaces:** none — docs only.

- [ ] **Step 1: Update the reverse-engineered design note**

In `CLAUDE.md` → "Known design notes", replace the bullet starting
**"Tesla/Google endpoints are reverse-engineered."** with:

```markdown
- **Tesla/Google portals are reverse-engineered.** Google is parsed from the
  careers results page's embedded `AF_initDataCallback` blobs (list-only — the
  blob carries full JDs); the old v3 API is dead. Tesla's cua-api is
  Akamai-gated, so `fetch_tesla` opens a `TeslaPortal`: one **visible** browser
  tab captures the state JSON and runs same-origin detail fetches — a pull
  whose companies list includes Tesla pops a window and is serialized with
  other browser connectors via `CompaniesConnector.concurrent_fetch`. Either
  portal shifting shape records a per-URL failure, never aborting the pull.
```

- [ ] **Step 2: Update the hot-paths rows**

In the CLAUDE.md hot-paths table, update the two rows:

- `src/resume_tailor_harness/discovery/connectors/tesla.py` → role: `Tesla browser portal: state capture + same-origin detail fetches`
- `src/resume_tailor_harness/discovery/connectors/google.py` → role: `Google Careers results-page blob parser (list-only)`

- [ ] **Step 3: Full suite, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest -q` and `ruff check`
Expected: green.

```bash
git add CLAUDE.md
git commit -m "Documents the rebuilt Google and Tesla portal connectors"
```

---

## Final verification (after all tasks)

- [ ] `.venv/Scripts/python.exe -m pytest -q` — full suite PASS
- [ ] `ruff check` — clean
- [ ] `git diff main --stat -- contracts/` — empty
- [ ] **Manual live smoke (optional, network + window):** `resume-tailor-harness pull --source <a companies source containing the Google or Tesla URL> --limit 5` — Google rows arrive with full JDs; Tesla pops one window and yields detailed rows
- [ ] Use the repository code-review-and-quality and code-simplification passes before merging

## Self-review notes (already applied)

- Spec coverage: Google rebuild → Task 1 (list-only per the amended spec); Tesla browser connector → Task 2; serialization → Task 3; CLAUDE.md notes → Task 4. Detection needed no task (already in `_SINGLETON_HOSTS`).
- Type consistency: `open_portal`/`TeslaPortal.job_detail(listing_id)` used by tests via `nullcontext(portal)`; `extract_job_rows`/`parse_job_rows`/`fetch_google` names match between Tasks 1's tests and implementation.
- Judgment calls: (a) `_fetch_detail` swallows all portal exceptions to a row-skip — harvest_detailed's `httpx.HTTPError` isolation can't see browser errors; (b) blob located structurally rather than by `ds:` key so renumbering survives; (c) `TeslaRow`/`parse_listings`/`apply_tesla_detail` kept byte-compatible so the parse tests pin them unchanged.
