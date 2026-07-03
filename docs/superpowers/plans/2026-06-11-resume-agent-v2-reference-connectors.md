# Resume Agent v2 — Reference Connectors (Greenhouse · Adzuna · RemoteOK) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three production connectors — one per query model — behind the Plan 1 `Connector` seam: **Greenhouse** (ATS, company-scoped), **Adzuna** (aggregator, keyword), **RemoteOK** (feed). Each is a _pure JSON→`RawJob` mapper_ tested against saved fixtures, wrapped in a thin connector whose only un-CI-tested part is a single HTTP call. Add `config/connectors.yaml` + `build_connectors()` so a config file decides which sources are live.

**Architecture:** This is **Plan 2 of 6** for v2 (spec `docs/superpowers/specs/2026-06-11-resume-agent-v2-connectors-design.md`). The valuable, fragile logic in every API connector is the _mapping_ (payload → `RawJob`) and the _client-side keyword filter_; both are pure functions over fixtures — the **interface is the test surface**. The HTTP fetch lives behind a one-method seam (`_get_*`) overridden in tests, exactly like Plan 1's LinkedIn `_search_html`. `build_connectors()` is the registry that turns `ConnectorsConfig` into live `Connector` instances in canonical dedup order (ATS → feed → aggregator → LinkedIn).

**Tech Stack:** Python 3.13, uv, **httpx** (already a dep — no new deps), **beautifulsoup4** (already a dep, for HTML→text), pydantic, pytest.

**Depends on:** **Plan 1 merged** (`discovery.connectors.base.Connector`/`RawJob`, `discovery.ingest.ingest_jobs`). Reuses `config.load_yaml`, `models.base.ExtensibleModel`, `discovery.search_config.SearchConfig`, `config.Settings`.

> **Commit convention:** every commit ends with `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`.

---

## Architecture notes (the two lenses)

**Deepening:** Each `parse_<source>` is a deep module — a small signature (`dict -> list[RawJob]`) hiding each provider's JSON quirks (Greenhouse's HTML-escaped `content`, Adzuna's nested `company.display_name`, RemoteOK's legal-header first element). `build_connectors` concentrates "which sources are live + in what order" in one place (**locality**): adding Lever later is one registry line + one mapper, nothing else changes.

**Restraint (karpathy):** connectors ship **only the fields `RawJob` needs** — no salary/tags/etc. modeling yet. Greenhouse fetches the configured boards and nothing speculative (no board auto-discovery — that was explicitly deferred to v3). Lever/Ashby/WWR/HN are **not** built here; they are "copy a reference," noted at the end.

---

## File Structure

```
config/connectors.yaml.example          # CREATE
.env.example                            # MODIFY — document ADZUNA_APP_ID/ADZUNA_APP_KEY
src/resume_agent/config.py              # MODIFY — Settings += adzuna_app_id/app_key
src/resume_agent/discovery/connectors/
  text.py                               # CREATE — html_to_text + search filter (pure)
  config.py                             # CREATE — ConnectorsConfig + load_connectors_config
  greenhouse.py                         # CREATE — parse_greenhouse + GreenhouseConnector
  adzuna.py                             # CREATE — parse_adzuna + AdzunaConnector
  remoteok.py                           # CREATE — parse_remoteok + RemoteOKConnector
  registry.py                           # CREATE — build_connectors()
tests/fixtures/greenhouse/jobs.json     # CREATE
tests/fixtures/adzuna/search.json       # CREATE
tests/fixtures/remoteok/api.json        # CREATE
tests/test_connectors_text.py           # CREATE
tests/test_connectors_config.py         # CREATE
tests/test_connector_greenhouse.py      # CREATE
tests/test_connector_adzuna.py          # CREATE
tests/test_connector_remoteok.py        # CREATE
tests/test_connectors_registry.py       # CREATE
```

---

## Task 1: shared connector text helpers (HTML→text + keyword filter)

**Files:**

- Create: `src/resume_agent/discovery/connectors/text.py`
- Test: `tests/test_connectors_text.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_text.py`:

