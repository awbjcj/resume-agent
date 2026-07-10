# Per-Source Limits + Workday Location Facets Implementation Plan

> **Execution:** Implement inline, task-by-task, with a red-green-refactor test cycle. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make job counts per source predictable: every source unit (board, careers URL, aggregator, scrape target) gets its own optional `limit`, the global `--limit` becomes the per-unit fallback (union caps removed), and Workday pulls send tenant-resolved `appliedFacets` for the configured locations.

**Architecture:** The `harvest` seam gates and caps **per unit** instead of on the union, taking a `unit_limit` resolver; connectors pass their unit models' `limit`. Config unit models gain an additive `limit` field (`ExtensibleModel`, so old YAML loads). The Source Manager PATCH grows a `limit` field end-to-end (config → SourceView → API → web input). Workday resolves location facet IDs from the first list response, caches them per tenant under `data/workday_facets/`, and restarts paging faceted; any miss falls back to searchText-only.

**Tech Stack:** Python 3.13, pydantic v2, FastAPI, httpx, React + TanStack Query (web), pytest + vitest.

## Reviewed corrections (authoritative)

- The Source Manager projection and mutations include scrape targets using the
  registry's stable `scrape:{host}` id; otherwise `ScrapeTarget.limit` would be
  configurable only by hand and the stated end-to-end surface would be incomplete.
- The source PATCH is one atomic service mutation and one file replacement when
  both `enabled` and `limit` are present. Service-level calls reject non-positive
  limits too; validation is not delegated only to the HTTP schema.
- Contract generation updates all three committed artifacts:
  `contracts/openapi.json`, `contracts/ts/api.ts`, and
  `web/src/lib/api/schema.ts`.
- LinkedIn receives `configured_limit` through its constructor/builder contract;
  do not attach an undeclared attribute after construction.
- Limit inputs have a unique accessible name per source row and reset on a failed
  mutation. The sources test uses MSW request capture rather than an unspecified
  request spy.
- Workday considers only location facet parameters and requires every configured
  location to match. Partial matches, malformed facets, cache I/O failures, and
  an empty first faceted page fall back to plain paging. This is required to
  preserve the “never fewer rows because mapping failed” invariant.
- Actual test paths are `tests/scraper/test_dashboard.py` and
  `tests/api/test_sources_router.py`.

**Execution order note:** run this plan after `2026-07-10-google-tesla-connectors.md` — Task 3 here edits the `concurrent_fetch` property that plan introduces in `companies.py`.

## Global Constraints

- Offline suite green with **no API key and no network**: `.venv/Scripts/python.exe -m pytest`; lint: `ruff check`; web: `cd web && npx vitest run`
- API wire format is **camelCase** (`CamelModel`); any schema change requires `bash scripts/gen_ts_client.sh` and a green `tests/api/test_openapi_contract.py`
- **Limit semantics (spec):** effective unit limit = `unit.limit` if set, else the global `--limit`; the cap counts *unseen, relevant* jobs (`skip_seen` runs before the cap — already true in `gate_and_limit`); union caps are removed
- Source-priority, dedup + location guard invariants untouched
- Workday fallback rule: a facet-resolution miss must never yield fewer results than today's searchText-only behavior; `_MAX_OFFSET = 1000` stays
- Spec: `docs/superpowers/specs/2026-07-10-discovery-precision-design.md` (§3, §4)

## File Structure

| Path | Role |
| ---- | ---- |
| `src/resume_agent/discovery/connectors/config.py` | `limit` on unit models + singleton sections |
| `src/resume_agent/discovery/connectors/harvest.py` | per-unit gate/cap via `unit_limit` |
| `src/resume_agent/discovery/connectors/greenhouse.py`, `lever.py` | pass `unit_limit` |
| `src/resume_agent/discovery/connectors/companies.py` | entries become `CompanyUrl`; per-URL limit |
| `src/resume_agent/discovery/connectors/remoteok.py`, `adzuna.py` | `configured_limit` |
| `src/resume_agent/discovery/scraper/linkedin.py`, `dashboard.py` | configured/per-target limits |
| `src/resume_agent/discovery/connectors/registry.py` | pass entries + section limits |
| `src/resume_agent/discovery/connectors/workday.py` | facet resolve + cache + faceted paging |
| `src/resume_agent/discovery/connectors/sources.py` | `SourceView.limit` + scrape projections |
| `src/resume_agent/services/sources.py` | atomic source patch + limit validation |
| `src/resume_agent/api/schemas/sources.py`, `api/routers/sources.py` | PATCH `{enabled?, limit?}` |
| `web/src/features/sources/*` | limit input per source row |
| `src/resume_agent/cli.py:331,386` | `--limit` help text |

---

### Task 1: `limit` on config unit models and singleton sections

**Files:**

- Modify: `src/resume_agent/discovery/connectors/config.py`
- Test: `tests/test_connectors_config.py` (create if absent; if config tests already live elsewhere — `grep -rl load_connectors_config tests/*.py` — append there)

**Interfaces:**

- Consumes: nothing new.
- Produces: `GreenhouseBoard.limit`, `LeverBoard.limit`, `CompanyUrl.limit`, `ScrapeTarget.limit`, `RemoteOKConfig.limit`, `AdzunaConfig.limit`, `LinkedInConfig.limit` — all `int | None = None`, validated `>= 1`. Tasks 2–5 read these.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pydantic import ValidationError

from resume_agent.discovery.connectors.config import (
    CompaniesConfig,
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
)


