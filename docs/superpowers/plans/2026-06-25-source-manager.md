# Source Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web Sources page to view/add/remove/enable-disable the recurring job sources in `connectors.yaml` and pull/re-pull one or all of them, with a live per-source `added / upgraded / skipped / failed` breakdown.

**Architecture:** A new `services/sources.py` use-case layer reads and atomically rewrites `config/connectors.yaml` (the same file the CLI uses — one source of truth). Pull selection is a **config projection + per-entry connector fan-out**: each enabled board/URL becomes its own single-entry connector whose `.name` is a stable source id, so the existing `run_pull` loop yields per-source telemetry for free and "pull one" and "pull all" share one code path. A new `api/routers/sources.py` exposes CRUD + preview; `POST /api/pull` gains an optional `sourceIds`. The React SPA gets a `/sources` route reusing the existing run/SSE infrastructure.

**Tech Stack:** Python 3 / FastAPI / SQLModel / Pydantic v2 (`CamelModel`), PyYAML, httpx; React + Vite + TypeScript, `openapi-fetch`, `@tanstack/react-query`, shadcn-style UI primitives, Playwright.

**Spec:** `docs/superpowers/specs/2026-06-25-source-manager-design.md`

## Global Constraints

- **Wire format is camelCase.** All API request/response schemas extend `CamelModel` (`api/schemas/base.py`); Python stays snake_case; DTO→schema is `Model.model_validate(row)`.
- **Source enabled vs pullable are distinct.** `enabled` is the persisted user toggle in `connectors.yaml`; `pullable` is derived runtime readiness (for example Adzuna requires both `enabled` and API credentials). UI rows may be enabled but not pullable, and must disable selection/per-row pull in that state.
- **Tests are offline.** No API key, no network. Fake every agent/browser/connector seam. Run with `.venv/Scripts/python.exe -m pytest`.
- **Config models extend `ExtensibleModel`** (`resume_agent/models/base.py`) — keep that base for any new config model.
- **Back-compatibility of `connectors.yaml` is mandatory.** Existing files (bare-string `companies.urls`, boards without `enabled`) must keep loading unchanged.
- **YAML writes are atomic** (temp file + `os.replace`) and use PyYAML (`yaml.safe_dump(..., sort_keys=False)`). Comment loss on UI write is accepted (per spec decision #9).
- **Default connectors path:** `config/connectors.yaml` (the existing `DEFAULT_CONNECTORS` constant in `services/discovery.py`).
- **Contract is generated, not hand-written.** After any schema change run `bash scripts/gen_ts_client.sh` (regenerates `contracts/openapi.json`, `contracts/ts/api.ts`, and copies to `web/src/lib/api/schema.ts`). `tests/api/test_openapi_contract.py` is a drift gate.
- **Lint:** `ruff check` must pass.

---

### Task 1: Config schema — per-entry `enabled` + `CompanyUrl`

**Files:**
- Modify: `src/resume_agent/discovery/connectors/config.py`
- Modify: `src/resume_agent/discovery/connectors/registry.py:12-36`
- Test: `tests/test_connectors_config.py`, `tests/test_connectors_registry.py`

**Interfaces:**
- Produces: `GreenhouseBoard.enabled: bool`, `LeverBoard.enabled: bool` (default `True`); `CompanyUrl(ExtensibleModel)` with `url: str`, `enabled: bool = True`, `label: str | None`; `CompaniesConfig.urls: list[CompanyUrl]` with a `mode="before"` validator coercing a bare string into `{"url": <string>}`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_connectors_config.py`, add:

```python
from resume_agent.discovery.connectors.config import (
    CompaniesConfig,
    CompanyUrl,
    GreenhouseConfig,
)


def test_company_url_accepts_bare_string_for_backcompat():
    cfg = CompaniesConfig.model_validate({"enabled": True, "urls": ["https://x.co"]})
    assert cfg.urls == [CompanyUrl(url="https://x.co", enabled=True, label=None)]


def test_company_url_accepts_object_form():
    cfg = CompaniesConfig.model_validate(
        {"enabled": True, "urls": [{"url": "https://x.co", "enabled": False, "label": "X"}]}
    )
    assert cfg.urls[0].enabled is False
    assert cfg.urls[0].label == "X"


def test_board_enabled_defaults_true_when_absent():
    cfg = GreenhouseConfig.model_validate({"enabled": True, "boards": [{"token": "anthropic"}]})
    assert cfg.boards[0].enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_config.py -v`
Expected: FAIL — `CompanyUrl` does not exist / bare string not coerced.

- [ ] **Step 3: Implement the schema**

In `src/resume_agent/discovery/connectors/config.py`, add `enabled: bool = True` to `GreenhouseBoard` and `LeverBoard`, and replace `CompaniesConfig`:

```python
from pydantic import Field, field_validator


class CompanyUrl(ExtensibleModel):
    url: str
    enabled: bool = True
    label: str | None = None


class CompaniesConfig(ExtensibleModel):
    enabled: bool = False
    urls: list[CompanyUrl] = Field(default_factory=list)

    @field_validator("urls", mode="before")
    @classmethod
    def _coerce_bare_strings(cls, value):
        if isinstance(value, list):
            return [{"url": v} if isinstance(v, str) else v for v in value]
        return value
```

Add `enabled: bool = True` to `GreenhouseBoard` and `LeverBoard` (keep `token`, `company`, `display()`).

- [ ] **Step 4: Keep the registry building (companies now holds objects)**

In `src/resume_agent/discovery/connectors/registry.py`, update the three board/url branches to project to enabled entries:

```python
    if config.greenhouse.enabled:
        boards = [b for b in config.greenhouse.boards if b.enabled]
        if boards:
            connectors.append(GreenhouseConnector(boards))

    if config.lever.enabled:
        boards = [b for b in config.lever.boards if b.enabled]
        if boards:
            connectors.append(LeverConnector(boards))

    if config.companies.enabled:
        urls = [u.url for u in config.companies.urls if u.enabled]
        if urls:
            connectors.append(CompaniesConnector(urls))
```

- [ ] **Step 5: Run config + registry tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_config.py tests/test_connectors_registry.py -v`
Expected: PASS (existing registry tests still green — they use boards without `enabled`, which now defaults `True`).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/connectors/config.py src/resume_agent/discovery/connectors/registry.py tests/test_connectors_config.py
git commit -m "feat(sources): per-entry enabled flag + CompanyUrl object form (back-compat)"
```

---

### Task 2: Source identity + views + projection (pure helpers)

**Files:**
- Create: `src/resume_agent/discovery/connectors/sources.py`
- Test: `tests/test_connector_sources.py`

**Interfaces:**
- Consumes: `ConnectorsConfig` (Task 1), `Settings`, `identify_host` (`discovery/connectors/detect.py:163`).
- Produces:
  - `@dataclass(frozen=True) SourceView` with `id: str`, `kind: str`, `type: str` (`"board"|"aggregator"`), `display_name: str`, `enabled: bool`, `pullable: bool`, `detail: str`.
  - `company_url_id(url: str) -> str` → `"companies:" + sha1(url)[:8]`.
  - `list_source_views(config: ConnectorsConfig, settings: Settings) -> list[SourceView]`.
  - Selection is implemented directly in `build_source_connectors` (Task 3), so this module stays a pure identity/read-model helper and does not construct throwaway `Settings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_connector_sources.py`:

```python
from typing import Any, cast

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
)


def _settings(**kw):
    return cast(Any, Settings)(_env_file=None, **kw)


def _cfg():
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "anthropic", "company": "Anthropic"}]},
            "lever": {"enabled": True, "boards": [{"token": "zoox", "company": "Zoox", "enabled": False}]},
            "companies": {"enabled": True, "urls": [{"url": "https://jobs.ashbyhq.com/openai", "label": "OpenAI"}]},
            "adzuna": {"enabled": True, "country": "us"},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": False},
        }
    )


def test_company_url_id_is_stable_and_prefixed():
    assert company_url_id("https://x.co").startswith("companies:")
    assert company_url_id("https://x.co") == company_url_id("https://x.co")


def test_list_source_views_covers_boards_and_aggregators():
    views = list_source_views(_cfg(), _settings(adzuna_app_id="a", adzuna_app_key="b"))
    by_id = {v.id: v for v in views}

    assert by_id["greenhouse:anthropic"] == SourceView(
        id="greenhouse:anthropic", kind="greenhouse", type="board",
        display_name="Anthropic", enabled=True, pullable=True, detail="anthropic",
    )
    # disabled lever board still listed, enabled=False
    assert by_id["lever:zoox"].enabled is False
    # companies entry: kind derived from URL host (ashby), display from label
    ohid = company_url_id("https://jobs.ashbyhq.com/openai")
    assert by_id[ohid].kind == "ashby"
    assert by_id[ohid].display_name == "OpenAI"
    # aggregators present with fixed ids
    assert by_id["adzuna"].type == "aggregator"
    assert "key set" in by_id["adzuna"].detail
    assert by_id["adzuna"].pullable is True
    assert by_id["remoteok"].type == "aggregator"
    assert by_id["linkedin"].enabled is False
    assert by_id["linkedin"].pullable is False