```python
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text
from resume_agent.discovery.search_config import SearchConfig


def test_html_to_text_unescapes_and_strips_tags():
    raw = "&lt;p&gt;We use &lt;b&gt;Python&lt;/b&gt; and Kubernetes.&lt;/p&gt;"
    text = html_to_text(raw)
    assert "Python" in text and "Kubernetes" in text
    assert "<" not in text and "&lt;" not in text


def _job(title, jd):
    return RawJob("greenhouse", None, "Acme", title, "Remote", jd)


def test_filter_keeps_all_when_no_keywords():
    jobs = [_job("Chef", "cooking")]
    assert filter_by_search(jobs, SearchConfig()) == jobs


def test_filter_matches_keyword_in_title_or_jd_case_insensitively():
    jobs = [
        _job("Backend Engineer", "build services"),
        _job("Chef", "make pasta"),
        _job("Designer", "We use PYTHON daily"),
    ]
    cfg = SearchConfig(keywords=[" python "], titles=["engineer"])
    kept = {j.title for j in filter_by_search(jobs, cfg)}
    assert kept == {"Backend Engineer", "Designer"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.text'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/discovery/connectors/text.py`:

```python
import html

from bs4 import BeautifulSoup

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.search_config import SearchConfig


def html_to_text(raw: str) -> str:
    """Unescape HTML entities then strip tags to readable text."""
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    return soup.get_text(separator="\n", strip=True)


def _terms(search: SearchConfig) -> list[str]:
    return [t.strip().lower() for t in (*search.keywords, *search.titles) if t.strip()]


def filter_by_search(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Keep jobs whose title or JD text contains any configured keyword/title.

    No keywords/titles configured ⇒ keep everything (the source already scoped it).
    """
    terms = _terms(search)
    if not terms:
        return jobs
    kept = []
    for job in jobs:
        haystack = f"{job.title or ''}\n{job.jd_text}".lower()
        if any(term in haystack for term in terms):
            kept.append(job)
    return kept
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_text.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/text.py tests/test_connectors_text.py
git commit -m "feat(connectors): shared html_to_text + keyword filter" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `ConnectorsConfig` + example file

**Files:**

- Create: `src/resume_agent/discovery/connectors/config.py`, `config/connectors.yaml.example`
- Test: `tests/test_connectors_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_config.py`:

```python
from pathlib import Path

from resume_agent.discovery.connectors.config import ConnectorsConfig, load_connectors_config


def test_defaults_are_all_disabled():
    cfg = ConnectorsConfig()
    assert cfg.greenhouse.enabled is False
    assert cfg.adzuna.enabled is False
    assert cfg.remoteok.enabled is False
    assert cfg.linkedin.enabled is False


def test_loads_example_file():
    example = Path("config/connectors.yaml.example")
    cfg = load_connectors_config(example)
    assert cfg.greenhouse.enabled is True
    assert cfg.greenhouse.boards[0].token == "stripe"
    assert cfg.adzuna.country == "us"


def test_board_company_defaults_to_token():
    cfg = ConnectorsConfig.model_validate({"greenhouse": {"boards": [{"token": "acme"}]}})
    board = cfg.greenhouse.boards[0]
    assert board.company is None  # resolved at use-site via board.display()
    assert board.display() == "acme"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.config'`.

- [ ] **Step 3: Implement the config model**

Create `src/resume_agent/discovery/connectors/config.py`:

```python
from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class GreenhouseBoard(ExtensibleModel):
    token: str  # the board slug, e.g. "stripe"
    company: str | None = None  # display name; falls back to the token

    def display(self) -> str:
        return self.company or self.token


class GreenhouseConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[GreenhouseBoard] = Field(default_factory=list)


class AdzunaConfig(ExtensibleModel):
    enabled: bool = False
    country: str = "us"


class RemoteOKConfig(ExtensibleModel):
    enabled: bool = False


class LinkedInConfig(ExtensibleModel):
    enabled: bool = False


class ConnectorsConfig(ExtensibleModel):
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)


def load_connectors_config(path: str | Path) -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(load_yaml(path))
```

- [ ] **Step 4: Create the example file**