def test_unit_models_accept_optional_limit():
    assert GreenhouseBoard(token="acme").limit is None
    assert GreenhouseBoard(token="acme", limit=10).limit == 10
    assert CompanyUrl(url="https://x.example/careers", limit=5).limit == 5


def test_singleton_sections_accept_optional_limit():
    config = ConnectorsConfig.model_validate(
        {"remoteok": {"enabled": True, "limit": 25}, "adzuna": {"limit": 15}}
    )
    assert config.remoteok.limit == 25
    assert config.adzuna.limit == 15
    assert config.linkedin.limit is None


def test_limit_must_be_positive():
    with pytest.raises(ValidationError):
        GreenhouseBoard(token="acme", limit=0)


def test_bare_string_company_urls_still_coerce():
    config = CompaniesConfig.model_validate({"urls": ["https://x.example/careers"]})
    assert config.urls[0].url == "https://x.example/careers"
    assert config.urls[0].limit is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_config.py -v`
Expected: FAIL — `ValidationError`/`AttributeError` on `limit`

- [ ] **Step 3: Add the fields**

In `src/resume_agent/discovery/connectors/config.py`, add to **each** of
`GreenhouseBoard`, `LeverBoard`, `CompanyUrl`, `ScrapeTarget`,
`RemoteOKConfig`, `AdzunaConfig`, `LinkedInConfig` (one line each, after their
last existing field):

```python
    limit: int | None = Field(default=None, ge=1)