def test_adzuna_without_keys_is_enabled_but_not_pullable():
    views = list_source_views(_cfg(), _settings())
    adzuna = next(v for v in views if v.id == "adzuna")
    assert adzuna.enabled is True
    assert adzuna.pullable is False
    assert "no API key" in adzuna.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_sources.py -v`
Expected: FAIL — module `sources` not found.

- [ ] **Step 3: Implement the helpers**

Create `src/resume_agent/discovery/connectors/sources.py`:

```python
"""Source identity + read-only projections over ConnectorsConfig.

Pure: no network, no file IO. The web Source Manager and per-source pull both
read entry identity from here so ids stay consistent across list, pull, and
mutate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.detect import identify_host


@dataclass(frozen=True)
class SourceView:
    id: str
    kind: str
    type: str  # "board" | "aggregator"
    display_name: str
    enabled: bool
    pullable: bool
    detail: str


def company_url_id(url: str) -> str:
    return "companies:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def _company_kind(url: str) -> str:
    target = identify_host(url)  # pure, no network
    return target.ats if target is not None else "companies"


def list_source_views(config: ConnectorsConfig, settings: Settings) -> list[SourceView]:
    views: list[SourceView] = []

    for board in config.greenhouse.boards:
        views.append(SourceView(
            id=f"greenhouse:{board.token}", kind="greenhouse", type="board",
            display_name=board.display(), enabled=board.enabled, pullable=board.enabled,
            detail=board.token,
        ))
    for board in config.lever.boards:
        views.append(SourceView(
            id=f"lever:{board.token}", kind="lever", type="board",
            display_name=board.display(), enabled=board.enabled, pullable=board.enabled,
            detail=board.token,
        ))
    for entry in config.companies.urls:
        views.append(SourceView(
            id=company_url_id(entry.url), kind=_company_kind(entry.url), type="board",
            display_name=entry.label or entry.url, enabled=entry.enabled, pullable=entry.enabled,
            detail=entry.url,
        ))

    key_set = bool(settings.adzuna_app_id and settings.adzuna_app_key)
    views.append(SourceView(
        id="adzuna", kind="adzuna", type="aggregator", display_name="Adzuna",
        enabled=config.adzuna.enabled, pullable=config.adzuna.enabled and key_set,
        detail=f"{config.adzuna.country.upper()} · {'key set' if key_set else 'no API key'}",
    ))
    views.append(SourceView(
        id="remoteok", kind="remoteok", type="aggregator", display_name="RemoteOK",
        enabled=config.remoteok.enabled, pullable=config.remoteok.enabled, detail="aggregator",
    ))
    views.append(SourceView(
        id="linkedin", kind="linkedin", type="aggregator", display_name="LinkedIn",
        enabled=config.linkedin.enabled, pullable=config.linkedin.enabled, detail="scraper",
    ))
    return views
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/sources.py tests/test_connector_sources.py
git commit -m "feat(sources): stable source ids + SourceView projection helpers"
```

---

### Task 3: Per-entry connector fan-out (the telemetry-granularity change)

**Files:**
- Modify: `src/resume_agent/discovery/connectors/registry.py`
- Test: `tests/test_connectors_registry.py`

**Interfaces:**
- Consumes: `ConnectorsConfig`, `Settings`, `SourceView` ids (Task 2), connector classes.
- Produces: `build_source_connectors(config: ConnectorsConfig, settings: Settings, source_ids: list[str] | None = None) -> list[Connector]` — one connector per **enabled, selected** entry, each with its instance `.name` set to the stable source id (boards/companies) or the fixed aggregator id. Order: greenhouse boards, lever boards, companies urls, remoteok, adzuna, linkedin.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_connectors_registry.py`:

```python
from resume_agent.discovery.connectors.registry import build_source_connectors


def _full_cfg():
    return ConnectorsConfig.model_validate({
        "greenhouse": {"enabled": True, "boards": [
            {"token": "anthropic"}, {"token": "scaleai", "enabled": False}]},
        "companies": {"enabled": True, "urls": [{"url": "https://jobs.ashbyhq.com/openai"}]},
        "remoteok": {"enabled": True},
        "adzuna": {"enabled": False},
        "linkedin": {"enabled": False},
    })


def test_build_source_connectors_is_one_per_enabled_entry():
    names = [c.name for c in build_source_connectors(_full_cfg(), _settings())]
    # scaleai disabled, adzuna disabled
    assert names == ["greenhouse:anthropic",
                     "companies:" + __import__("hashlib").sha1(b"https://jobs.ashbyhq.com/openai").hexdigest()[:8],
                     "remoteok"]


def test_build_source_connectors_honors_explicit_selection():
    names = [c.name for c in build_source_connectors(_full_cfg(), _settings(), source_ids=["remoteok"])]
    assert names == ["remoteok"]


def test_build_source_connectors_skips_adzuna_without_keys():
    cfg = ConnectorsConfig.model_validate({
        "adzuna": {"enabled": True, "country": "us"},
        "remoteok": {"enabled": False},
        "linkedin": {"enabled": False},
    })
    names = [c.name for c in build_source_connectors(cfg, _settings())]
    assert "adzuna" not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py -v`
Expected: FAIL — `build_source_connectors` not defined.

- [ ] **Step 3: Implement `build_source_connectors`**

Append to `src/resume_agent/discovery/connectors/registry.py`:

```python
from resume_agent.discovery.connectors.sources import company_url_id


def _named(connector: Connector, source_id: str) -> Connector:
    connector.name = source_id  # instance attr shadows the class-level name
    return connector


def build_source_connectors(
    config: ConnectorsConfig,
    settings: Settings,
    source_ids: list[str] | None = None,
) -> list[Connector]:
    """One single-entry connector per enabled, pullable, selected source.

    Each connector's ``name`` is the stable source id, so ``run_pull`` keys
    telemetry per entry. ``source_ids=None`` selects every enabled + pullable entry.
    """
    selected = set(source_ids) if source_ids is not None else None  # None means "all pullable enabled"

    def picked(source_id: str, enabled: bool, pullable: bool = True) -> bool:
        if not enabled or not pullable:
            return False
        return selected is None or source_id in selected

    connectors: list[Connector] = []

    if config.greenhouse.enabled:
        for board in config.greenhouse.boards:
            sid = f"greenhouse:{board.token}"
            if picked(sid, board.enabled):
                connectors.append(_named(GreenhouseConnector([board]), sid))

    if config.lever.enabled:
        for board in config.lever.boards:
            sid = f"lever:{board.token}"
            if picked(sid, board.enabled):
                connectors.append(_named(LeverConnector([board]), sid))

    if config.companies.enabled:
        for entry in config.companies.urls:
            sid = company_url_id(entry.url)
            if picked(sid, entry.enabled):
                connectors.append(_named(CompaniesConnector([entry.url]), sid))

    if picked("remoteok", config.remoteok.enabled):
        connectors.append(_named(RemoteOKConnector(), "remoteok"))

    adzuna_pullable = bool(settings.adzuna_app_id and settings.adzuna_app_key)
    if picked("adzuna", config.adzuna.enabled, adzuna_pullable):
        connectors.append(_named(
            AdzunaConnector(settings.adzuna_app_id, settings.adzuna_app_key, config.adzuna.country),
            "adzuna",
        ))

    if picked("linkedin", config.linkedin.enabled):
        connectors.append(_named(build_linkedin_scraper(), "linkedin"))

    return connectors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/registry.py tests/test_connectors_registry.py
git commit -m "feat(sources): build_source_connectors — one connector per entry with id name"
```

---

### Task 4: Count `skipped` in ingest

**Files:**
- Modify: `src/resume_agent/discovery/ingest.py:30-34,127-165`
- Test: `tests/test_discovery_ingest.py`

**Interfaces:**
- Produces: `IngestCounts.skipped: dict[str, int]`; `ingest_jobs_with_outcomes` tallies the `IngestOutcome.skipped` branch per `raw.source`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_discovery_ingest.py` (follow the file's existing fixtures for building `RawJob`s and a session):

```python
def test_skipped_outcome_is_counted(session):
    from resume_agent.discovery.connectors.base import RawJob
    from resume_agent.discovery.ingest import ingest_jobs_with_outcomes

    job = RawJob(source="greenhouse", url="https://x/1", company="Acme",
                 title="AI Engineer", location="Remote", jd_text="Build agents.")
    first = ingest_jobs_with_outcomes(session, [job])
    assert first.added.get("greenhouse") == 1
    # Same job, same source/tier on re-pull -> first-seen-wins skip.
    again = ingest_jobs_with_outcomes(session, [job])
    assert again.added.get("greenhouse", 0) == 0
    assert again.skipped.get("greenhouse") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_ingest.py::test_skipped_outcome_is_counted -v`
Expected: FAIL — `IngestCounts` has no attribute `skipped`.

- [ ] **Step 3: Implement the counter**

In `src/resume_agent/discovery/ingest.py`:

Add `skipped: dict[str, int]` to the `IngestCounts` dataclass (after `upgraded`). In `ingest_jobs_with_outcomes`, add `skipped: Counter[str] = Counter()` next to the others, add the branch, and include it in the return:

```python
        elif outcome is IngestOutcome.skipped:
            skipped[raw.source] += 1
    return IngestCounts(
        added=dict(added),
        upgraded=dict(upgraded),
        skipped=dict(skipped),
        changed_raw_job_ids=changed_raw_job_ids,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/ingest.py tests/test_discovery_ingest.py
git commit -m "feat(sources): count skipped (first-seen-wins) ingest outcomes"
```

---

### Task 5: Carry `upgraded` + `skipped` on `PullReport`

**Files:**
- Modify: `src/resume_agent/discovery/connectors/runner.py:13-23,60-82`
- Test: `tests/test_connectors_runner.py`

**Interfaces:**
- Consumes: `IngestCounts.skipped` (Task 4).
- Produces: `PullReport.upgraded: dict[str, int]`, `PullReport.skipped: dict[str, int]`, populated per connector in `run_pull`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_connectors_runner.py` (mirror the file's existing fake-connector style — a connector returning a `FetchResult`):

```python
def test_run_pull_reports_upgraded_and_skipped(session, tmp_path):
    from resume_agent.discovery.connectors.base import FetchResult, RawJob
    from resume_agent.discovery.connectors.runner import run_pull
    from resume_agent.discovery.search_config import SearchConfig

    job = RawJob(source="greenhouse", url="https://x/1", company="Acme",
                 title="AI Engineer", location="Remote", jd_text="Build agents.")

    class OneBoard:
        name = "greenhouse:acme"
        def fetch(self, search, limit=None):
            return FetchResult(jobs=[job])

    search = SearchConfig.model_validate({})
    run_pull(session, [OneBoard()], search, tmp_path / "t.json")
    report = run_pull(session, [OneBoard()], search, tmp_path / "t.json")  # re-pull -> skip
    assert report.skipped.get("greenhouse:acme") == 1
    assert report.totals.get("greenhouse:acme") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_runner.py::test_run_pull_reports_upgraded_and_skipped -v`
Expected: FAIL — `PullReport` has no `skipped`.

- [ ] **Step 3: Implement the report fields**

In `src/resume_agent/discovery/connectors/runner.py`, add to `PullReport`:

```python
    upgraded: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
```

Update `_run_note` to accept `skipped_count` and include it when non-zero. Also rename the existing fetch-failure text from "skipped source(s)" to "failed source(s)" so duplicate skips are not confused with fetch failures:

```python
def _run_note(
    result: FetchResult,
    added_count: int,
    upgraded_count: int,
    skipped_count: int,
) -> str | None:
    """Non-fatal note: upgrades, duplicate skips, skipped sub-sources, and filters."""
    if not result.filtered and not result.failures and not upgraded_count and not skipped_count:
        return None
    parts: list[str] = [f"+{added_count} added"]
    if upgraded_count:
        parts.append(f"{upgraded_count} upgraded")
    if skipped_count:
        parts.append(f"{skipped_count} skipped")
    if result.filtered:
        parts.append(f"filtered {result.filtered} off-target")
    if result.failures:
        items = ", ".join(f"{name} ({reason})" for name, reason in result.failures.items())
        parts.append(f"failed {len(result.failures)} source(s): {items}")
    return "; ".join(parts)
```

Add a small payload helper so partial SSE progress and final run results share one shape:

```python
def _pull_result(report: PullReport) -> dict[str, object]:
    return {
        "totals": report.totals,
        "upgraded": report.upgraded,
        "skipped": report.skipped,
        "failures": report.failures,
    }
```

In `run_pull`, after computing `upgraded_count`, add the skipped lookup and store all three (the `.get(connector.name, sum(...))` fallback already yields the single-entry total):

```python
            skipped_count = summary.skipped.get(connector.name, sum(summary.skipped.values()))
            report.totals[connector.name] = added_count
            report.upgraded[connector.name] = upgraded_count
            report.skipped[connector.name] = skipped_count
```

Update the `record_run` call to pass `skipped_count`, and publish the partial source result through the existing progress record after each connector:

```python
            record_run(
                telemetry_path,
                connector.name,
                added=added_count,
                error=_run_note(result, added_count, upgraded_count, skipped_count),
            )
...
        if reporter:
            reporter.step(index, added=added_total, result=_pull_result(report))
    if reporter and finish:
        reporter.done(added=added_total, result=_pull_result(report))
```

- [ ] **Step 4: Run runner + ingest tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_runner.py tests/test_discovery_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/runner.py tests/test_connectors_runner.py
git commit -m "feat(sources): PullReport carries per-source upgraded + skipped counts"
```

---

### Task 6: `pull_jobs(source_ids=...)` uses per-entry fan-out

**Files:**
- Modify: `src/resume_agent/services/discovery.py:105-122`
- Test: `tests/test_services_discovery_pull.py` (create if absent)

**Interfaces:**
- Consumes: `build_source_connectors` (Task 3), `PullReport` (Task 5).
- Produces: `pull_jobs(session, *, source_ids: list[str] | None = None, ...)` — builds connectors via `build_source_connectors`; `None` pulls all enabled and pullable entries.

- [ ] **Step 1: Write the failing test**

Create `tests/test_services_discovery_pull.py`:

```python
from resume_agent.services import discovery


def test_pull_jobs_passes_source_ids_to_per_entry_build(session, tmp_path, monkeypatch):
    captured = {}

    def fake_build(config, settings, source_ids=None):
        captured["source_ids"] = source_ids
        return []  # no connectors -> empty pull

    monkeypatch.setattr(discovery, "build_source_connectors", fake_build)
    discovery.pull_jobs(session, source_ids=["greenhouse:anthropic"])
    assert captured["source_ids"] == ["greenhouse:anthropic"]
```

> If `session` / `tmp_path` config-path fixtures differ in this repo, reuse the harness already used by `tests/test_connectors_runner.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery_pull.py -v`
Expected: FAIL — `pull_jobs` has no `source_ids`; `discovery.build_source_connectors` not imported.

- [ ] **Step 3: Implement**

In `src/resume_agent/services/discovery.py`, change the import from `registry` to bring in `build_source_connectors`, and update `pull_jobs`:

```python
from resume_agent.discovery.connectors.registry import build_source_connectors


def pull_jobs(
    session: Session,
    *,
    search_path: str = DEFAULT_SEARCH,
    connectors_path: str = DEFAULT_CONNECTORS,
    telemetry_path: str = CONNECTOR_RUNS_PATH,
    limit: int | None = None,
    source_ids: list[str] | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
) -> PullReport:
    """Run the selected (or all enabled + pullable) per-entry connectors and ingest results."""
    search_config = load_search_config(search_path)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_source_connectors(connectors_config, get_settings(), source_ids=source_ids)
    return run_pull(
        session, connectors, search_config, telemetry_path,
        limit=limit, reporter=reporter, finish=finish,
    )
```

- [ ] **Step 4: Run discovery + a refresh test to verify nothing regressed**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_discovery_pull.py tests/test_connectors_runner.py -v`
Expected: PASS. (`refresh_jobs` calls `pull_jobs` with no `source_ids` → all enabled, unchanged behavior.)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/discovery.py tests/test_services_discovery_pull.py
git commit -m "feat(sources): pull_jobs(source_ids=...) selects via per-entry fan-out"
```

---

### Task 7: `services/sources.py` — list / add / toggle / remove (atomic YAML)

**Files:**
- Create: `src/resume_agent/services/sources.py`
- Test: `tests/test_services_sources.py`

**Interfaces:**
- Consumes: `ConnectorsConfig`, `load_connectors_config`, `list_source_views`, `company_url_id`, `detect_ats`, `DEFAULT_CONNECTORS`.
- Produces:
  - `list_sources(connectors_path=DEFAULT_CONNECTORS, settings=None) -> list[SourceView]`
  - `add_source(url: str, label: str | None = None, connectors_path=DEFAULT_CONNECTORS) -> SourceView`
  - `set_source_enabled(source_id: str, enabled: bool, connectors_path=DEFAULT_CONNECTORS) -> SourceView`
  - `remove_source(source_id: str, connectors_path=DEFAULT_CONNECTORS) -> None`
  - raises `SourceError(message)` (mapped to a 400 by the router) for not-found / undetectable or failed preview / duplicate.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services_sources.py`:

```python
import textwrap

import pytest

from resume_agent.services import sources as svc


def _write(tmp_path, body: str) -> str:
    p = tmp_path / "connectors.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


BASE = """
greenhouse: {enabled: true, boards: [{token: anthropic, company: Anthropic}]}
lever: {enabled: true, boards: []}
companies: {enabled: true, urls: ["https://jobs.ashbyhq.com/openai"]}
adzuna: {enabled: true, country: us}
remoteok: {enabled: true}
linkedin: {enabled: false}
"""


def test_add_greenhouse_url_writes_typed_board(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    from resume_agent.discovery.connectors.detect import AtsTarget
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget("greenhouse", "cohere"))
    view = svc.add_source("https://job-boards.greenhouse.io/cohere", connectors_path=path)
    assert view.id == "greenhouse:cohere"
    reloaded = {v.id for v in svc.list_sources(path)}
    assert "greenhouse:cohere" in reloaded


def test_add_unknown_ats_falls_to_companies(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    monkeypatch.setattr(svc, "detect_ats", lambda url: __import__(
        "resume_agent.discovery.connectors.detect", fromlist=["AtsTarget"]).AtsTarget("workday", tenant="gm", datacenter="wd5", site="Careers"))
    view = svc.add_source("https://gm.wd5.myworkdayjobs.com/Careers", label="GM", connectors_path=path)
    assert view.detail == "https://gm.wd5.myworkdayjobs.com/Careers"
    assert view.display_name == "GM"


def test_add_undetectable_raises(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    monkeypatch.setattr(svc, "detect_ats", lambda url: None)
    with pytest.raises(svc.SourceError):
        svc.add_source("https://nope.example", connectors_path=path)


def test_set_enabled_and_remove(tmp_path):
    path = _write(tmp_path, BASE)
    svc.set_source_enabled("greenhouse:anthropic", False, connectors_path=path)
    assert next(v for v in svc.list_sources(path) if v.id == "greenhouse:anthropic").enabled is False
    svc.remove_source("greenhouse:anthropic", connectors_path=path)
    assert "greenhouse:anthropic" not in {v.id for v in svc.list_sources(path)}


def test_remove_unknown_raises(tmp_path):
    path = _write(tmp_path, BASE)
    with pytest.raises(svc.SourceError):
        svc.remove_source("greenhouse:ghost", connectors_path=path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py -v`
Expected: FAIL — module `services.sources` not found.

- [ ] **Step 3: Implement the service**

Create `src/resume_agent/services/sources.py`:

```python
"""Source Manager use-case layer: read + atomically rewrite connectors.yaml.