Create `config/connectors.yaml.example`:

```yaml
# Which job-source connectors `resume-agent pull` runs, and their parameters.
# Copy to config/connectors.yaml and edit. Secrets (Adzuna keys) go in .env.

greenhouse: # ATS boards — company-scoped; lists ALL open roles per board.
  enabled: true
  boards:
    - token: stripe # board slug from boards.greenhouse.io/<slug>
      company: Stripe # optional display name (defaults to the token)
    - token: airbnb
      company: Airbnb

adzuna: # keyword aggregator (needs ADZUNA_APP_ID / ADZUNA_APP_KEY in .env)
  enabled: true
  country: us

remoteok: # remote-jobs feed (no auth)
  enabled: true

linkedin: # the v1 scraper; opt-in (brittle, needs a burner session)
  enabled: false
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/connectors/config.py config/connectors.yaml.example tests/test_connectors_config.py
git commit -m "feat(connectors): connectors.yaml config model + example" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Greenhouse connector

**Files:**

- Create: `tests/fixtures/greenhouse/jobs.json`, `src/resume_agent/discovery/connectors/greenhouse.py`
- Test: `tests/test_connector_greenhouse.py`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/greenhouse/jobs.json`:

```json
{
  "jobs": [
    {
      "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1",
      "title": "Senior Backend Engineer",
      "location": { "name": "Remote - US" },
      "content": "&lt;p&gt;Build &lt;b&gt;payment&lt;/b&gt; systems in Python.&lt;/p&gt;"
    },
    {
      "absolute_url": "https://boards.greenhouse.io/stripe/jobs/2",
      "title": "Office Manager",
      "location": { "name": "San Francisco" },
      "content": "&lt;p&gt;Run the front desk.&lt;/p&gt;"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_connector_greenhouse.py`:

```python
import json
from pathlib import Path

from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector, parse_greenhouse
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "greenhouse" / "jobs.json").read_text())


def test_parse_greenhouse_maps_and_decodes_content():
    jobs = parse_greenhouse(FIXTURE, company="Stripe")
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "greenhouse"
    assert first.company == "Stripe"
    assert first.title == "Senior Backend Engineer"
    assert first.location == "Remote - US"
    assert first.url == "https://boards.greenhouse.io/stripe/jobs/1"
    assert "payment" in first.jd_text and "<" not in first.jd_text


class _FakeGreenhouse(GreenhouseConnector):
    def _get_board(self, token):
        return FIXTURE


def test_connector_fetches_boards_and_filters_by_search():
    connector = _FakeGreenhouse([GreenhouseBoard(token="stripe", company="Stripe")])
    jobs = connector.fetch(SearchConfig(keywords=["python"]))
    assert {j.title for j in jobs} == {"Senior Backend Engineer"}  # Office Manager filtered out
    assert connector.name == "greenhouse"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_connector_greenhouse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.greenhouse'`.

- [ ] **Step 4: Implement**

Create `src/resume_agent/discovery/connectors/greenhouse.py`:

```python
import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://boards-api.greenhouse.io/v1/boards"


def parse_greenhouse(payload: dict, company: str) -> list[RawJob]:
    """Map a Greenhouse board `jobs` payload (content=true) to RawJobs."""
    jobs: list[RawJob] = []
    for j in payload.get("jobs", []):
        location = (j.get("location") or {}).get("name")
        jobs.append(
            RawJob(
                source="greenhouse",
                url=j.get("absolute_url"),
                company=company,
                title=j.get("title"),
                location=location,
                jd_text=html_to_text(j.get("content", "")),
            )
        )
    return jobs


class GreenhouseConnector:
    """Pulls every open role from each configured Greenhouse board, then keyword-filters."""

    name = "greenhouse"

    def __init__(self, boards: list[GreenhouseBoard]):
        self.boards = boards

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs: list[RawJob] = []
        for board in self.boards:
            jobs.extend(parse_greenhouse(self._get_board(board.token), board.display()))
        jobs = filter_by_search(jobs, search)
        return jobs[:limit] if limit is not None else jobs

    def _get_board(self, token: str) -> dict:  # the only un-CI-tested line
        resp = httpx.get(f"{_BASE}/{token}/jobs", params={"content": "true"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_connector_greenhouse.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/greenhouse/ src/resume_agent/discovery/connectors/greenhouse.py tests/test_connector_greenhouse.py
git commit -m "feat(connectors): Greenhouse ATS connector" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Adzuna connector

**Files:**

- Modify: `src/resume_agent/config.py` (Settings), `.env.example`
- Create: `tests/fixtures/adzuna/search.json`, `src/resume_agent/discovery/connectors/adzuna.py`
- Test: `tests/test_connector_adzuna.py`

- [ ] **Step 1: Add Adzuna credentials to Settings and `.env.example`**

In `src/resume_agent/config.py`, add these two fields to `class Settings` after `github_token`:

```python
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
```

In `.env.example`, add:

```dotenv
# Adzuna API credentials for the aggregator connector.
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