```

(`Field` is already imported.)

- [ ] **Step 4: Run tests to verify they pass, then the config-adjacent suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_config.py -v && .venv/Scripts/python.exe -m pytest -q -k "sources or registry or connector"`
Expected: PASS — the field is additive.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/connectors/config.py tests/test_connectors_config.py
git commit -m "Adds an optional per-unit limit to connector config models"
```

---

### Task 2: Per-unit gate/cap in the harvest seam

**Files:**

- Modify: `src/resume_agent/discovery/connectors/harvest.py:45-74` (`harvest`)
- Test: `tests/test_connector_harvest.py` (append; locate with `grep -rl "from resume_agent.discovery.connectors.harvest" tests/*.py` if named differently)

**Interfaces:**

- Consumes: `gate_and_limit` (unchanged).
- Produces: `harvest(units, produce, *, search, limit, key, on_error, skip_seen=None, unit_limit=None) -> FetchResult` — new optional `unit_limit: Callable[[U], int | None]`; per unit, the effective cap is `unit_limit(unit)` when not None, else `limit`. **The union is no longer capped.** Tasks 3 uses `unit_limit`.

- [ ] **Step 1: Write the failing tests**

Append (reusing the file's existing `SearchConfig`/`RawJob` imports; add missing ones):

```python
def _jobs(prefix: str, n: int) -> list[RawJob]:
    return [
        RawJob(source="t", url=f"http://x/{prefix}/{i}", company=prefix,
               title=f"Engineer {prefix} {i}", jd_text="Python role")
        for i in range(n)
    ]


def test_harvest_caps_each_unit_not_the_union():
    result = harvest(
        ["a", "b"],
        lambda unit: _jobs(unit, 5),
        search=SearchConfig(),
        limit=2,
        key=str,
        on_error=lambda exc: "boom",
    )
    # 2 per unit (global fallback is per-unit), union NOT capped at 2.
    assert len(result.jobs) == 4
    assert {j.company for j in result.jobs} == {"a", "b"}


def test_harvest_unit_limit_overrides_global():
    result = harvest(
        ["a", "b"],
        lambda unit: _jobs(unit, 5),
        search=SearchConfig(),
        limit=2,
        key=str,
        on_error=lambda exc: "boom",
        unit_limit=lambda unit: 4 if unit == "a" else None,
    )
    by_company = {}
    for job in result.jobs:
        by_company[job.company] = by_company.get(job.company, 0) + 1
    assert by_company == {"a": 4, "b": 2}


def test_harvest_no_limits_returns_everything():
    result = harvest(
        ["a"],
        lambda unit: _jobs(unit, 3),
        search=SearchConfig(),
        limit=None,
        key=str,
        on_error=lambda exc: "boom",
    )
    assert len(result.jobs) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_harvest.py -v -k "unit or union or everything"`
Expected: `caps_each_unit` FAILS (union capped at 2 today); `unit_limit` FAILS (`TypeError: unexpected keyword`)

- [ ] **Step 3: Rewrite `harvest`**

Replace the `harvest` function in `harvest.py` with:

```python
def harvest(
    units: Iterable[U],
    produce: Callable[[U], list[RawJob]],
    *,
    search: SearchConfig,
    limit: int | None,
    key: Callable[[U], str],
    on_error: Callable[[Exception], str | None],
    skip_seen: SkipSeen | None = None,
    unit_limit: Callable[[U], int | None] | None = None,
) -> FetchResult:
    """Fan out over ``units``, isolating each unit's failure, then gate and cap
    **per unit** — the union is never capped, so one prolific board cannot eat
    another's budget.

    ``produce`` turns one unit into RawJobs. When it raises, ``on_error`` decides:
    a returned string records ``failures[key(unit)] = reason`` and continues; ``None``
    re-raises (the connector does not tolerate this failure). The effective cap for
    a unit is ``unit_limit(unit)`` when set, else ``limit`` (the global default).
    ``skip_seen`` drops already-known rows before the cap, so caps fill with
    unseen rows.
    """
    jobs: list[RawJob] = []
    failures: dict[str, str] = {}
    filtered = 0
    for unit in units:
        try:
            produced = produce(unit)
        except Exception as exc:  # noqa: BLE001 — on_error decides record vs propagate
            reason = on_error(exc)
            if reason is None:
                raise
            failures[key(unit)] = reason
            continue
        cap = unit_limit(unit) if unit_limit is not None else None
        gated, unit_filtered = gate_and_limit(
            produced, search, cap if cap is not None else limit, skip_seen
        )
        jobs.extend(gated)
        filtered += unit_filtered
    return FetchResult(jobs=jobs, failures=failures, filtered=filtered)
```

Update the module docstring's "gate and cap the union" phrasing to "gate and cap each unit".

- [ ] **Step 4: Run the harvest + all connector suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_harvest.py -v && .venv/Scripts/python.exe -m pytest -q -k connector`
Expected: new tests PASS. **If a pre-existing test pinned the union cap** (asserting N total across units under a global limit), that expectation is the deliberate behavior change of this plan — update only such assertions, citing this task in the commit message.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/connectors/harvest.py tests/test_connector_harvest.py
git commit -m "Caps harvest per unit instead of on the union"
```

---

### Task 3: Wire unit limits through greenhouse, lever, and companies

**Files:**

- Modify: `src/resume_agent/discovery/connectors/greenhouse.py:57-73` (`fetch`)
- Modify: `src/resume_agent/discovery/connectors/lever.py` (`LeverConnector.fetch` — same edit shape)
- Modify: `src/resume_agent/discovery/connectors/companies.py` (entries become `CompanyUrl`)
- Modify: `src/resume_agent/discovery/connectors/registry.py:65` (companies payload)
- Modify: `src/resume_agent/services/sources.py:84` (preview call, coercion covers it — verify only)
- Test: `tests/test_connector_companies.py`, `tests/test_connector_greenhouse.py` (append)

**Interfaces:**

- Consumes: Task 1's `limit` fields, Task 2's `unit_limit` kwarg, `CompanyUrl` model.
- Produces: `CompaniesConnector(urls: list[CompanyUrl | str])` — `__init__` coerces bare strings to `CompanyUrl(url=...)`; `self.urls: list[CompanyUrl]`. Task 5 (Source Manager) and the registry rely on entries carrying `.url`/`.limit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connector_greenhouse.py` (mirror the file's existing fake-board fixtures for `_get_board` monkeypatching):

```python
def test_greenhouse_per_board_limit(monkeypatch):
    boards = [
        GreenhouseBoard(token="alpha", limit=1),
        GreenhouseBoard(token="beta"),
    ]
    connector = GreenhouseConnector(boards)
    payload = {"jobs": [
        {"title": f"Engineer {i}", "absolute_url": f"http://x/{i}",
         "location": {"name": "Remote"}, "content": "Python"}
        for i in range(3)
    ]}
    monkeypatch.setattr(connector, "_get_board", lambda token: payload)
    result = connector.fetch(SearchConfig(), limit=2)
    # alpha capped at its own 1, beta falls back to the global 2.
    assert len(result.jobs) == 3
```

Append to `tests/test_connector_companies.py`:

```python
def test_companies_coerces_strings_and_carries_limits():
    connector = CompaniesConnector(
        ["https://boards.greenhouse.io/acme",
         CompanyUrl(url="https://jobs.lever.co/beta", limit=3)]
    )
    assert connector.urls[0].url == "https://boards.greenhouse.io/acme"
    assert connector.urls[0].limit is None
    assert connector.urls[1].limit == 3
```

(add `from resume_agent.discovery.connectors.config import CompanyUrl, GreenhouseBoard` to the respective import blocks as needed.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_greenhouse.py tests/test_connector_companies.py -v -k "limit or coerces"`
Expected: FAIL (`ValidationError`less attribute errors / union-cap count of 2)

- [ ] **Step 3: Pass unit_limit in greenhouse and lever**

In `greenhouse.py` `fetch`, add one kwarg to the `harvest(...)` call:

```python
            unit_limit=lambda board: board.limit,
```

Make the identical edit in `lever.py`'s `LeverConnector.fetch` harvest call.

- [ ] **Step 4: Move companies onto CompanyUrl entries**

In `companies.py`:

1. Add `from resume_agent.discovery.connectors.config import CompanyUrl` to the imports.
2. Replace `__init__` and `fetch`/`_produce` of `CompaniesConnector`:

```python
    def __init__(self, urls: list[CompanyUrl | str]):
        self.urls: list[CompanyUrl] = [
            CompanyUrl(url=item) if isinstance(item, str) else item for item in urls
        ]

    @property
    def concurrent_fetch(self) -> bool:
        """False when a browser-driven portal (Tesla) is among the URLs, so the
        runner serializes this connector with other browser connectors instead
        of racing two visible browser sessions."""
        return not any(
            (target := identify_host(entry.url)) is not None and target.ats == "tesla"
            for entry in self.urls
        )

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        return harvest(
            self.urls,
            lambda entry: self._produce(entry, search, limit, skip_seen),
            search=search,
            limit=limit,
            key=lambda entry: entry.url,
            on_error=_failure_reason,
            skip_seen=skip_seen,
            unit_limit=lambda entry: entry.limit,
        )

    def _produce(
        self,
        entry: CompanyUrl,
        search: SearchConfig,
        limit: int | None,
        skip_seen: SkipSeen | None,
    ) -> list[RawJob]:
        target = detect_ats(entry.url)
        if target is None:
            raise NoAtsDetected
        backend = _BACKENDS.get(target.ats)
        if backend is None:
            raise UnsupportedAts(target.ats)
        effective = entry.limit if entry.limit is not None else limit
        return backend(target, search, effective, skip_seen=skip_seen)
```

(The `effective` passed to the backend lets paging backends — Workday, Google,
Tesla — stop fetching early; the harvest `unit_limit` then enforces the same
cap post-gate.)

3. In `registry.py:65`, change the companies units line to pass the entry:

```python
            ConnectorUnit(company_url_id(e.url), e.enabled, e) for e in c.companies.urls
```

4. Verify `services/sources.py:84` (`CompaniesConnector([url])`) still works —
   the `__init__` coercion covers the bare string; no edit needed.

- [ ] **Step 5: Run the suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_companies.py tests/test_connector_greenhouse.py tests/test_connector_lever.py -q && .venv/Scripts/python.exe -m pytest -q -k "registry or sources"`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/connectors/greenhouse.py src/resume_agent/discovery/connectors/lever.py \
        src/resume_agent/discovery/connectors/companies.py src/resume_agent/discovery/connectors/registry.py \
        tests/test_connector_companies.py tests/test_connector_greenhouse.py
git commit -m "Wires per-unit limits through greenhouse, lever, and companies"
```

---

### Task 4: Singleton and scrape-target limits

**Files:**

- Modify: `src/resume_agent/discovery/connectors/remoteok.py`, `adzuna.py`
- Modify: `src/resume_agent/discovery/scraper/linkedin.py` (builder + fetch head), `dashboard.py:285-` (per-target budget)
- Modify: `src/resume_agent/discovery/connectors/registry.py` (pass section limits)
- Test: `tests/test_connector_remoteok.py`, `tests/scraper/test_dashboard.py` (append)

**Interfaces:**

- Consumes: Task 1's section `limit` fields.
- Produces: `RemoteOKConnector(configured_limit: int | None = None)`, `AdzunaConnector(..., configured_limit: int | None = None)`, `build_linkedin_scraper(configured_limit: int | None = None)`; each `fetch` resolves `limit = self.configured_limit if self.configured_limit is not None else limit` as its first statement. `DashboardScraper` honors `target.limit` per target.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connector_remoteok.py` (reuse its existing `_get_all` monkeypatch idiom):

```python
def test_remoteok_configured_limit_beats_global(monkeypatch):
    connector = RemoteOKConnector(configured_limit=1)
    payload = [
        {"position": f"Engineer {i}", "company": "X", "url": f"http://x/{i}",
         "description": "Python"} for i in range(3)
    ]
    monkeypatch.setattr(connector, "_get_all", lambda: payload)
    result = connector.fetch(SearchConfig(), limit=5)
    assert len(result.jobs) == 1
```

Append to the dashboard scraper tests (adapt to the file's existing target/recipe fakes — the assertion structure is what matters):

```python
def test_scrape_per_target_limit_overrides_global(...):
    # two targets, each producing 3 gated cards; target A has limit=1, B has none;
    # global limit=2 -> expect 1 job from A and 2 from B.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -q -k "configured_limit or per_target_limit"`
Expected: FAIL (`TypeError: unexpected keyword 'configured_limit'`)

- [ ] **Step 3: Implement the singleton resolution**

`remoteok.py` — give the class an `__init__` and resolve in `fetch`:

```python
    def __init__(self, configured_limit: int | None = None):
        self.configured_limit = configured_limit
```

and as the first line of `fetch`:

```python
        if self.configured_limit is not None:
            limit = self.configured_limit
```

`adzuna.py` — add `configured_limit: int | None = None` to `__init__`'s
keyword-only params, store `self.configured_limit = configured_limit`, and add
the same two-line resolution at the top of `fetch`.

`scraper/linkedin.py` — add `configured_limit: int | None = None` to
`LinkedInScraper.__init__`, store it on the instance, add the same two-line
resolution at the top of `fetch`, and thread it through
`build_linkedin_scraper(configured_limit: int | None = None)`. Keeping the
field in the constructor makes the connector contract explicit and testable.

- [ ] **Step 4: Implement the per-target scrape budget**

In `dashboard.py` `fetch` (line ~297), the loop currently breaks on a global
budget. Convert to per-target:

1. Delete the global break `if limit is not None and len(jobs) >= limit: break` inside the target loop.
2. After the `recipe, cards = self._recipe_for(...)` try/except, add:

```python
                target_cap = getattr(target, "limit", None)
                if target_cap is None:
                    target_cap = limit
                taken = 0
```

3. In the card loop, immediately before the card is turned into a row, add:

```python
                    if target_cap is not None and taken >= target_cap:
                        break
```

4. Wherever this target's finished row is appended to `jobs` (follow the card
   loop to its `jobs.append(...)`), increment `taken += 1` right after the append.
5. Add `limit: int | None` to the `ScrapeTargetLike` protocol (line 47) so the
   attribute is part of the contract rather than a `getattr` — then replace the
   `getattr(target, "limit", None)` with `target.limit`. Update any test fake
   targets that implement the protocol to carry `limit = None`.

- [ ] **Step 5: Pass section limits in the registry**

In `registry.py`, update the three singleton build lambdas:

```python
        build=lambda payloads, c, s: RemoteOKConnector(configured_limit=c.remoteok.limit),
```

```python
        build=lambda payloads, c, s: AdzunaConnector(
            s.adzuna_app_id, s.adzuna_app_key, c.adzuna.country,
            configured_limit=c.adzuna.limit,
        ),
```

```python
        build=lambda payloads, c, s: build_linkedin_scraper(configured_limit=c.linkedin.limit),
```

- [ ] **Step 6: Update the CLI help text**

In `cli.py` lines 331 and 386, change the `--limit` help to:

```python
    limit: int | None = typer.Option(
        None, help="Default cap per source unit (board/URL/aggregator); per-source limits in connectors.yaml override."
    ),
```

- [ ] **Step 7: Run the full suite, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: green.

```bash
git add src/resume_agent/discovery/connectors/remoteok.py src/resume_agent/discovery/connectors/adzuna.py \
        src/resume_agent/discovery/scraper/linkedin.py src/resume_agent/discovery/scraper/dashboard.py \
        src/resume_agent/discovery/connectors/registry.py src/resume_agent/cli.py tests
git commit -m "Resolves configured limits for singleton connectors and scrape targets"
```

---

### Task 5: Source Manager limit — SourceView, API, contract

**Files:**

- Modify: `src/resume_agent/discovery/connectors/sources.py` (`SourceView.limit` + projections)
- Modify: `src/resume_agent/services/sources.py` (+ `set_source_limit`, `_apply_limit`)
- Modify: `src/resume_agent/api/schemas/sources.py` (`SourceOut.limit`, `SourcePatchIn`)
- Modify: `src/resume_agent/api/routers/sources.py` (PATCH route body)
- Modify: `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` (regenerated)
- Test: `tests/api/test_sources_router.py`, `tests/test_services_sources.py` (append)

**Interfaces:**

- Consumes: Task 1's config `limit` fields.
- Produces: `SourceView.limit: int | None`; `set_source_limit(source_id: str, limit: int | None, connectors_path=...) -> SourceView`; atomic `patch_source(source_id, *, enabled=UNSET, limit=UNSET, connectors_path=...)`; wire `PATCH /api/sources/{source_id}` body `SourcePatchIn {enabled?: bool, limit?: int|null}` — `limit: null` **clears** the per-source limit (present-vs-absent detected via `model_fields_set`). Task 6 (web) calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services_sources.py` (reuse its tmp connectors.yaml fixture idiom):

```python
def test_set_source_limit_roundtrips(tmp_path):
    path = tmp_path / "connectors.yaml"
    path.write_text(
        "greenhouse:\n  enabled: true\n  boards:\n    - token: acme\n",
        encoding="utf-8",
    )
    view = set_source_limit("greenhouse:acme", 10, connectors_path=str(path))
    assert view.limit == 10
    config = load_connectors_config(path)
    assert config.greenhouse.boards[0].limit == 10

    view = set_source_limit("greenhouse:acme", None, connectors_path=str(path))
    assert view.limit is None


def test_set_source_limit_on_singletons(tmp_path):
    path = tmp_path / "connectors.yaml"
    path.write_text("remoteok:\n  enabled: true\n", encoding="utf-8")
    view = set_source_limit("remoteok", 25, connectors_path=str(path))
    assert view.limit == 25


def test_set_source_limit_unknown_source_raises(tmp_path):
    path = tmp_path / "connectors.yaml"
    path.write_text("remoteok:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(SourceError):
        set_source_limit("greenhouse:nope", 5, connectors_path=str(path))
```

Append to `tests/api/test_sources_router.py` (reuse its client fixture and monkeypatch the service seam):

```python
def test_patch_source_limit(...):
    resp = client.patch("/api/sources/remoteok", json={"limit": 25})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 25

    resp = client.patch("/api/sources/remoteok", json={"limit": None})
    assert resp.status_code == 200
    assert resp.json()["limit"] is None

    resp = client.patch("/api/sources/remoteok", json={"enabled": False})
    assert resp.json()["enabled"] is False
    assert resp.json()["limit"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py tests/api/test_sources_router.py -v -k limit`
Expected: FAIL (import errors on `set_source_limit`, `KeyError: 'limit'`)

- [ ] **Step 3: Carry limit on SourceView**

In `connectors/sources.py`: add `limit: int | None = None` to the `SourceView`
dataclass, then populate it in `list_source_views` — `limit=board.limit` for
both board loops, `limit=entry.limit` for companies, `limit=target.limit` for
scrape targets, and `limit=config.adzuna.limit` / `config.remoteok.limit` /
`config.linkedin.limit` for the three singleton views. Add a shared
`scrape_target_id(url)` helper and use it here and in the registry so the stable
id cannot drift between projections and pull construction. Because scrape rows
now appear in Source Manager, extend enable/remove mutations for them too.

- [ ] **Step 4: Add the service mutation**

In `services/sources.py`, add the validated `set_source_limit` wrapper shown
below, include scrape targets in `_apply_limit`, and implement `patch_source`
to load once, apply every present field, validate `limit is None or limit >= 1`,
save once, and return one view. The router must call this atomic mutation rather
than chaining two independently persisted service calls.

```python
def set_source_limit(
    source_id: str,
    limit: int | None,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    config = load_connectors_config(connectors_path)
    if not _apply_limit(config, source_id, limit):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)
    return _view(config, source_id)


def _apply_limit(config: ConnectorsConfig, source_id: str, limit: int | None) -> bool:
    if source_id == "adzuna":
        config.adzuna.limit = limit
        return True
    if source_id == "remoteok":
        config.remoteok.limit = limit
        return True
    if source_id == "linkedin":
        config.linkedin.limit = limit
        return True
    for board in config.greenhouse.boards:
        if f"greenhouse:{board.token}" == source_id:
            board.limit = limit
            return True
    for board in config.lever.boards:
        if f"lever:{board.token}" == source_id:
            board.limit = limit
            return True
    for entry in config.companies.urls:
        if company_url_id(entry.url) == source_id:
            entry.limit = limit
            return True
    return False
```

- [ ] **Step 5: Wire schema and router**

In `api/schemas/sources.py`: add `limit: int | None = None` to `SourceOut`, and
replace `SetEnabledIn` with:

```python
class SourcePatchIn(CamelModel):
    enabled: bool | None = None
    limit: int | None = None
```

In `api/routers/sources.py`, update the import and the PATCH route:

```python
@router.patch("/sources/{source_id}", response_model=SourceOut)
def patch_source_route(source_id: str, body: SourcePatchIn):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiException(400, "VALIDATION_ERROR", "Provide enabled and/or limit.")
    return SourceOut.model_validate(
        _guard(lambda: patch_source(source_id, **changes))
    )
```

(add `patch_source` to the services import; `limit` must be `>= 1` or null —
add `from pydantic import Field` and use `limit: int | None = Field(default=None, ge=1)`
in `SourcePatchIn`.)

- [ ] **Step 6: Regenerate the contract, run suites**

```bash
bash scripts/gen_ts_client.sh
.venv/Scripts/python.exe -m pytest tests/api tests/test_services_sources.py -q
```

Expected: PASS including `tests/api/test_openapi_contract.py`.

- [ ] **Step 7: Lint and commit**

```bash
ruff check
git add src/resume_agent/discovery/connectors/sources.py src/resume_agent/services/sources.py \
        src/resume_agent/api/schemas/sources.py src/resume_agent/api/routers/sources.py \
        contracts tests
git commit -m "Exposes per-source limits through the Source Manager API"
```

---

### Task 6: Source Manager web input

**Files:**

- Modify: `web/src/features/sources/use-sources.ts` (+ `useSetSourceLimit`)
- Modify: `web/src/features/sources/SourcesPage.tsx` (limit cell per row)
- Test: `web/src/features/sources/SourcesPage.test.tsx` (append)

**Interfaces:**

- Consumes: Task 5's `PATCH /api/sources/{source_id}` with `{limit}` and `SourceOut.limit` (regenerated `contracts/ts/api.ts` exposes `limit` on the source type).
- Produces: a per-row numeric input labelled "Limit" that PATCHes on commit (blur/Enter), blank = no per-source limit (sends `limit: null`).

- [ ] **Step 1: Add the mutation hook**

In `web/src/features/sources/use-sources.ts`, mirroring the file's existing
mutation style (check its PATCH/toggle hook for the exact `api.PATCH` idiom and
query key — reuse both):

```ts
export function useSetSourceLimit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, limit }: { id: string; limit: number | null }) =>
      unwrap(
        api.PATCH("/api/sources/{source_id}", {
          params: { path: { source_id: id } },
          body: { limit },
        } as never),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
    onError: (err: Error) => toast.error(err.message),
  });
}
```

(If the file's list query key differs from `["sources"]`, use that key.)

- [ ] **Step 2: Add the input component and mount it**

In `SourcesPage.tsx`, add above the page component:

```tsx
function LimitInput({ id, limit }: { id: string; limit: number | null }) {
  const setLimit = useSetSourceLimit();
  const [value, setValue] = useState(limit == null ? "" : String(limit));
  useEffect(() => setValue(limit == null ? "" : String(limit)), [limit]);
  const commit = () => {
    const parsed = value.trim() === "" ? null : Number(value);
    if (parsed !== null && (!Number.isInteger(parsed) || parsed < 1)) {
      setValue(limit == null ? "" : String(limit));
      return;
    }
    if (parsed !== limit) setLimit.mutate({ id, limit: parsed });
  };
  return (
    <input
      type="number"
      min={1}
      inputMode="numeric"
      className="h-7 w-16 rounded border bg-transparent px-1.5 text-right text-xs"
      placeholder="—"
      aria-label="Per-pull job limit"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}
```

Mount `<LimitInput id={source.id} limit={source.limit ?? null} />` in each
source row, next to the enable toggle (locate the row render with
`grep -n "enabled" web/src/features/sources/SourcesPage.tsx` and place the cell
beside it, matching the row's existing cell classes). Add the
`useState`/`useEffect` imports if absent.

- [ ] **Step 3: Append the test**

In `SourcesPage.test.tsx`, mirroring the file's existing MSW/fetch-mock setup
for the sources list (give one source `limit: 10`):

```tsx
it("shows and edits the per-source limit", async () => {
  render(<SourcesPage />);   // adapt to the file's render helper
  const input = await screen.findByLabelText("Per-pull job limit");
  expect(input).toHaveValue(10);
  fireEvent.change(input, { target: { value: "25" } });
  fireEvent.blur(input);
  // assert the PATCH was issued with { limit: 25 } via the file's request spy
});
```

- [ ] **Step 4: Run web tests, lint, commit**

```bash
cd web && npx vitest run src/features/sources && cd ..
git add web/src/features/sources
git commit -m "Adds a per-source pull limit input to the Source Manager"
```

---

### Task 7: Workday location facets

**Files:**

- Modify: `src/resume_agent/discovery/connectors/workday.py`
- Test: `tests/test_connector_workday.py` (append)

**Interfaces:**

- Consumes: `search.locations` (`SearchConfig`), existing `_list_pages`/`list_request_body`/`fetch_workday`.
- Produces: `resolve_location_facets(page: dict, locations: list[str]) -> dict[str, list[str]]`; `load_cached_facets(target, locations, base_dir) -> dict | None` (None = no/invalid/mismatched cache; `{}` = cached miss); `save_cached_facets(target, locations, applied, base_dir) -> None`; `list_request_body(search, offset, applied_facets=None)`; `fetch_workday(..., facets_dir=_FACETS_DIR)` (new trailing keyword, default preserves callers).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_connector_workday.py` (reuse its existing `httpx.post` fake idiom and `TARGET` fixture; if the file names them differently, adapt the plumbing, not the assertions):

```python
FACETED_PAGE = {
    "total": 1,
    "jobPostings": [
        {"title": "Software Engineer", "externalPath": "/job/Austin/SWE_1",
         "locationsText": "Austin, TX"},
    ],
    "facets": [
        {"facetParameter": "locations",
         "values": [
             {"descriptor": "Austin, TX, United States of America", "id": "loc-austin"},
             {"descriptor": "Detroit, MI, United States of America", "id": "loc-detroit"},
         ]},
        {"facetParameter": "jobFamilyGroup",
         "values": [{"descriptor": "Engineering", "id": "fam-eng"}]},
    ],
}


def test_resolve_location_facets_matches_by_containment():
    applied = workday.resolve_location_facets(FACETED_PAGE, ["Austin, TX"])
    assert applied == {"locations": ["loc-austin"]}


def test_resolve_location_facets_no_match_is_empty():
    assert workday.resolve_location_facets(FACETED_PAGE, ["Boston, MA"]) == {}
    assert workday.resolve_location_facets(FACETED_PAGE, []) == {}


def test_facet_cache_roundtrip_and_invalidation(tmp_path):
    workday.save_cached_facets(TARGET, ["Austin, TX"], {"locations": ["loc-austin"]},
                               base_dir=tmp_path)
    assert workday.load_cached_facets(TARGET, ["Austin, TX"], base_dir=tmp_path) == {
        "locations": ["loc-austin"]
    }
    # Changed configured locations invalidate the cache.
    assert workday.load_cached_facets(TARGET, ["Detroit, MI"], base_dir=tmp_path) is None


def test_fetch_workday_resolves_then_restarts_faceted(monkeypatch, tmp_path):
    bodies = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(url, json, timeout):
        bodies.append(json)
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    monkeypatch.setattr(workday, "_fetch_detail", lambda target, row: {
        "jobPostingInfo": {"jobDescription": "<p>Python</p>"}
    })
    jobs = workday.fetch_workday(
        TARGET, SearchConfig(locations=["Austin, TX"]), facets_dir=tmp_path
    )
    # Request 1 plain (resolution), request 2 restarted at offset 0 with facets.
    assert bodies[0]["appliedFacets"] == {}
    assert bodies[1]["appliedFacets"] == {"locations": ["loc-austin"]}
    assert bodies[1]["offset"] == 0
    assert [j.title for j in jobs] == ["Software Engineer"]
    # Cache written for the next pull.
    assert workday.load_cached_facets(TARGET, ["Austin, TX"], base_dir=tmp_path) == {
        "locations": ["loc-austin"]
    }


def test_fetch_workday_cached_miss_stays_plain(monkeypatch, tmp_path):
    bodies = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(url, json, timeout):
        bodies.append(json)
        return _Resp(FACETED_PAGE)

    monkeypatch.setattr(workday.httpx, "post", fake_post)
    monkeypatch.setattr(workday, "_fetch_detail", lambda target, row: {
        "jobPostingInfo": {"jobDescription": "<p>Python</p>"}
    })
    workday.save_cached_facets(TARGET, ["Boston, MA"], {}, base_dir=tmp_path)
    jobs = workday.fetch_workday(
        TARGET, SearchConfig(locations=["Boston, MA"]), facets_dir=tmp_path
    )
    # Cached miss -> single plain pass, no restart, rows still yielded.
    assert all(body["appliedFacets"] == {} for body in bodies)
    assert len(jobs) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_workday.py -v -k facet`
Expected: FAIL — `AttributeError: resolve_location_facets`

- [ ] **Step 3: Implement resolution + cache + faceted paging**

In `workday.py`, add imports `import json` and `from pathlib import Path`, plus:

```python
_FACETS_DIR = Path("data/workday_facets")


def resolve_location_facets(page: dict, locations: list[str]) -> dict[str, list[str]]:
    """Match configured location strings against the facet descriptors of a CXS
    list response. Facet vocabularies are tenant-specific, so matching is
    case-insensitive containment either way. Empty result = caller stays on
    searchText-only (never fewer results than today from a mapping failure)."""
    wanted = [loc.casefold() for loc in locations if loc.strip()]
    if not wanted:
        return {}
    applied: dict[str, list[str]] = {}

    def walk(node: object, param: str | None) -> None:
        if isinstance(node, dict):
            param = node.get("facetParameter") or param
            descriptor = str(node.get("descriptor") or "")
            facet_id = node.get("id")
            if param and facet_id and descriptor:
                hay = descriptor.casefold()
                if any(want in hay or hay in want for want in wanted):
                    ids = applied.setdefault(str(param), [])
                    if facet_id not in ids:
                        ids.append(facet_id)
            for value in node.values():
                walk(value, param)
        elif isinstance(node, list):
            for item in node:
                walk(item, param)

    walk(page.get("facets") or [], None)
    return applied


def _facet_cache_path(target: AtsTarget, base_dir: str | Path) -> Path:
    return Path(base_dir) / f"{target.tenant}-{target.site}.json"


def load_cached_facets(
    target: AtsTarget, locations: list[str], base_dir: str | Path = _FACETS_DIR
) -> dict | None:
    """The cached appliedFacets for this tenant+site, or None when absent,
    unreadable, or resolved against different configured locations. A cached
    ``{}`` is a remembered miss: stay plain without re-resolving each pull."""
    try:
        data = json.loads(_facet_cache_path(target, base_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("locations") != sorted(loc for loc in locations if loc.strip()):
        return None
    applied = data.get("appliedFacets")
    return applied if isinstance(applied, dict) else None


def save_cached_facets(
    target: AtsTarget,
    locations: list[str],
    applied: dict[str, list[str]],
    base_dir: str | Path = _FACETS_DIR,
) -> None:
    path = _facet_cache_path(target, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "locations": sorted(loc for loc in locations if loc.strip()),
        "appliedFacets": applied,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

Change `list_request_body` to:

```python
def list_request_body(
    search: SearchConfig, offset: int, applied_facets: dict | None = None
) -> dict:
    return {
        "appliedFacets": applied_facets or {},
        "limit": _PAGE,
        "offset": offset,
        "searchText": primary_search_term(search),
    }
```

Replace `_list_pages` with:

```python
def _list_pages(target: AtsTarget, search: SearchConfig, facets_dir: str | Path = _FACETS_DIR):
    locations = [loc for loc in search.locations if loc.strip()]
    applied = load_cached_facets(target, locations, facets_dir) if locations else None
    must_resolve = applied is None and bool(locations)
    offset = 0
    while offset <= _MAX_OFFSET:
        body = list_request_body(search, offset, applied)
        resp = httpx.post(cxs_jobs_url(target), json=body, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        if must_resolve:
            # Resolve from the first (plain) response, cache, and restart the
            # paging faceted — the plain page's rows are dropped, not yielded,
            # so faceted and plain rows never mix.
            must_resolve = False
            found = resolve_location_facets(page, locations)
            save_cached_facets(target, locations, found, facets_dir)
            if found:
                applied = found
                offset = 0
                continue
        postings = page.get("jobPostings") or []
        if not postings:
            return
        yield from parse_list_rows(target, page)
        total = page.get("total")
        offset += _PAGE
        if isinstance(total, int) and offset >= total:
            return
```

And thread the directory through `fetch_workday`:

```python
def fetch_workday(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
    facets_dir: str | Path = _FACETS_DIR,
) -> list[RawJob]:
    """List (faceted when resolvable) -> gate on title/location -> detail-fetch survivors."""
    return harvest_detailed(
        _list_pages(target, search, facets_dir),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
```

- [ ] **Step 4: Run the workday suite (new + conformance)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connector_workday.py -v`
Expected: all PASS — pre-existing tests use no `locations`, so `applied` stays
None and request bodies are byte-identical to before.

- [ ] **Step 5: Update CLAUDE.md**

Replace the "Workday `appliedFacets` not used." design note with:

```markdown
- **Workday sends location facets when resolvable.** On the first faceted pull,
  the plain page-1 response's `facets` are matched (case-insensitive containment)
  against `search.yaml` locations, cached per tenant in `data/workday_facets/
  {tenant}-{site}.json` keyed by the configured locations, and paging restarts
  with `appliedFacets`. Any miss is cached as `{}` and the pull stays
  searchText-only — never fewer results than the unfaceted behavior. Category/
  jobFamily facets remain out of scope.
```

Also append to the "Known design notes" the limit contract:

```markdown
- **Limits are per source unit.** Every board/URL/aggregator/scrape target takes
  an optional `limit` (connectors.yaml, Source Manager); the global `--limit` is
  the per-unit fallback. `harvest` gates and caps per unit — the union is never
  capped — and `skip_seen` runs before the cap, so caps fill with unseen rows.
```

- [ ] **Step 6: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/discovery/connectors/workday.py tests/test_connector_workday.py CLAUDE.md
git commit -m "Applies cached tenant location facets to Workday pulls"
```

---

## Final verification (after all tasks)

- [ ] `.venv/Scripts/python.exe -m pytest -q` — full suite PASS
- [ ] `ruff check` — clean
- [ ] `cd web && npx vitest run` — web suite PASS
- [ ] `tests/api/test_openapi_contract.py` green after `bash scripts/gen_ts_client.sh` (Task 5 regenerated)
- [ ] Use the repository code-review-and-quality and code-simplification passes before merging

## Self-review notes (already applied)

- Spec coverage: config fields → Task 1; per-unit harvest → Task 2; multi-unit wiring + payload shape → Task 3; singletons/scrape → Task 4; API+SourceView → Task 5; web input → Task 6; Workday facets + both CLAUDE.md notes → Task 7.
- Type consistency: `unit_limit: Callable[[U], int | None]` (Task 2) matches the lambdas in Task 3; `CompanyUrl` coercion in Task 3 keeps `services/sources.py:84` and Plan 1's `concurrent_fetch` property working (property body updated here to `entry.url`); `SourcePatchIn`/`set_source_limit` names match between Task 5's router and service.
- Known judgment calls: (a) a facet-resolution miss is cached as `{}` so pulls don't pay a resolve round-trip every run; delete the tenant's file under `data/workday_facets/` to force re-resolution. (b) The scrape per-target budget replaces the global break — with per-unit semantics a global budget across targets no longer exists anywhere. (c) `PATCH /api/sources/{id}` uses `model_fields_set` to distinguish "clear limit" (`limit: null`) from "don't touch limit" (field absent).