The same file the CLI reads, so the UI and `resume-agent pull` agree. Writes are
atomic (temp + os.replace) so a concurrent pull never sees a torn file. Comments
are not preserved (PyYAML) — accepted per design.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from resume_agent.config import Settings, get_settings
from resume_agent.discovery.connectors.config import (
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import detect_ats
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
)
from resume_agent.services.discovery import DEFAULT_CONNECTORS


class SourceError(Exception):
    """A source mutation the user must fix (undetectable URL, duplicate, missing id)."""


def _save(path: str, config: ConnectorsConfig) -> None:
    data = config.model_dump(mode="python")
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, target)


def list_sources(connectors_path: str = DEFAULT_CONNECTORS, settings: Settings | None = None) -> list[SourceView]:
    return list_source_views(load_connectors_config(connectors_path), settings or get_settings())


def _view(config: ConnectorsConfig, source_id: str) -> SourceView:
    for v in list_source_views(config, Settings(_env_file=None)):
        if v.id == source_id:
            return v
    raise SourceError(f"Unknown source '{source_id}'")


def add_source(url: str, label: str | None = None, connectors_path: str = DEFAULT_CONNECTORS) -> SourceView:
    config = load_connectors_config(connectors_path)
    target = detect_ats(url)
    if target is None:
        raise SourceError("Could not detect a known ATS behind this URL.")

    if target.ats == "greenhouse" and target.token:
        if any(b.token == target.token for b in config.greenhouse.boards):
            raise SourceError(f"Greenhouse board '{target.token}' is already a source.")
        config.greenhouse.enabled = True
        config.greenhouse.boards.append(GreenhouseBoard(token=target.token, company=label))
        new_id = f"greenhouse:{target.token}"
    elif target.ats == "lever" and target.token:
        if any(b.token == target.token for b in config.lever.boards):
            raise SourceError(f"Lever board '{target.token}' is already a source.")
        config.lever.enabled = True
        config.lever.boards.append(LeverBoard(token=target.token, company=label))
        new_id = f"lever:{target.token}"
    else:
        if any(u.url == url for u in config.companies.urls):
            raise SourceError("This URL is already a source.")
        config.companies.enabled = True
        config.companies.urls.append(CompanyUrl(url=url, label=label))
        new_id = company_url_id(url)

    _save(connectors_path, config)
    return _view(config, new_id)