- [ ] **Step 2: Create the fixture**

Create `tests/fixtures/adzuna/search.json`:

```json
{
  "results": [
    {
      "redirect_url": "https://www.adzuna.com/jobs/1",
      "title": "Backend Engineer",
      "company": { "display_name": "Acme Corp" },
      "location": { "display_name": "Remote, US" },
      "description": "Work on distributed systems in Python and Go."
    },
    {
      "redirect_url": "https://www.adzuna.com/jobs/2",
      "title": "Platform Engineer",
      "company": { "display_name": "Beta Inc" },
      "location": { "display_name": "London, UK" },
      "description": "Operate Kubernetes clusters."
    }
  ]
}
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_connector_adzuna.py`:

```python
import json
from pathlib import Path

from resume_agent.discovery.connectors.adzuna import AdzunaConnector, parse_adzuna
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "adzuna" / "search.json").read_text())


def test_parse_adzuna_maps_nested_company_and_location():
    jobs = parse_adzuna(FIXTURE)
    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "adzuna"
    assert first.company == "Acme Corp"
    assert first.location == "Remote, US"
    assert first.url == "https://www.adzuna.com/jobs/1"
    assert "Python" in first.jd_text


class _FakeAdzuna(AdzunaConnector):
    def _get_results(self, search):
        return FIXTURE


def test_connector_filters_by_search():
    connector = _FakeAdzuna(app_id="x", app_key="y", country="us")
    jobs = connector.fetch(SearchConfig(keywords=["kubernetes"]))
    assert {j.title for j in jobs} == {"Platform Engineer"}
    assert connector.name == "adzuna"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_connector_adzuna.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.adzuna'`.

- [ ] **Step 5: Implement**

Create `src/resume_agent/discovery/connectors/adzuna.py`:

```python
import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.adzuna.com/v1/api/jobs"


def parse_adzuna(payload: dict) -> list[RawJob]:
    """Map an Adzuna search payload to RawJobs."""
    jobs: list[RawJob] = []
    for r in payload.get("results", []):
        jobs.append(
            RawJob(
                source="adzuna",
                url=r.get("redirect_url"),
                company=(r.get("company") or {}).get("display_name"),
                title=r.get("title"),
                location=(r.get("location") or {}).get("display_name"),
                jd_text=r.get("description", ""),
            )
        )
    return jobs


class AdzunaConnector:
    """Keyword aggregator. One search call; results filtered client-side too."""

    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, country: str = "us"):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs = filter_by_search(parse_adzuna(self._get_results(search)), search)
        return jobs[:limit] if limit is not None else jobs

    def _get_results(self, search: SearchConfig) -> dict:  # the only un-CI-tested line
        terms = list(
            dict.fromkeys(t.strip() for t in [*search.titles, *search.keywords] if t.strip())
        )
        what = " ".join(terms)
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": what,
            "results_per_page": 50,
        }
        if search.locations:
            params["where"] = search.locations[0]
        resp = httpx.get(f"{_BASE}/{self.country}/search/1", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_connector_adzuna.py tests/test_config.py -v`