def set_source_enabled(source_id: str, enabled: bool, connectors_path: str = DEFAULT_CONNECTORS) -> SourceView:
    config = load_connectors_config(connectors_path)
    if not _apply_enabled(config, source_id, enabled):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)
    return _view(config, source_id)


def remove_source(source_id: str, connectors_path: str = DEFAULT_CONNECTORS) -> None:
    config = load_connectors_config(connectors_path)
    if not _remove(config, source_id):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)


def _apply_enabled(config: ConnectorsConfig, source_id: str, enabled: bool) -> bool:
    if source_id == "adzuna":
        config.adzuna.enabled = enabled; return True
    if source_id == "remoteok":
        config.remoteok.enabled = enabled; return True
    if source_id == "linkedin":
        config.linkedin.enabled = enabled; return True
    for board in config.greenhouse.boards:
        if f"greenhouse:{board.token}" == source_id:
            board.enabled = enabled; return True
    for board in config.lever.boards:
        if f"lever:{board.token}" == source_id:
            board.enabled = enabled; return True
    for entry in config.companies.urls:
        if company_url_id(entry.url) == source_id:
            entry.enabled = enabled; return True
    return False


def _remove(config: ConnectorsConfig, source_id: str) -> bool:
    before_g = len(config.greenhouse.boards)
    config.greenhouse.boards = [b for b in config.greenhouse.boards if f"greenhouse:{b.token}" != source_id]
    if len(config.greenhouse.boards) != before_g:
        return True
    before_l = len(config.lever.boards)
    config.lever.boards = [b for b in config.lever.boards if f"lever:{b.token}" != source_id]
    if len(config.lever.boards) != before_l:
        return True
    before_c = len(config.companies.urls)
    config.companies.urls = [u for u in config.companies.urls if company_url_id(u.url) != source_id]
    return len(config.companies.urls) != before_c
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/sources.py tests/test_services_sources.py
git commit -m "feat(sources): list/add/toggle/remove service with atomic YAML write"
```

---

### Task 8: `preview_source` — detect + bounded test-fetch

**Files:**
- Modify: `src/resume_agent/services/sources.py`
- Test: `tests/test_services_sources_preview.py`

**Interfaces:**
- Consumes: `detect_ats`, `build_source_connectors`-style single-entry fetch, `load_search_config`.
- Produces: `@dataclass(frozen=True) SourcePreview` with `ok: bool`, `url: str`, `kind: str | None`, `token: str | None`, `label: str | None`, `role_count: int | None`, `error: str | None`; and `preview_source(url: str, label: str | None = None) -> SourcePreview`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services_sources_preview.py`:

```python
import pytest

from resume_agent.services import sources as svc
from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.detect import AtsTarget


def test_preview_undetectable_is_not_ok(monkeypatch):
    monkeypatch.setattr(svc, "detect_ats", lambda url: None)
    p = svc.preview_source("https://nope.example")
    assert p.ok is False and p.error


def test_preview_counts_roles_from_test_fetch(monkeypatch):
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget("greenhouse", "cohere"))

    class FakeConn:
        name = "greenhouse:cohere"
        def fetch(self, search, limit=None):
            return FetchResult(jobs=[RawJob("greenhouse", "u", "Cohere", "AI Eng", "Remote", "jd")])

    monkeypatch.setattr(svc, "_preview_connector", lambda target, url: FakeConn())
    p = svc.preview_source("https://job-boards.greenhouse.io/cohere", label="Cohere")
    assert p.ok is True
    assert p.kind == "greenhouse"
    assert p.token == "cohere"
    assert p.role_count == 1


def test_add_source_requires_successful_preview(tmp_path, monkeypatch):
    path = tmp_path / "connectors.yaml"
    path.write_text("greenhouse: {enabled: true, boards: []}\ncompanies: {enabled: true, urls: []}\n")
    monkeypatch.setattr(
        svc,
        "preview_source",
        lambda url, label=None: svc.SourcePreview(ok=False, url=url, error="preview failed"),
    )
    with pytest.raises(svc.SourceError, match="preview failed"):
        svc.add_source("https://nope.example", connectors_path=str(path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources_preview.py -v`
Expected: FAIL — `preview_source` not defined.

- [ ] **Step 3: Implement preview**

Add to `src/resume_agent/services/sources.py`:

```python
from dataclasses import dataclass

from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.search_config import load_search_config
from resume_agent.services.discovery import DEFAULT_SEARCH

_PREVIEW_LIMIT = 50


@dataclass(frozen=True)
class SourcePreview:
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None


def _preview_connector(target: AtsTarget, url: str):
    if target.ats == "greenhouse" and target.token:
        return GreenhouseConnector([GreenhouseBoard(token=target.token)])
    if target.ats == "lever" and target.token:
        return LeverConnector([LeverBoard(token=target.token)])
    return CompaniesConnector([url])


def preview_source(url: str, label: str | None = None, search_path: str = DEFAULT_SEARCH) -> SourcePreview:
    target = detect_ats(url)
    if target is None:
        return SourcePreview(ok=False, url=url, error="Could not detect a known ATS behind this URL.")
    try:
        result = _preview_connector(target, url).fetch(load_search_config(search_path), limit=_PREVIEW_LIMIT)
    except Exception as exc:  # noqa: BLE001 — preview must never raise to the user
        return SourcePreview(ok=False, url=url, kind=target.ats, token=target.token or None,
                             error=f"Could not reach this source: {type(exc).__name__}")
    if result.failures and not result.jobs:
        reason = "; ".join(result.failures.values())
        return SourcePreview(ok=False, url=url, kind=target.ats, token=target.token or None, error=reason)
    return SourcePreview(ok=True, url=url, kind=target.ats, token=target.token or None,
                         label=label, role_count=len(result.jobs))
```

Then tighten `add_source` so the service, not only the dialog, enforces the same detection + bounded test-fetch before saving:

```python
def add_source(url: str, label: str | None = None, connectors_path: str = DEFAULT_CONNECTORS) -> SourceView:
    preview = preview_source(url, label=label)
    if not preview.ok:
        raise SourceError(preview.error or "Could not validate this source.")

    config = load_connectors_config(connectors_path)
    target = detect_ats(url)
    if target is None:
        raise SourceError("Could not detect a known ATS behind this URL.")

    if target.ats == "greenhouse" and target.token:
        if any(b.token == target.token for b in config.greenhouse.boards):
            raise SourceError(f"Greenhouse board '{target.token}' is already a source.")
        config.greenhouse.enabled = True
        config.greenhouse.boards.append(GreenhouseBoard(token=target.token, company=label))
        new_id = f"greenhouse:{target.token}"
    elif target.ats == "lever" and target.token:
        if any(b.token == target.token for b in config.lever.boards):
            raise SourceError(f"Lever board '{target.token}' is already a source.")
        config.lever.enabled = True
        config.lever.boards.append(LeverBoard(token=target.token, company=label))
        new_id = f"lever:{target.token}"
    else:
        if any(u.url == url for u in config.companies.urls):
            raise SourceError("This URL is already a source.")
        config.companies.enabled = True
        config.companies.urls.append(CompanyUrl(url=url, label=label))
        new_id = company_url_id(url)

    _save(connectors_path, config)
    return _view(config, new_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources_preview.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/sources.py tests/test_services_sources_preview.py
git commit -m "feat(sources): preview_source — detect + bounded test-fetch, never raises"
```

---

### Task 9: API schemas — sources + `PullParams.sourceIds`

**Files:**
- Create: `src/resume_agent/api/schemas/sources.py`
- Modify: `src/resume_agent/api/schemas/runs.py:33-34`
- Test: `tests/api/test_schemas_sources.py`

**Interfaces:**
- Consumes: `SourceView`, `SourcePreview` (Tasks 2, 8) via `model_validate` (`from_attributes`).
- Produces: `SourceOut`, `SourcePreviewIn{url}`, `SourcePreviewOut`, `AddSourceIn{url, label?}`, `SetEnabledIn{enabled}` (all `CamelModel`); `PullParams.source_ids: list[str] | None = None`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_schemas_sources.py`:

```python
from resume_agent.api.schemas.sources import SourceOut, SourcePreviewOut
from resume_agent.discovery.connectors.sources import SourceView
from resume_agent.services.sources import SourcePreview


def test_source_out_projects_view_with_camel_alias():
    view = SourceView(id="greenhouse:x", kind="greenhouse", type="board",
                      display_name="X", enabled=True, pullable=True, detail="x")
    dumped = SourceOut.model_validate(view).model_dump(by_alias=True)
    assert dumped["displayName"] == "X"
    assert dumped["pullable"] is True
    assert dumped["type"] == "board"