Expected: PASS (Adzuna tests + existing config tests still green).

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/config.py .env.example tests/fixtures/adzuna/ src/resume_agent/discovery/connectors/adzuna.py tests/test_connector_adzuna.py
git commit -m "feat(connectors): Adzuna aggregator connector" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: RemoteOK connector

**Files:**

- Create: `tests/fixtures/remoteok/api.json`, `src/resume_agent/discovery/connectors/remoteok.py`
- Test: `tests/test_connector_remoteok.py`

- [ ] **Step 1: Create the fixture**

> RemoteOK's API returns a JSON array whose **first element is a legal/metadata object** (no `position` key) — the parser must skip it.

Create `tests/fixtures/remoteok/api.json`:

```json
[
  { "legal": "See https://remoteok.com/api for terms" },
  {
    "id": "1001",
    "url": "https://remoteok.com/remote-jobs/1001",
    "company": "Acme",
    "position": "Backend Engineer",
    "location": "Worldwide",
    "description": "<p>Build APIs in Python.</p>"
  },
  {
    "id": "1002",
    "url": "https://remoteok.com/remote-jobs/1002",
    "company": "Beta",
    "position": "Frontend Engineer",
    "location": "",
    "description": "<p>React and TypeScript.</p>"
  }
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_connector_remoteok.py`:

```python
import json
from pathlib import Path

from resume_agent.discovery.connectors.remoteok import RemoteOKConnector, parse_remoteok
from resume_agent.discovery.search_config import SearchConfig

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "remoteok" / "api.json").read_text())


def test_parse_remoteok_skips_legal_header_and_maps_jobs():
    jobs = parse_remoteok(FIXTURE)
    assert len(jobs) == 2  # legal header skipped
    first = jobs[0]
    assert first.source == "remoteok"
    assert first.title == "Backend Engineer"
    assert first.company == "Acme"
    assert first.location == "Worldwide"
    assert "Python" in first.jd_text and "<" not in first.jd_text


def test_parse_remoteok_defaults_blank_location_to_remote():
    jobs = parse_remoteok(FIXTURE)
    assert jobs[1].location == "Remote"


class _FakeRemoteOK(RemoteOKConnector):
    def _get_all(self):
        return FIXTURE


def test_connector_filters_by_search():
    connector = _FakeRemoteOK()
    jobs = connector.fetch(SearchConfig(keywords=["react"]))
    assert {j.title for j in jobs} == {"Frontend Engineer"}
    assert connector.name == "remoteok"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_connector_remoteok.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.remoteok'`.

- [ ] **Step 4: Implement**

Create `src/resume_agent/discovery/connectors/remoteok.py`:

```python
import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text
from resume_agent.discovery.search_config import SearchConfig

_URL = "https://remoteok.com/api"


def parse_remoteok(payload: list) -> list[RawJob]:
    """Map the RemoteOK API array to RawJobs, skipping the legal header element."""
    jobs: list[RawJob] = []
    for item in payload:
        if not isinstance(item, dict) or "position" not in item:
            continue  # the first element is a legal/metadata object
        jobs.append(
            RawJob(
                source="remoteok",
                url=item.get("url"),
                company=item.get("company"),
                title=item.get("position"),
                location=item.get("location") or "Remote",
                jd_text=html_to_text(item.get("description", "")),
            )
        )
    return jobs


class RemoteOKConnector:
    """Remote-jobs feed. One GET returns everything; filtered client-side."""

    name = "remoteok"

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs = filter_by_search(parse_remoteok(self._get_all()), search)
        return jobs[:limit] if limit is not None else jobs

    def _get_all(self) -> list:  # the only un-CI-tested line
        resp = httpx.get(_URL, headers={"User-Agent": "resume-agent"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_connector_remoteok.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/remoteok/ src/resume_agent/discovery/connectors/remoteok.py tests/test_connector_remoteok.py
git commit -m "feat(connectors): RemoteOK feed connector" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `build_connectors` registry

**Files:**

- Create: `src/resume_agent/discovery/connectors/registry.py`
- Test: `tests/test_connectors_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_registry.py`:

```python
from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.registry import build_connectors