def test_preview_out_projects_dataclass():
    p = SourcePreview(ok=True, url="u", kind="greenhouse", token="x", role_count=3)
    dumped = SourcePreviewOut.model_validate(p).model_dump(by_alias=True)
    assert dumped["roleCount"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_sources.py -v`
Expected: FAIL — schema module not found.

- [ ] **Step 3: Implement the schemas**

Create `src/resume_agent/api/schemas/sources.py`:

```python
"""Source Manager wire schemas (camelCase via CamelModel)."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SourceOut(CamelModel):
    id: str
    kind: str
    type: str
    display_name: str
    enabled: bool
    pullable: bool
    detail: str


class SourcePreviewIn(CamelModel):
    url: str
    label: str | None = None


class SourcePreviewOut(CamelModel):
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None


class AddSourceIn(CamelModel):
    url: str
    label: str | None = None


class SetEnabledIn(CamelModel):
    enabled: bool
```

In `src/resume_agent/api/schemas/runs.py`, extend `PullParams`:

```python
class PullParams(CamelModel):
    limit: int | None = None
    source_ids: list[str] | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/schemas/sources.py src/resume_agent/api/schemas/runs.py tests/api/test_schemas_sources.py
git commit -m "feat(sources): API schemas + PullParams.sourceIds"
```

---

### Task 10: Sources router + pull wiring + app registration

**Files:**
- Create: `src/resume_agent/api/routers/sources.py`
- Modify: `src/resume_agent/api/routers/runs.py:109-123`
- Modify: `src/resume_agent/api/app.py:16-22,82-89`
- Test: `tests/api/test_sources_router.py`

**Interfaces:**
- Consumes: `services.sources` (Tasks 7, 8), `SourceError`, schemas (Task 9), `pull_jobs(source_ids=...)` (Task 6).
- Produces: routes `GET /api/sources`, `POST /api/sources/preview`, `POST /api/sources`, `PATCH /api/sources/{source_id}`, `DELETE /api/sources/{source_id}`; `POST /api/pull` honors `sourceIds`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_sources_router.py`:

```python
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import sources as sources_router


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_list_sources_returns_views(monkeypatch):
    from resume_agent.discovery.connectors.sources import SourceView
    monkeypatch.setattr(sources_router, "list_sources",
                        lambda **kw: [SourceView("remoteok", "remoteok", "aggregator", "RemoteOK", True, True, "aggregator")])
    client = _client()
    with client:
        body = client.get("/api/sources").json()
    assert body[0]["id"] == "remoteok"
    assert body[0]["displayName"] == "RemoteOK"


def test_preview_endpoint(monkeypatch):
    from resume_agent.services.sources import SourcePreview
    monkeypatch.setattr(sources_router, "preview_source",
                        lambda url, label=None: SourcePreview(ok=True, url=url, kind="ashby", role_count=7))
    client = _client()
    with client:
        body = client.post("/api/sources/preview", json={"url": "https://jobs.ashbyhq.com/x"}).json()
    assert body["ok"] is True and body["roleCount"] == 7


def test_add_source_error_maps_to_400(monkeypatch):
    from resume_agent.services.sources import SourceError
    def boom(url, label=None, **kw):
        raise SourceError("nope")
    monkeypatch.setattr(sources_router, "add_source", boom)
    client = _client()
    with client:
        resp = client.post("/api/sources", json={"url": "x"})
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "nope"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_sources_router.py -v`
Expected: FAIL — router module not found.

- [ ] **Step 3: Implement the router**

Create `src/resume_agent/api/routers/sources.py`:

```python
"""Source Manager CRUD + preview. Thin adapter over services/sources.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.sources import (
    AddSourceIn,
    SetEnabledIn,
    SourceOut,
    SourcePreviewIn,
    SourcePreviewOut,
)
from resume_agent.config import Settings
from resume_agent.services.sources import (
    SourceError,
    add_source,
    list_sources,
    preview_source,
    remove_source,
    set_source_enabled,
)

router = APIRouter()


def _guard(call):
    try:
        return call()
    except SourceError as exc:
        raise ApiException(400, "SOURCE_ERROR", str(exc)) from exc


@router.get("/sources", response_model=list[SourceOut])
def list_sources_route(settings: Settings = Depends(get_settings_dep)):
    return [SourceOut.model_validate(v) for v in list_sources(settings=settings)]


@router.post("/sources/preview", response_model=SourcePreviewOut)
def preview_source_route(body: SourcePreviewIn):
    return SourcePreviewOut.model_validate(preview_source(body.url, label=body.label))


@router.post("/sources", response_model=SourceOut, status_code=201)
def add_source_route(body: AddSourceIn):
    return SourceOut.model_validate(_guard(lambda: add_source(body.url, label=body.label)))


@router.patch("/sources/{source_id}", response_model=SourceOut)
def set_enabled_route(source_id: str, body: SetEnabledIn):
    return SourceOut.model_validate(_guard(lambda: set_source_enabled(source_id, body.enabled)))


@router.delete("/sources/{source_id}", status_code=204)
def remove_source_route(source_id: str):
    _guard(lambda: remove_source(source_id))
```

- [ ] **Step 4: Wire pull `sourceIds` and register the router**

In `src/resume_agent/api/routers/runs.py`, update `launch_pull`'s `work`:

```python
        report = pull_jobs(session, limit=params.limit, source_ids=params.source_ids, reporter=reporter)
        return {
            "totals": report.totals,
            "upgraded": report.upgraded,
            "skipped": report.skipped,
            "failures": report.failures,
        }
```

In `src/resume_agent/api/app.py`, add the import beside the other routers and include it with the guarded routers:

```python
from resume_agent.api.routers import sources as sources_router
...
    app.include_router(sources_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 5: Run router tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_sources_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/routers/sources.py src/resume_agent/api/routers/runs.py src/resume_agent/api/app.py tests/api/test_sources_router.py
git commit -m "feat(sources): sources router + pull sourceIds + app registration"
```

---

### Task 11: Regenerate the API contract + extend the drift gate

**Files:**
- Modify: `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` (generated)
- Modify: `tests/api/test_openapi_contract.py:9-14`

**Interfaces:**
- Produces: committed contract that includes `/api/sources` paths, so the SPA's typed client can call them.

- [ ] **Step 1: Add the new path to the drift-gate assertion**

In `tests/api/test_openapi_contract.py`, add `"/api/sources"` to the tuple in `test_openapi_exposes_core_paths`.

- [ ] **Step 2: Regenerate the contract + TS client**

Run: `bash scripts/gen_ts_client.sh`
Expected: rewrites `contracts/openapi.json`, `contracts/ts/api.ts`, and copies to `web/src/lib/api/schema.ts`. (Requires Node/`npx`. If offline without Node, run `.venv/Scripts/python.exe scripts/export_openapi.py` to refresh `openapi.json`, and regenerate the TS in Task 12's environment.)

- [ ] **Step 3: Run the contract test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS — committed contract matches the live app and exposes `/api/sources`.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts tests/api/test_openapi_contract.py
git commit -m "chore(sources): regenerate OpenAPI + TS client for /api/sources"
```

---

### Task 12: Full backend gate (no regressions)

**Files:** none (verification task)

- [ ] **Step 1: Run the whole Python suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS. Pay attention to `tests/test_connectors_runner.py`, `tests/test_ingest_jobs.py`, `tests/api/test_runs_launch.py` — the per-entry fan-out changed pull telemetry granularity.

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: clean. Fix any findings and re-run.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "test(sources): backend suite + lint green"
```

---

### Task 13: Frontend — sources data hooks + pull launcher

**Files:**
- Create: `web/src/features/sources/use-sources.ts`
- Modify: `web/src/features/runs/use-launch-run.ts:64-72`
- Modify: `web/src/lib/runs/store.ts`
- Modify: `web/src/lib/runs/sse.ts`
- Test: `web/src/features/sources/use-sources.test.tsx`

**Interfaces:**
- Consumes: generated `api` client (`/api/sources*`, `/api/pull`), `@tanstack/react-query`, `useLaunchRun`, the existing run SSE stream.
- Produces: `useSources()` query; `useAddSource()`, `useSetEnabled()`, `useRemoveSource()` mutations (invalidate `["sources"]`); `previewSource(url, label?)`; a `pullSources(ids)` launcher entry; `RunRecord.result` preserved from SSE so the Sources page can render the live/final per-source breakdown.

- [ ] **Step 1: Add the `pullSources` launcher**

In `web/src/features/runs/use-launch-run.ts`, add to the `launchers` object:

```typescript
  pullSources: (sourceIds: string[] | null, opts: PullOptions = {}) =>
    unwrap(api.POST("/api/pull", { body: { limit: opts.limit ?? null, sourceIds } })),
```

In `web/src/lib/runs/store.ts`, preserve the run result payload:

```typescript
export type PullRunResult = {
  totals?: Record<string, number>;
  upgraded?: Record<string, number>;
  skipped?: Record<string, number>;
  failures?: Record<string, Record<string, string>>;
};

export interface RunRecord {
  runId: string;
  kind: string;
  status: "running" | "succeeded" | "failed" | "cancelled";
  percent: number;
  phase: string;
  current: number;
  total: number;
  etaText: string | null;
  error?: string;
  result?: PullRunResult | Record<string, unknown> | null;
}
```

In `web/src/lib/runs/sse.ts`, import the result type, then parse and store `result` from each SSE frame:

```typescript
import { useRunStore, type PullRunResult, type RunRecord } from "./store";

    let data: {
      state?: string;
      percent?: number;
      label?: string;
      current?: number;
      total?: number;
      etaText?: string | null;
      error?: string;
      result?: PullRunResult | Record<string, unknown> | null;
    };
    useRunStore.getState().upsert({
      runId,
      kind,
      status,
      percent: typeof data.percent === "number" ? data.percent : 0,
      phase: data.label ?? "",
      current: typeof data.current === "number" ? data.current : 0,
      total: typeof data.total === "number" ? data.total : 0,
      etaText: data.etaText ?? null,
      error: data.error ?? undefined,
      result: data.result ?? null,
    });
```

- [ ] **Step 2: Write the failing hook test**

Create `web/src/features/sources/use-sources.test.tsx` (mirror the MSW/react-query setup used in `web/src/features/runs/use-bulk-run.test.tsx`):

```tsx
import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useSources } from "./use-sources";
import { withQueryClient } from "@/test/utils"; // existing test helper; adjust path to match repo

describe("useSources", () => {
  it("loads the source list", async () => {
    const { result } = renderHook(() => useSources(), { wrapper: withQueryClient });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(Array.isArray(result.current.data)).toBe(true);
  });
});
```

> If the repo has no shared `withQueryClient`/MSW helper, copy the provider + handler wiring from `use-bulk-run.test.tsx` and stub `GET /api/sources` to return `[]`.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npm run test -- use-sources`
Expected: FAIL — `use-sources` module not found.

- [ ] **Step 4: Implement the hooks**

Create `web/src/features/sources/use-sources.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

export type Source = {
  id: string;
  kind: string;
  type: "board" | "aggregator";
  displayName: string;
  enabled: boolean;
  pullable: boolean;
  detail: string;
};

export type Preview = {
  ok: boolean;
  url: string;
  kind?: string | null;
  token?: string | null;
  label?: string | null;
  roleCount?: number | null;
  error?: string | null;
};

export function useSources() {
  return useQuery({
    queryKey: ["sources"],
    queryFn: () => unwrap(api.GET("/api/sources")) as Promise<Source[]>,
  });
}

export function previewSource(url: string, label?: string | null): Promise<Preview> {
  return unwrap(
    api.POST("/api/sources/preview", { body: { url, label: label ?? null } }),
  ) as Promise<Preview>;
}

export function useAddSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { url: string; label?: string | null }) =>
      unwrap(api.POST("/api/sources", { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useSetEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      unwrap(api.PATCH("/api/sources/{source_id}", {
        params: { path: { source_id: id } }, body: { enabled },
      })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useRemoveSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/sources/{source_id}", { params: { path: { source_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && npm run test -- use-sources`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/sources/use-sources.ts web/src/features/sources/use-sources.test.tsx web/src/features/runs/use-launch-run.ts
git commit -m "feat(web): sources data hooks + pullSources launcher"
```

---

### Task 14: Frontend — Add Source dialog (preview + add)

**Files:**
- Create: `web/src/features/sources/AddSourceDialog.tsx`
- Test: `web/src/features/sources/AddSourceDialog.test.tsx`

**Interfaces:**
- Consumes: `previewSource`, `useAddSource` (Task 13), UI primitives (`dialog`, `button`, `input`, `label`).
- Produces: `<AddSourceDialog />` — paste URL → Preview → shows detected kind + role count or error → Add (enabled only after a successful preview).

- [ ] **Step 1: Write the failing test**

Create `web/src/features/sources/AddSourceDialog.test.tsx` (mirror existing component tests; stub `POST /api/sources/preview` to return `{ok:true, kind:"ashby", roleCount:7}`):

```tsx
import { describe, expect, it } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AddSourceDialog } from "./AddSourceDialog";
import { withQueryClient } from "@/test/utils";

describe("AddSourceDialog", () => {
  it("enables Add only after a successful preview", async () => {
    render(<AddSourceDialog />, { wrapper: withQueryClient });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    fireEvent.change(screen.getByLabelText(/careers or board URL/i), {
      target: { value: "https://jobs.ashbyhq.com/x" },
    });
    fireEvent.click(screen.getByText("Preview"));
    await waitFor(() => expect(screen.getByText(/7 roles/i)).toBeInTheDocument());
    const addButtons = screen.getAllByRole("button", { name: "Add source" });
    expect(addButtons[addButtons.length - 1]).not.toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm run test -- AddSourceDialog`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the dialog**

Create `web/src/features/sources/AddSourceDialog.tsx`:

```tsx
import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { previewSource, useAddSource, type Preview } from "./use-sources";

export function AddSourceDialog() {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const add = useAddSource();

  const reset = () => { setUrl(""); setLabel(""); setPreview(null); };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset(); }}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <Plus className="size-4" aria-hidden="true" />
        Add source
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Add a job source</DialogTitle></DialogHeader>

        <Label htmlFor="src-url">Careers or board URL</Label>
        <Input id="src-url" value={url} placeholder="https://…"
          onChange={(e) => { setUrl(e.target.value); setPreview(null); }} />

        <Label htmlFor="src-label">Display name (optional)</Label>
        <Input id="src-label" value={label} onChange={(e) => setLabel(e.target.value)} />

        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled={!url.trim() || previewing}
            onClick={async () => {
              setPreviewing(true);
              try { setPreview(await previewSource(url.trim(), label.trim() || null)); }
              finally { setPreviewing(false); }
            }}>
            {previewing ? "Checking…" : "Preview"}
          </Button>

          {preview?.ok && (
            <span className="text-sm text-muted-foreground">
              {preview.kind} · {preview.roleCount ?? 0} roles
            </span>
          )}
          {preview && !preview.ok && (
            <span className="text-sm text-destructive">{preview.error}</span>
          )}
        </div>

        <Button disabled={!preview?.ok || add.isPending}
          onClick={async () => {
            try {
              await add.mutateAsync({ url: url.trim(), label: label.trim() || null });
              setOpen(false); reset();
            } catch (e) { toast.error((e as Error).message); }
          }}>
          Add source
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm run test -- AddSourceDialog`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/sources/AddSourceDialog.tsx web/src/features/sources/AddSourceDialog.test.tsx
git commit -m "feat(web): Add Source dialog with live preview"
```

---

### Task 15: Frontend — Sources page, route, and nav

**Files:**
- Create: `web/src/features/sources/SourcesPage.tsx`
- Modify: `web/src/app/router.tsx:6-46`
- Modify: `web/src/app/AppLayout.tsx:1-37`
- Test: `web/src/features/sources/SourcesPage.test.tsx`

**Interfaces:**
- Consumes: `useSources`, `useSetEnabled`, `useRemoveSource` (Task 13), `useLaunchRun` + `launchers.pullSources` (Task 13), `<AddSourceDialog />` (Task 14), UI primitives (`switch`, `badge`, `checkbox`, `button`) and existing card surface tokens.
- Produces: `<SourcesPage />` exported; route `path: "sources"`; nav entry `{ to: "/sources", label: "Sources", icon: Radar }`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/sources/SourcesPage.test.tsx` (stub `GET /api/sources` → one pullable board + one non-pullable Adzuna aggregator with `detail: "US · no API key"`):

```tsx
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { SourcesPage } from "./SourcesPage";
import { useRunStore } from "@/lib/runs/store";
import { withQueryClient } from "@/test/utils";

describe("SourcesPage", () => {
  beforeEach(() => {
    useRunStore.setState({ runs: {} });
  });

  it("renders boards and aggregators sections", async () => {
    render(<SourcesPage />, { wrapper: withQueryClient });
    await waitFor(() => expect(screen.getByText(/Boards & careers pages/i)).toBeInTheDocument());
    expect(screen.getByText(/Aggregators/i)).toBeInTheDocument();
  });

  it("disables pull controls for non-pullable sources", async () => {
    render(<SourcesPage />, { wrapper: withQueryClient });
    await waitFor(() => expect(screen.getByText(/no API key/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Pull Adzuna/i })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /Select Adzuna/i })).toBeDisabled();
  });

  it("renders the latest per-source pull result", async () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "pull",
      status: "running",
      percent: 50,
      phase: "Pulling greenhouse:anthropic",
      current: 1,
      total: 2,
      etaText: null,
      result: {
        totals: { "greenhouse:anthropic": 3 },
        upgraded: { "greenhouse:anthropic": 1 },
        skipped: { "greenhouse:anthropic": 8 },
        failures: {},
      },
    });
    render(<SourcesPage />, { wrapper: withQueryClient });
    await waitFor(() => expect(screen.getByText(/Latest pull result/i)).toBeInTheDocument());
    expect(screen.getByText("+3 added")).toBeInTheDocument();
    expect(screen.getByText("1 upd")).toBeInTheDocument();
    expect(screen.getByText("8 skip")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm run test -- SourcesPage`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the page**

Create `web/src/features/sources/SourcesPage.tsx`:

```tsx
import { useState } from "react";
import { Play, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { PageHeader } from "@/components/PageHeader";
import { useLaunchRun, launchers } from "@/features/runs/use-launch-run";
import { useRunStore, type PullRunResult } from "@/lib/runs/store";
import { AddSourceDialog } from "./AddSourceDialog";
import {
  useSources, useSetEnabled, useRemoveSource, type Source,
} from "./use-sources";

function Row({ source, checked, onToggleCheck }: {
  source: Source; checked: boolean; onToggleCheck: (id: string) => void;
}) {
  const setEnabled = useSetEnabled();
  const remove = useRemoveSource();
  const { launch } = useLaunchRun();
  const disabled = !source.pullable;
  return (
    <li className="flex min-h-12 items-center gap-3 border-b py-2" aria-disabled={disabled}>
      <Checkbox
        checked={checked}
        disabled={disabled}
        aria-label={`Select ${source.displayName}`}
        onCheckedChange={() => onToggleCheck(source.id)}
      />
      <span className="min-w-0 flex-1 truncate font-medium">{source.displayName}</span>
      <Badge variant="outline">{source.kind}</Badge>
      <span className="hidden w-48 truncate text-xs text-muted-foreground md:inline">{source.detail}</span>
      <Switch aria-label={`Enable ${source.displayName}`} checked={source.enabled}
        onCheckedChange={(v) => setEnabled.mutate({ id: source.id, enabled: v })} />
      <Button size="sm" variant="secondary"
        aria-label={`Pull ${source.displayName}`}
        disabled={disabled}
        onClick={() => launch("pull", () => launchers.pullSources([source.id]), ["shortlist", "pipeline", "triage", "sources"])}>
        <Play className="size-3.5" aria-hidden="true" />
        Pull
      </Button>
      {source.type === "board" && (
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label={`Remove ${source.displayName}`}
          onClick={() => remove.mutate(source.id)}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </Button>
      )}
    </li>
  );
}

function SourceResultPanel({ sources }: { sources: Source[] }) {
  const runsMap = useRunStore((s) => s.runs);
  const latestPull = Object.values(runsMap)
    .reverse()
    .find((r) => r.kind === "pull" && r.result);
  const result = latestPull?.result as PullRunResult | undefined;
  if (!result) return null;

  const labels = new Map(sources.map((s) => [s.id, s.displayName]));
  const ids = new Set([
    ...Object.keys(result.totals ?? {}),
    ...Object.keys(result.upgraded ?? {}),
    ...Object.keys(result.skipped ?? {}),
    ...Object.keys(result.failures ?? {}),
  ]);

  return (
    <section aria-labelledby="sources-results" className="rounded-lg border bg-card p-4">
      <h2 id="sources-results" className="text-sm font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        Latest pull result
      </h2>
      <ul className="mt-3 divide-y">
        {[...ids].map((id) => {
          const failed = Object.keys(result.failures?.[id] ?? {}).length;
          return (
            <li key={id} className="grid gap-2 py-2 text-sm md:grid-cols-[minmax(0,1fr)_repeat(4,auto)] md:items-center">
              <span className="truncate font-medium">{labels.get(id) ?? id}</span>
              <span className="tabular-nums">+{result.totals?.[id] ?? 0} added</span>
              <span className="tabular-nums">{result.upgraded?.[id] ?? 0} upd</span>
              <span className="tabular-nums">{result.skipped?.[id] ?? 0} skip</span>
              <span className={failed ? "text-destructive" : "text-muted-foreground"}>
                {failed ? `${failed} failed` : "0 failed"}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function SourcesPage() {
  const { data = [], isLoading } = useSources();
  const { launch } = useLaunchRun();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const boards = data.filter((s) => s.type === "board");
  const aggregators = data.filter((s) => s.type === "aggregator");

  return (
    <div className="space-y-6">
      <PageHeader title="Sources" description="Manage the boards and careers pages you pull from." />

      <div className="flex flex-wrap items-center gap-2">
        <AddSourceDialog />
        <Button variant="outline" size="sm" disabled={selected.size === 0}
          onClick={() => launch("pull", () => launchers.pullSources([...selected]), ["shortlist", "pipeline", "triage", "sources"])}>
          Pull selected ({selected.size})
        </Button>
        <Button size="sm" onClick={() => launch("pull", () => launchers.pullSources(null), ["shortlist", "pipeline", "triage", "sources"])}>
          Pull all
        </Button>
      </div>

      {isLoading ? <p className="text-sm text-muted-foreground">Loading…</p> : (
        <>
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Boards &amp; careers pages
            </h2>
            {boards.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recurring boards yet.</p>
            ) : (
              <ul role="list">
                {boards.map((s) => (
                  <Row key={s.id} source={s} checked={selected.has(s.id)} onToggleCheck={toggle} />
                ))}
              </ul>
            )}
          </section>
          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Aggregators
            </h2>
            <ul role="list">
              {aggregators.map((s) => (
                <Row key={s.id} source={s} checked={selected.has(s.id)} onToggleCheck={toggle} />
              ))}
            </ul>
          </section>
          <SourceResultPanel sources={data} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Register the route and nav entry**

In `web/src/app/router.tsx`, add the lazy import and child route:

```tsx
const SourcesPage = lazy(() =>
  import("@/features/sources/SourcesPage").then((m) => ({ default: m.SourcesPage })),
);
// ...inside children:
      { path: "sources", element: page(<SourcesPage />) },
```

In `web/src/app/AppLayout.tsx`, import `Radar` from `lucide-react` and add to `NAV`:

```tsx
  { to: "/sources", label: "Sources", icon: Radar },
```

- [ ] **Step 5: Run the page test + typecheck**

Run: `cd web && npm run test -- SourcesPage && npm run build`
Expected: test PASS; build (incl. `tsc`) succeeds — the generated `schema.ts` from Task 11 types every `api.*` call used here.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/sources/SourcesPage.tsx web/src/features/sources/SourcesPage.test.tsx web/src/app/router.tsx web/src/app/AppLayout.tsx
git commit -m "feat(web): Sources page, route, and nav entry"
```

---

### Task 16: Frontend — e2e smoke + full web gate

**Files:**
- Create: `web/e2e/sources.spec.ts`
- Test: the Playwright smoke + the full web suite

**Interfaces:**
- Consumes: the running SPA + API (or mocked routes, matching how `web/e2e/smoke.spec.ts` runs today).

- [ ] **Step 1: Write the smoke test**

Inspect `web/e2e/smoke.spec.ts` for the existing harness (base URL, whether the API is mocked or live), then create `web/e2e/sources.spec.ts` following the same pattern:

```typescript
import { test, expect } from "@playwright/test";

test("sources page lists sections and add control", async ({ page }) => {
  await page.goto("/sources");
  await expect(page.getByRole("heading", { name: /Boards & careers pages/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add source" })).toBeVisible();
});
```

- [ ] **Step 2: Run the e2e smoke**

Run: `cd web && npm run test:e2e -- sources` (use the script name from `web/package.json`; it may be `e2e` or `playwright test`).
Expected: PASS.

- [ ] **Step 3: Full web gate**

Run: `cd web && npm run test && npm run lint && npm run build`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/sources.spec.ts
git commit -m "test(web): sources page e2e smoke"
```

---

### Task 17: Migrate the commented-out board parking-lot (optional cleanup)

**Files:**
- Modify: `config/connectors.yaml`

**Interfaces:** none — data hygiene so the spec's mitigation (decision #9) is realized.

- [ ] **Step 1: Convert commented-out boards to disabled rows**

In `config/connectors.yaml`, turn each commented-out Greenhouse/Lever board (Kodiak, Nuro, Divergent, StackAV, Outrider, Via, Buzz Solutions, Anduril…) into a real entry with `enabled: false`, e.g.:

```yaml
    - token: kodiak
      company: Kodiak Robotics
      enabled: false
```

This way the backlog survives the first UI write (which would otherwise drop comments) and appears in the Sources page as paused rows.

- [ ] **Step 2: Verify it still loads**

Run: `.venv/Scripts/python.exe -c "from resume_agent.discovery.connectors.config import load_connectors_config; print(len(load_connectors_config('config/connectors.yaml').greenhouse.boards))"`
Expected: prints the new (larger) board count without error.

- [ ] **Step 3: Commit**

```bash
git add config/connectors.yaml
git commit -m "chore(sources): migrate commented-out board backlog to disabled rows"
```

---

## Self-Review

**Spec coverage:**
- §2 view/add/remove/enable-disable → Tasks 7, 13–15. ✓
- §2/§5.3 pull one/selection/all → Tasks 3, 6, 13, 15. ✓
- §2/§5.4 per-source added/upgraded/skipped/failed → Tasks 4, 5, 10 (pull result payload). ✓
- §4 schema (`enabled`, `CompanyUrl`, coercion, ids) → Tasks 1, 2. ✓
- §5.1/§5.2 service + router (list/preview/add/patch/delete, atomic write) → Tasks 7, 8, 10. ✓
- §5.3 per-entry fan-out + telemetry-granularity risk → Task 3 (+ Task 12 regression gate). ✓
- §6 two-section page, add dialog with preview, pull controls, aggregator states → Tasks 14, 15. ✓
- §7 error envelope + `SourceError`→400 + preview-never-raises → Tasks 8, 10. ✓
- §8 comment-loss mitigation → Task 17. ✓
- §9 testing (back-compat, projection, skipped, CRUD, router, OpenAPI gate, web smoke) → Tasks 1–11, 13–16. ✓
- Contract regeneration drift gate → Task 11. ✓

**Placeholder scan:** No "TBD"/"add error handling"/"similar to". New modules/components carry full code; existing-file edits are written as concrete deltas at the target call site. Two soft references (`withQueryClient`/MSW helper path and the e2e harness shape) are explicitly flagged to match existing repo files (`use-bulk-run.test.tsx`, `e2e/smoke.spec.ts`) because their exact form is repo-local; implementers adapt the import path, not the logic.

**Type consistency:** `SourceView` (id, kind, type, display_name, enabled, pullable, detail) is identical across Tasks 2, 7, 9, 10, 13, 15. `SourcePreview` fields (ok, url, kind, token, label, role_count, error) match between Task 8 (dataclass) and Task 9 (`SourcePreviewOut`). `build_source_connectors(config, settings, source_ids=None)` signature is identical in Tasks 3, 6. `pull_jobs(..., source_ids=None, ...)` matches between Tasks 6 and 10. Wire field `sourceIds`/`roleCount`/`displayName` (camel) ↔ snake (`source_ids`/`role_count`/`display_name`) consistent via `CamelModel`.