def _cfg(**enabled):
    data = {
        "greenhouse": {"enabled": enabled.get("greenhouse", False), "boards": [{"token": "stripe"}]},
        "adzuna": {"enabled": enabled.get("adzuna", False)},
        "remoteok": {"enabled": enabled.get("remoteok", False)},
        "linkedin": {"enabled": enabled.get("linkedin", False)},
    }
    return ConnectorsConfig.model_validate(data)


def test_only_enabled_connectors_are_built():
    cfg = _cfg(greenhouse=True, remoteok=True)
    names = [c.name for c in build_connectors(cfg, Settings())]
    assert names == ["greenhouse", "remoteok"]  # canonical order, adzuna/linkedin off


def test_canonical_order_is_ats_feed_aggregator_linkedin():
    cfg = _cfg(greenhouse=True, adzuna=True, remoteok=True, linkedin=True)
    settings = Settings(adzuna_app_id="x", adzuna_app_key="y")
    names = [c.name for c in build_connectors(cfg, settings)]
    assert names == ["greenhouse", "remoteok", "adzuna", "linkedin"]


def test_adzuna_skipped_without_credentials():
    cfg = _cfg(adzuna=True)
    names = [c.name for c in build_connectors(cfg, Settings())]  # no keys
    assert names == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.discovery.connectors.registry'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/discovery/connectors/registry.py`:

```python
from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.base import Connector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper


def build_connectors(config: ConnectorsConfig, settings: Settings) -> list[Connector]:
    """Instantiate enabled connectors in canonical dedup order: ATS → feed → aggregator → LinkedIn.

    A connector that is enabled but unauthenticated (e.g. Adzuna without keys) is
    skipped rather than erroring — `pull` simply runs the sources it can.
    """
    connectors: list[Connector] = []

    if config.greenhouse.enabled and config.greenhouse.boards:
        connectors.append(GreenhouseConnector(config.greenhouse.boards))

    if config.remoteok.enabled:
        connectors.append(RemoteOKConnector())

    if config.adzuna.enabled and settings.adzuna_app_id and settings.adzuna_app_key:
        connectors.append(
            AdzunaConnector(settings.adzuna_app_id, settings.adzuna_app_key, config.adzuna.country)
        )

    if config.linkedin.enabled:
        connectors.append(build_linkedin_scraper())

    return connectors
```

- [ ] **Step 4: Run test, then the full suite**

Run: `uv run pytest tests/test_connectors_registry.py -v`
Expected: PASS (3 tests).

Run: `uv run pytest -q`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/registry.py tests/test_connectors_registry.py
git commit -m "feat(connectors): build_connectors registry (canonical order)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.2, Decisions #3/#9/#10):** Greenhouse (ATS, company-scoped via `boards`) — Task 3; Adzuna (aggregator, `.env` keys) — Task 4; RemoteOK (feed) — Task 5; `connectors.yaml` + model — Task 2; `build_connectors` in canonical dedup order with credential-gating — Task 6. Client-side keyword filtering for the company-/feed-scoped sources — Task 1, used by all three.

**Placeholder scan:** none — every mapper, connector, fixture, and config is shown in full.

**Type consistency:** every `parse_*` returns `list[RawJob]`; every connector exposes `name: str` + `fetch(search, limit=None) -> list[RawJob]` (matches the Plan 1 `Connector` protocol and the registry's `list[Connector]`). `GreenhouseBoard.display()` is defined in Task 2 and used in Tasks 3/registry. `Settings.adzuna_app_id/app_key` defined in Task 4, read in Task 6. `filter_by_search`/`html_to_text` signatures defined in Task 1 match all call sites.

**Deferred (noted, not built):** Lever/Ashby (copy `greenhouse.py`, swap endpoint + mapper), WeWorkRemotely (RSS via `feedparser` — new dep), HN Who's-Hiring (Algolia). Each is one mapper + one registry line behind the same seam.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-agent-v2-reference-connectors.md`. Execute via **superpowers:subagent-driven-development** (fresh subagent per task) or **superpowers:executing-plans** (inline, checkpointed). Next plan in the spine: **Plan 3 — `pull` + `sources`** (the ordered multi-connector run that uses `build_connectors`).
