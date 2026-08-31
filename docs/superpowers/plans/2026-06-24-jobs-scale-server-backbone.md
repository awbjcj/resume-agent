# Jobs-Scale Server Backbone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move board filtering, sorting, pagination, and facet counting into the `services/board` layer behind one `BoardFilter` contract, and add a single act-by-query bulk endpoint, so the React client stops fetching-all-then-filtering and bulk archive/delete/prune of thousands of jobs is one request.

**Architecture:** A new pure module `services/board_query.py` holds the `BoardFilter` dataclass and the cross-board predicate/facet helpers; it **reuses** the existing `dashboard/filtering.py` predicate for the rich Shortlist facets (no second implementation). `services/board.py` gains a `BoardFilter` parameter on each `list_*` plus a `board_facets` and a `bulk_apply`. The API exposes the filter as query params, returns a `BoardPage` envelope (`data` + `pagination` + `facets` + `total`), and adds `POST /api/jobs/bulk`. All mutation invariants (`has_progress` skip, FK-safe `delete_job`, `archived_at` orthogonality) are enforced server-side, per job.

**Tech Stack:** Python 3 / FastAPI / SQLModel / pytest. Offline tests (`.venv/Scripts/python.exe -m pytest`). Contract regen via `bash scripts/gen_ts_client.sh`.

## Global Constraints

- **Wire format is camelCase**; Python stays snake_case. All request/response models extend `CamelModel` (`api/schemas/base.py`).
- **Error envelope** is `{ "error": { code, message, details? } }` via `ApiException` (`api/errors.py`). Use `422 VALIDATION_ERROR`, `404 NOT_FOUND`, `409 CONFLICT`.
- **Approach A preserved:** criteria fields stay in `criteria_json`; filtering is in-process Python over loaded rows. The only schema change is **index creation**, never new criteria columns.
- **Invariants (never break):** `delete_job` refuses `has_progress` jobs and cascades FK-safe; `archived_at` is orthogonal to `status`; bulk `approve`/`setStatus` skip `has_progress` jobs rather than re-stage them.
- **Additive API only:** new query params are optional with today's defaults; existing `minFit`/`sortBy`/`status`/`archived`/`page`/`pageSize` keep working unchanged.
- **`pageSize` stays capped at 200** (`ge=1, le=200`).
- Run the full suite (`.venv/Scripts/python.exe -m pytest`) and `ruff check` before the final commit of each task.
- **In-flight compatibility (verified 2026-06-24):** this plan is written against the current working tree, which already contains compatible uncommitted refactors — `board.job_detail_facets` renamed to `board.get_job_detail`; prune logic extracted to `services/prune.py` (router calls it; `/api/prune` unchanged); `filtering.composite_score` split into `_composite_raw` + wrapper; `queries.py` additive (`JobDetailRow`/`job_detail_row`/`is_us`). None collide: this plan reuses only `FilterState`/`apply_filters`/`sort_rows`, rewrites `list_*`, and appends new symbols (`board_facets`, `bulk_apply`, the bulk endpoint). **Commit (or stash) that in-flight work before executing** so each task's diff stays clean.

---

### Task 1: `BoardFilter` contract + query-param parser

**Files:**

- Create: `src/resume_tailor_harness/services/board_query.py`
- Test: `tests/test_services_board_query.py`

**Interfaces:**

- Produces: `BoardFilter` dataclass; `parse_csv(value: str | None) -> set[str]`; `to_filter_state(f: BoardFilter) -> dashboard.filtering.FilterState`.

`BoardFilter` is the superset of every board's filters. Per-board `list_*` functions
read only the subset that board supports (Task 2). Sets default to empty; scalars to `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_board_query.py
from resume_tailor_harness.services.board_query import BoardFilter, parse_csv, to_filter_state


def test_parse_csv_splits_trims_and_drops_empties():
    assert parse_csv("a, b ,,c") == {"a", "b", "c"}
    assert parse_csv(None) == set()
    assert parse_csv("") == set()


def test_to_filter_state_maps_scalars_and_sets():
    f = BoardFilter(min_fit=60, min_salary=120000, seniority={"senior"}, skills={"python"})
    state = to_filter_state(f)
    assert state.fit_min == 60
    assert state.salary_min == 120000
    assert state.seniority == {"senior"}
    assert state.skills == {"python"}
    assert state.sort == "fit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board_query.py -v`
Expected: FAIL with `ModuleNotFoundError: resume_tailor_harness.services.board_query`.

- [ ] **Step 3: Write the module**

```python
# src/resume_tailor_harness/services/board_query.py
"""Cross-board filter contract (BoardFilter) + helpers shared by services/board.

Pure: no FastAPI, no Streamlit. The rich Shortlist facet predicate is reused from
dashboard.filtering via to_filter_state; this module only adds the cross-cutting
filters (q, source, status, max_fit, stale_days) that the board lists apply on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from resume_tailor_harness.dashboard.filtering import FilterState


@dataclass
class BoardFilter:
    q: str | None = None
    min_fit: int | None = None
    max_fit: int | None = None
    min_salary: int | None = None
    stale_days: int | None = None
    source: set[str] = field(default_factory=set)
    status: set[str] = field(default_factory=set)
    remote: set[str] = field(default_factory=set)
    sponsorship: set[str] = field(default_factory=set)
    seniority: set[str] = field(default_factory=set)
    employment_type: set[str] = field(default_factory=set)
    industry: set[str] = field(default_factory=set)
    country: set[str] = field(default_factory=set)
    region: set[str] = field(default_factory=set)
    city: set[str] = field(default_factory=set)
    company_size: set[str] = field(default_factory=set)
    skills: set[str] = field(default_factory=set)
    # None means "board default": Shortlist/Triage use fit; Pipeline keeps stage order.
    sort: str | None = None
    preset: str = "balanced"


def parse_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def to_filter_state(f: BoardFilter) -> FilterState:
    """Project the BoardFilter onto the Shortlist facet predicate's FilterState."""
    return FilterState(
        salary_min=f.min_salary,
        fit_min=f.min_fit,
        remote=set(f.remote),
        sponsorship=set(f.sponsorship),
        seniority=set(f.seniority),
        employment_type=set(f.employment_type),
        industry=set(f.industry),
        country=set(f.country),
        region=set(f.region),
        city=set(f.city),
        company_size=set(f.company_size),
        skills=set(f.skills),
        sort=f.sort or "fit",
        preset=f.preset,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board_query.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/resume_tailor_harness/services/board_query.py tests/test_services_board_query.py
git add src/resume_tailor_harness/services/board_query.py tests/test_services_board_query.py
git commit -m "feat(board): BoardFilter contract + query-param helpers"
```

---

### Task 2: Server-side filter + sort on the board lists

**Files:**

- Create: `src/resume_tailor_harness/services/board_query.py` (extend — add cross-cutting predicate + sorters)
- Modify: `src/resume_tailor_harness/services/board.py` (`list_shortlist`, `list_pipeline`, `list_triage`)
- Test: `tests/test_services_board.py` (append cases)

**Interfaces:**

- Consumes: `BoardFilter`, `to_filter_state` (Task 1); `apply_filters`, `sort_rows` (`dashboard/filtering`); `triage_rows`, `archived_rows`, `pipeline_rows`, `shortlist_rows` (`tracking/queries`); `paginate` (`services/pagination`).
- Produces: `list_shortlist(session, *, filter: BoardFilter, page, page_size) -> Page[ShortlistRow]`; same shape for `list_triage` / `list_pipeline`. Helpers `apply_common(rows, f)`, `age_days(row, now)`, `sort_triage(rows, f)`.

Backward compatibility: keep the existing keyword params (`min_fit`, `sort`, `status`,
`archived`, `q`) by having the routers build a `BoardFilter` (Task 4). The service
functions switch to a single `filter: BoardFilter` argument.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services_board.py  (append)
from datetime import datetime, timedelta, timezone

from resume_tailor_harness.services.board_query import BoardFilter


def test_list_triage_filters_source_status_and_stale():
    now = datetime.now(timezone.utc)
    with _session() as session:
        _job(session, status=JobStatus.rejected.value, source="adzuna", fit_score=20,
             company="Old", posted_at=now - timedelta(days=60))
        _job(session, status=JobStatus.rejected.value, source="lever", fit_score=20,
             company="Fresh", posted_at=now - timedelta(days=2))
        _job(session, status=JobStatus.raw.value, source="adzuna", fit_score=20, company="Raw")
        page = board.list_triage(
            session, filter=BoardFilter(source={"adzuna"}, status={"rejected"}, stale_days=45)
        )
    assert [r.company for r in page.data] == ["Old"]


def test_list_triage_max_fit_keeps_low_scores():
    with _session() as session:
        _job(session, status=JobStatus.rejected.value, fit_score=20, company="Low")
        _job(session, status=JobStatus.rejected.value, fit_score=80, company="High")
        _job(session, status=JobStatus.rejected.value, fit_score=None, company="Unknown")
        page = board.list_triage(session, filter=BoardFilter(max_fit=40))
    assert {r.company for r in page.data} == {"Low"}


def test_list_shortlist_facet_filter_and_q():
    with _session() as session:
        _job(session, status=JobStatus.shortlisted.value, fit_score=90, company="Acme Corp")
        _job(session, status=JobStatus.shortlisted.value, fit_score=70, company="Beta LLC")
        page = board.list_shortlist(session, filter=BoardFilter(q="acme", min_fit=50))
    assert [r.company for r in page.data] == ["Acme Corp"]


def test_list_shortlist_ignores_source_filter_until_source_is_on_shortlist_rows():
    with _session() as session:
        _job(session, status=JobStatus.shortlisted.value, source="adzuna", fit_score=90, company="Acme")
        page = board.list_shortlist(session, filter=BoardFilter(source={"lever"}))
    assert [r.company for r in page.data] == ["Acme"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v -k "triage_filters or max_fit or facet_filter or ignores_source"`
Expected: FAIL — `list_triage`/`list_shortlist` do not accept `filter=`.

- [ ] **Step 3: Add the cross-cutting predicate to `board_query.py`**

```python
# src/resume_tailor_harness/services/board_query.py  (append)
from datetime import datetime, timezone


def age_days(posted_at: datetime | None, now: datetime) -> float | None:
    if posted_at is None:
        return None
    posted = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    return (now - posted.astimezone(timezone.utc)).total_seconds() / 86400.0


def matches_common(row, f: BoardFilter, now: datetime) -> bool:
    """Cross-board filters that read attributes shared by the row DTOs.

    Each check is guarded by getattr so it is a no-op on a row type lacking the
    attribute (e.g. ShortlistRow has no .source/.status, PipelineRow no .posted_at).
    """
    if f.q:
        needle = f.q.strip().lower()
        hay = f"{getattr(row, 'company', '') or ''} {getattr(row, 'title', '') or ''}".lower()
        if needle not in hay:
            return False
    fit = getattr(row, "fit_score", None)
    # Fit bounds are score predicates, not null-neutral metadata filters. Unknown
    # scores must not be swept into Low-fit pruning or Min-fit shortlist views.
    if f.min_fit is not None and (fit is None or fit < f.min_fit):
        return False
    if f.max_fit is not None and (fit is None or fit > f.max_fit):
        return False
    source = getattr(row, "source", None)
    if f.source and source is not None and source not in f.source:
        return False
    status = getattr(row, "status", None)
    if f.status and status is not None and status not in f.status:
        return False
    if f.stale_days is not None:
        age = age_days(getattr(row, "posted_at", None), now)
        # Unknown posting date is neutral (kept), matching the null-neutral rule.
        if age is not None and age < f.stale_days:
            return False
    return True


def sort_by_fit_desc(rows):
    return sorted(rows, key=lambda r: (r.fit_score is not None, r.fit_score or -1), reverse=True)
```

- [ ] **Step 4: Rewrite the three `list_*` in `board.py` to take a `BoardFilter`**

Replace `list_shortlist`, `list_pipeline`, `list_triage` (`services/board.py:45-106`) with:

```python
from datetime import datetime, timezone

from resume_tailor_harness.dashboard.filtering import apply_filters, sort_rows
from resume_tailor_harness.services.board_query import (
    BoardFilter,
    matches_common,
    sort_by_fit_desc,
    to_filter_state,
)


def list_shortlist(
    session: Session, *, filter: BoardFilter | None = None,
    page: int = 1, page_size: int = 50, facts_path: str = DEFAULT_FACTS,
) -> Page[ShortlistRow]:
    f = filter or BoardFilter()
    now = datetime.now(timezone.utc)
    facts = load_facts(facts_path) if Path(facts_path).exists() else None
    rows = shortlist_rows(session, facts=facts)
    state = to_filter_state(f)
    rows = [r for r in apply_filters(rows, state) if matches_common(r, f, now)]
    rows = sort_rows(rows, state, now=now)
    return paginate(rows, page=page, page_size=page_size)


def list_pipeline(
    session: Session, *, filter: BoardFilter | None = None,
    page: int = 1, page_size: int = 50,
) -> Page[PipelineRow]:
    f = filter or BoardFilter()
    now = datetime.now(timezone.utc)
    rows = [r for r in pipeline_rows(session) if matches_common(r, f, now)]
    sort = f.sort or "stage"
    if sort == "fit":
        rows = sort_by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)


def list_triage(
    session: Session, *, filter: BoardFilter | None = None, archived: bool = False,
    page: int = 1, page_size: int = 50,
) -> Page[TriageRow]:
    f = filter or BoardFilter()
    now = datetime.now(timezone.utc)
    rows = archived_rows(session) if archived else triage_rows(session)
    rows = [r for r in rows if matches_common(r, f, now)]
    sort = f.sort or "fit"
    if sort == "fit":
        rows = sort_by_fit_desc(rows)
    elif sort == "company":
        rows = sorted(rows, key=lambda r: ((r.company or "").lower(), (r.title or "").lower()))
    return paginate(rows, page=page, page_size=page_size)
```

Remove the now-unused `_by_fit_desc` helper and its only other callers (replaced by
`sort_by_fit_desc`). Leave the mutation functions below untouched.

- [ ] **Step 5: Run the board tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v`
Expected: PASS — new cases plus the existing `test_list_pipeline_filters_by_status_and_min_fit` (it calls `list_pipeline(session, status=..., min_fit=...)`; update that existing test to `filter=BoardFilter(status={"tailored"}, min_fit=50)` since the signature changed).

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/resume_tailor_harness/services/board_query.py src/resume_tailor_harness/services/board.py tests/test_services_board.py
git add src/resume_tailor_harness/services/board_query.py src/resume_tailor_harness/services/board.py tests/test_services_board.py
git commit -m "feat(board): server-side BoardFilter filter+sort on every board list"
```

---

### Task 3: Facet counts (`board_facets`) with excluding-self semantics

**Files:**

- Modify: `src/resume_tailor_harness/services/board_query.py` (add `compute_facets`)
- Modify: `src/resume_tailor_harness/services/board.py` (add `board_facets`)
- Test: `tests/test_services_board.py` (append)

**Interfaces:**

- Produces: `compute_facets(rows, f, now, specs) -> dict[str, dict[str, int]]` where `specs` maps facet-name → row attribute name (or a callable). `board.board_facets(session, board, filter) -> dict[str, dict[str, int]]`.

Each facet's counts are computed over rows passing **all other** facets (excluding that
facet's own selections), so sibling values stay visible. The Shortlist `skills` facet
counts on normalized skill tokens; geography/industry use the row attributes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_board.py  (append)
def test_board_facets_exclude_self_and_count_siblings():
    with _session() as session:
        _job(session, status=JobStatus.rejected.value, source="adzuna", fit_score=10)
        _job(session, status=JobStatus.rejected.value, source="lever", fit_score=10)
        _job(session, status=JobStatus.raw.value, source="adzuna", fit_score=10)
        # With source=adzuna selected, the 'source' facet still shows lever (excl-self),
        # but the 'status' facet is computed within source=adzuna.
        facets = board.board_facets(
            session, "triage", filter=BoardFilter(source={"adzuna"})
        )
    assert facets["source"] == {"adzuna": 2, "lever": 1}
    assert facets["status"] == {"raw": 1, "rejected": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py::test_board_facets_exclude_self_and_count_siblings -v`
Expected: FAIL — `board_facets` undefined.

- [ ] **Step 3: Add `compute_facets` to `board_query.py`**

```python
# src/resume_tailor_harness/services/board_query.py  (append)
import copy
from collections.abc import Callable

from resume_tailor_harness.tracking.match_gap import normalize_skill

# facet name -> the BoardFilter set-attribute it clears + how to read row values.
TRIAGE_FACETS: dict[str, str] = {"source": "source", "status": "status"}
SHORTLIST_FACETS: dict[str, str] = {
    "remote": "remote", "sponsorship": "sponsorship", "seniority": "seniority",
    "employmentType": "employment_type", "companySize": "company_size",
    "industry": "industry", "country": "country", "region": "region", "city": "city",
}
# row attribute backing each shortlist facet value (camelCase facet -> row attr).
_SHORTLIST_ROW_ATTR: dict[str, str] = {
    "remote": "remote_policy", "sponsorship": "sponsorship_signal",
    "seniority": "seniority", "employmentType": "employment_type",
    "companySize": "company_size", "industry": "sic_major",
    "country": "location_country", "region": "location_region", "city": "location_city",
}


def _without(f: BoardFilter, attr: str) -> BoardFilter:
    clone = copy.copy(f)
    setattr(clone, attr, set())
    return clone


def _values(row, facet: str, row_attr: str) -> list[str]:
    if facet == "skills":
        return [normalize_skill(t.name) for t in getattr(row, "skills", [])]
    v = getattr(row, row_attr, None)
    return [str(v)] if v is not None else []


def compute_facets(
    rows: list, f: BoardFilter, now,
    facet_filter_attr: dict[str, str], facet_row_attr: dict[str, str],
    predicate: Callable[[list, BoardFilter], list],
    *, include_skills: bool = False,
) -> dict[str, dict[str, int]]:
    """{facet: {value: count}} with each facet computed excluding its own selection."""
    out: dict[str, dict[str, int]] = {}
    specs = dict(facet_row_attr)
    if include_skills:
        specs["skills"] = "skills"
        facet_filter_attr = {**facet_filter_attr, "skills": "skills"}
    for facet, row_attr in specs.items():
        subset = predicate(rows, _without(f, facet_filter_attr[facet]))
        counts: dict[str, int] = {}
        for row in subset:
            for val in _values(row, facet, row_attr):
                if val:
                    counts[val] = counts.get(val, 0) + 1
        out[facet] = counts
    return out
```

- [ ] **Step 4: Add `board_facets` to `board.py`**

```python
# src/resume_tailor_harness/services/board.py  (append near the list_* functions)
from resume_tailor_harness.services.board_query import (
    SHORTLIST_FACETS, TRIAGE_FACETS, _SHORTLIST_ROW_ATTR, compute_facets, matches_common,
)


def board_facets(
    session: Session, board: str, *, filter: BoardFilter | None = None,
    archived: bool = False, facts_path: str = DEFAULT_FACTS,
) -> dict[str, dict[str, int]]:
    f = filter or BoardFilter()
    now = datetime.now(timezone.utc)
    if board == "triage":
        rows = archived_rows(session) if archived else triage_rows(session)
        return compute_facets(
            rows, f, now,
            {"source": "source", "status": "status"},
            {"source": "source", "status": "status"},
            lambda rs, ff: [r for r in rs if matches_common(r, ff, now)],
        )
    if board == "shortlist":
        facts = load_facts(facts_path) if Path(facts_path).exists() else None
        rows = shortlist_rows(session, facts=facts)
        facet_filter_attr = {
            "remote": "remote", "sponsorship": "sponsorship", "seniority": "seniority",
            "employmentType": "employment_type", "companySize": "company_size",
            "industry": "industry", "country": "country", "region": "region", "city": "city",
        }
        def _pred(rs, ff):
            state = to_filter_state(ff)
            return [r for r in apply_filters(rs, state) if matches_common(r, ff, now)]
        return compute_facets(
            rows, f, now, facet_filter_attr, _SHORTLIST_ROW_ATTR, _pred, include_skills=True
        )
    return {}
```

- [ ] **Step 5: Run the facet test + full board suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/resume_tailor_harness/services/board_query.py src/resume_tailor_harness/services/board.py
git add src/resume_tailor_harness/services/board_query.py src/resume_tailor_harness/services/board.py tests/test_services_board.py
git commit -m "feat(board): excluding-self facet counts for triage + shortlist"
```

---

### Task 4: `BoardPage` envelope + filter query params on the GET endpoints

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/base.py` (add `BoardPage`)
- Modify: `src/resume_tailor_harness/api/mappers.py` (add `to_board_page`)
- Modify: `src/resume_tailor_harness/api/routers/boards.py` (filter params + facets)
- Test: `tests/api/test_boards.py` (append)

**Interfaces:**

- Consumes: `board.list_*`, `board.board_facets`, `BoardFilter`, `parse_csv` (Tasks 1–3).
- Produces: `BoardPage[T]` = `Page[T]` + `facets: dict[str, dict[str, int]]` + `total: int`; dependency `board_filter_params(...) -> BoardFilter`.

`BoardPage` extends the existing envelope **additively** (`data` + `pagination`
unchanged; `facets` + `total` added) so existing clients keep parsing.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_boards.py  (append)
def test_triage_filter_params_and_facets_envelope():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.rejected.value, source="adzuna", fit_score=10, company="A")
        _seed(client.app, status=JobStatus.rejected.value, source="lever", fit_score=10, company="B")
        body = client.get("/api/triage?source=adzuna").json()
    assert [r["company"] for r in body["data"]] == ["A"]
    assert body["total"] == 1
    assert body["facets"]["source"] == {"adzuna": 1, "lever": 1}


def test_shortlist_q_filter():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.shortlisted.value, fit_score=90, company="Acme")
        _seed(client.app, status=JobStatus.shortlisted.value, fit_score=80, company="Beta")
        body = client.get("/api/shortlist?q=acme").json()
    assert [r["company"] for r in body["data"]] == ["Acme"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -v -k "facets_envelope or q_filter"`
Expected: FAIL — no `total`/`facets` keys; `source`/`q` ignored.

- [ ] **Step 3: Add `BoardPage` to `base.py`**

```python
# src/resume_tailor_harness/api/schemas/base.py  (append; add Field to the pydantic import)
class BoardPage(CamelModel, Generic[T]):
    data: list[T]
    pagination: Pagination
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)
    total: int = 0
```

- [ ] **Step 4: Add `to_board_page` to `mappers.py`**

```python
# src/resume_tailor_harness/api/mappers.py  (append)
from resume_tailor_harness.api.schemas.base import BoardPage


def to_board_page(service_page, item_model, facets: dict) -> BoardPage:
    return BoardPage(
        data=[item_model.model_validate(row) for row in service_page.data],
        pagination=Pagination(
            page=service_page.page, page_size=service_page.page_size,
            total_items=service_page.total_items, total_pages=service_page.total_pages,
        ),
        facets=facets,
        total=service_page.total_items,
    )
```

- [ ] **Step 5: Rewrite `boards.py` with the filter dependency**

```python
# src/resume_tailor_harness/api/routers/boards.py  (full replacement)
"""Read-only board lists: shortlist, pipeline, triage. Server-side filter + facets."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.mappers import to_board_page
from resume_tailor_harness.api.schemas.base import BoardPage
from resume_tailor_harness.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_tailor_harness.services import board
from resume_tailor_harness.services.board_query import BoardFilter, parse_csv

router = APIRouter()


def board_filter_params(
    q: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    max_fit: int | None = Query(None, alias="maxFit"),
    min_salary: int | None = Query(None, alias="minSalary"),
    stale_days: int | None = Query(None, alias="staleDays"),
    sort: str | None = Query(None, alias="sortBy"),
    preset: str = "balanced",
    source: str | None = None,
    status: str | None = None,
    remote: str | None = None,
    sponsorship: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = Query(None, alias="employmentType"),
    industry: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    company_size: str | None = Query(None, alias="companySize"),
    skills: str | None = None,
) -> BoardFilter:
    return BoardFilter(
        q=q, min_fit=min_fit, max_fit=max_fit, min_salary=min_salary, stale_days=stale_days,
        sort=sort, preset=preset,
        source=parse_csv(source), status=parse_csv(status), remote=parse_csv(remote),
        sponsorship=parse_csv(sponsorship), seniority=parse_csv(seniority),
        employment_type=parse_csv(employment_type), industry=parse_csv(industry),
        country=parse_csv(country), region=parse_csv(region), city=parse_csv(city),
        company_size=parse_csv(company_size), skills=parse_csv(skills),
    )


@router.get("/shortlist", response_model=BoardPage[ShortlistItem])
def get_shortlist(
    flt: BoardFilter = Depends(board_filter_params),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_shortlist(session, filter=flt, page=page, page_size=page_size)
    facets = board.board_facets(session, "shortlist", filter=flt)
    return to_board_page(result, ShortlistItem, facets)


@router.get("/pipeline", response_model=BoardPage[PipelineItem])
def get_pipeline(
    flt: BoardFilter = Depends(board_filter_params),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_pipeline(session, filter=flt, page=page, page_size=page_size)
    return to_board_page(result, PipelineItem, {})


@router.get("/triage", response_model=BoardPage[TriageItem])
def get_triage(
    archived: bool = False,
    flt: BoardFilter = Depends(board_filter_params),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_triage(session, filter=flt, archived=archived, page=page, page_size=page_size)
    facets = board.board_facets(session, "triage", filter=flt, archived=archived)
    return to_board_page(result, TriageItem, facets)
```

- [ ] **Step 6: Run board API tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -v`
Expected: PASS — new cases plus the existing pagination/status/bearer tests (those read `data`/`pagination`, still present).

- [ ] **Step 7: Lint + commit**

```bash
ruff check src/resume_tailor_harness/api
git add src/resume_tailor_harness/api/schemas/base.py src/resume_tailor_harness/api/mappers.py src/resume_tailor_harness/api/routers/boards.py tests/api/test_boards.py
git commit -m "feat(api): BoardPage envelope (facets+total) + filter query params"
```

---

### Task 5: `bulk_apply` service + `POST /api/jobs/bulk`

**Files:**

- Modify: `src/resume_tailor_harness/services/board.py` (add `resolve_ids`, `bulk_apply`)
- Create: `src/resume_tailor_harness/api/schemas/bulk.py`
- Modify: `src/resume_tailor_harness/api/routers/jobs.py` (add the endpoint)
- Test: `tests/test_services_board.py`, `tests/api/test_job_mutations.py` (append)

**Interfaces:**

- Consumes: `archive_job`, `restore_job`, `delete_job`, `has_progress`, `get_job` (`tracking/repository`); `set_stage` (`board`); `list_triage`/`list_shortlist`/`list_pipeline` (for `scope="query"` id resolution); `JobStatus` (`tracking/tables`).
- Produces: `BulkResult` dataclass `{affected:int, skipped:int, reasons:dict[str,int]}`; `bulk_apply(session, *, board, action, scope, filter, ids, status, dry_run) -> BulkResult`. Schemas `BulkRequest` / `BulkResultOut`.

Actions: `archive`, `restore`, `delete`, `approve` (= setStatus `approved`), `setStatus`
(requires `status`). `delete`, `approve`, and `setStatus` skip `has_progress` rows
→ `reasons["hasProgress"]`.
`dry_run=True` mutates nothing but returns the same counts.

- [ ] **Step 1: Write the failing service tests**

```python
# tests/test_services_board.py  (append)
from resume_tailor_harness.services.board import bulk_apply
from resume_tailor_harness.tracking.tables import ResumeVersion


def test_bulk_delete_by_query_skips_progress_and_reports():
    with _session() as session:
        _job(session, status=JobStatus.rejected.value, source="adzuna", fit_score=10)
        protected = _job(session, status=JobStatus.rejected.value, source="adzuna", fit_score=10)
        assert protected.id is not None
        session.add(ResumeVersion(job_id=protected.id))  # makes a triage-visible row progress-guarded
        session.commit()
        res = bulk_apply(
            session, board="triage", action="delete", scope="query",
            filter=BoardFilter(source={"adzuna"}),
        )
    assert res.affected == 1
    assert res.skipped == 1
    assert res.reasons.get("hasProgress") == 1


def test_bulk_archive_dry_run_mutates_nothing():
    with _session() as session:
        jid = _job(session, status=JobStatus.rejected.value, fit_score=10).id
        res = bulk_apply(session, board="triage", action="archive", scope="ids",
                         ids=[jid], dry_run=True)
        from resume_tailor_harness.tracking.repository import get_job
        assert get_job(session, jid).archived_at is None
    assert res.affected == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -v -k bulk`
Expected: FAIL — `bulk_apply` undefined.

- [ ] **Step 3: Implement `resolve_ids` + `bulk_apply` in `board.py`**

```python
# src/resume_tailor_harness/services/board.py  (append)
from dataclasses import dataclass, field

from resume_tailor_harness.tracking.tables import JobStatus


@dataclass
class BulkResult:
    affected: int = 0
    skipped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


_LIST_FOR_BOARD = {"triage": list_triage, "shortlist": list_shortlist, "pipeline": list_pipeline}


def resolve_ids(session: Session, board: str, filter: BoardFilter, *, archived: bool) -> list[int]:
    lister = _LIST_FOR_BOARD[board]
    kwargs = {"filter": filter, "page": 1, "page_size": 1_000_000}
    if board == "triage":
        kwargs["archived"] = archived
    page = lister(session, **kwargs)
    return [r.job_id for r in page.data]


def bulk_apply(
    session: Session, *, board: str, action: str, scope: str,
    filter: BoardFilter | None = None, ids: list[int] | None = None,
    status: str | None = None, archived: bool = False, dry_run: bool = False,
) -> BulkResult:
    if scope == "query":
        target = resolve_ids(session, board, filter or BoardFilter(), archived=archived)
    else:
        target = list(ids or [])
    res = BulkResult()
    for job_id in target:
        if action == "delete":
            if has_progress(session, job_id):
                res.skipped += 1
                res.reasons["hasProgress"] = res.reasons.get("hasProgress", 0) + 1
                continue
            if not dry_run and not delete_job(session, job_id):
                res.skipped += 1
                continue
            res.affected += 1
        elif action == "archive":
            if not dry_run:
                archive_job(session, job_id)
            res.affected += 1
        elif action == "restore":
            if not dry_run:
                restore_job(session, job_id)
            res.affected += 1
        elif action in ("approve", "setStatus"):
            if action == "setStatus" and status is None:
                raise ValueError("setStatus requires status")
            new_status = JobStatus.approved.value if action == "approve" else status
            if has_progress(session, job_id):
                # never silently re-stage a progress job from a bulk call
                res.skipped += 1
                res.reasons["hasProgress"] = res.reasons.get("hasProgress", 0) + 1
                continue
            if not dry_run:
                set_stage(session, job_id, new_status)
            res.affected += 1
        else:
            raise ValueError(f"Unknown bulk action {action!r}")
    return res
```

- [ ] **Step 4: Create `api/schemas/bulk.py`**

```python
# src/resume_tailor_harness/api/schemas/bulk.py
"""Request/response for the act-by-query bulk endpoint."""

from __future__ import annotations

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel


class BulkRequest(CamelModel):
    board: str                       # triage | shortlist | pipeline
    action: str                      # archive | restore | delete | approve | setStatus
    scope: str = "ids"               # ids | query
    ids: list[int] = Field(default_factory=list)
    status: str | None = None        # required when action == setStatus
    archived: bool = False           # triage query scope: act over archived rows
    dry_run: bool = False
    # filter mirrors the board query params (camelCase sets as arrays on the wire)
    q: str | None = None
    min_fit: int | None = None
    max_fit: int | None = None
    min_salary: int | None = None
    stale_days: int | None = None
    source: list[str] = Field(default_factory=list)
    status_in: list[str] = Field(default_factory=list)
    remote: list[str] = Field(default_factory=list)
    sponsorship: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    employment_type: list[str] = Field(default_factory=list)
    industry: list[str] = Field(default_factory=list)
    country: list[str] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    city: list[str] = Field(default_factory=list)
    company_size: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class BulkResultOut(CamelModel):
    affected: int
    skipped: int
    reasons: dict[str, int]
```

Note: the body field for the status **filter** is `status_in` (camel `statusIn`) to avoid
clashing with the `status` **action argument** for `setStatus`.

- [ ] **Step 5: Add the endpoint to `jobs.py`**

```python
# src/resume_tailor_harness/api/routers/jobs.py  (append; add imports at top)
from resume_tailor_harness.api.schemas.bulk import BulkRequest, BulkResultOut
from resume_tailor_harness.services.board import bulk_apply
from resume_tailor_harness.services.board_query import BoardFilter

_VALID_ACTIONS = {"archive", "restore", "delete", "approve", "setStatus"}
_VALID_BOARDS = {"triage", "shortlist", "pipeline"}


def _filter_from_body(b: BulkRequest) -> BoardFilter:
    return BoardFilter(
        q=b.q, min_fit=b.min_fit, max_fit=b.max_fit, min_salary=b.min_salary,
        stale_days=b.stale_days, source=set(b.source), status=set(b.status_in),
        remote=set(b.remote), sponsorship=set(b.sponsorship), seniority=set(b.seniority),
        employment_type=set(b.employment_type), industry=set(b.industry),
        country=set(b.country), region=set(b.region), city=set(b.city),
        company_size=set(b.company_size), skills=set(b.skills),
    )


@router.post("/jobs/bulk", response_model=BulkResultOut)
def bulk_jobs(body: BulkRequest, session: Session = Depends(get_session)):
    if body.action not in _VALID_ACTIONS:
        raise ApiException(422, "VALIDATION_ERROR", f"Unknown action '{body.action}'")
    if body.board not in _VALID_BOARDS:
        raise ApiException(422, "VALIDATION_ERROR", f"Unknown board '{body.board}'")
    if body.action == "setStatus":
        if body.status is None or body.status not in {s.value for s in JobStatus}:
            raise ApiException(422, "VALIDATION_ERROR", "setStatus requires a valid 'status'")
    if body.scope not in {"ids", "query"}:
        raise ApiException(422, "VALIDATION_ERROR", f"Unknown scope '{body.scope}'")
    result = bulk_apply(
        session, board=body.board, action=body.action, scope=body.scope,
        filter=_filter_from_body(body), ids=body.ids, status=body.status,
        archived=body.archived, dry_run=body.dry_run,
    )
    return BulkResultOut.model_validate(result)
```

- [ ] **Step 6: Write + run the API test**

```python
# tests/api/test_job_mutations.py  (append)
def test_bulk_delete_by_query_endpoint():
    client = _client()
    with client:
        _seed(client.app, status=JobStatus.rejected.value, source="adzuna", fit_score=5)
        protected = _seed(client.app, status=JobStatus.rejected.value, source="adzuna", fit_score=5)
        with get_session(client.app.state.engine) as session:
            session.add(ResumeVersion(job_id=protected))
            session.commit()
        body = client.post("/api/jobs/bulk", json={
            "board": "triage", "action": "delete", "scope": "query", "source": ["adzuna"],
        }).json()
    assert body["affected"] == 1
    assert body["skipped"] == 1
    assert body["reasons"]["hasProgress"] == 1
```

(Reuse the `_client`/`_seed` helpers already in `test_job_mutations.py`; import
`get_session` and `ResumeVersion` if they are not already in that file.)

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py tests/api/test_job_mutations.py -v -k bulk`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
ruff check src/resume_tailor_harness tests
git add src/resume_tailor_harness/services/board.py src/resume_tailor_harness/api/schemas/bulk.py src/resume_tailor_harness/api/routers/jobs.py tests
git commit -m "feat(api): act-by-query bulk endpoint (archive/restore/delete/approve/setStatus)"
```

---

### Task 6: Database indexes for filter/sort at scale

**Files:**

- Modify: `src/resume_tailor_harness/db.py` (`init_db` — add `ensure_indexes`)
- Test: `tests/test_db_indexes.py` (create)

**Interfaces:**

- Produces: `ensure_indexes(engine)` — idempotent `CREATE INDEX IF NOT EXISTS` for `status`, `archived_at`, `fit_score`, `source`, `company` on the `jobs` table; called at the end of `init_db`.

Using `CREATE INDEX IF NOT EXISTS` (not `Field(index=True)`) so **existing** databases
gain the indexes without a migration framework.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_indexes.py
from sqlalchemy import text

from resume_tailor_harness.db import get_session, init_db, make_engine


def test_job_filter_indexes_exist():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        names = {r[0] for r in session.exec(text(
            "select name from sqlite_master where type='index' and tbl_name='jobs'"
        ))}
    for col in ("status", "archived_at", "fit_score", "source", "company"):
        assert any(col in n for n in names), f"missing index for {col}: {names}"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_indexes.py -v`
Expected: FAIL — indexes absent.

- [ ] **Step 3: Add `ensure_indexes` and call it from `init_db`**

In `src/resume_tailor_harness/db.py`, add and call at the end of `init_db(engine)` (after
`SQLModel.metadata.create_all(engine)`):

```python
from sqlalchemy import text

_JOB_INDEXES = {
    "ix_job_status": "status",
    "ix_job_archived_at": "archived_at",
    "ix_job_fit_score": "fit_score",
    "ix_job_source": "source",
    "ix_job_company": "company",
}


def ensure_indexes(engine) -> None:
    with engine.begin() as conn:
        for name, col in _JOB_INDEXES.items():
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON jobs ({col})'))
```

Call `ensure_indexes(engine)` as the last line of `init_db`. Use the explicit table name
from `Job.__tablename__` (`jobs` in the current tree).

- [ ] **Step 4: Run the index test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_indexes.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/resume_tailor_harness/db.py tests/test_db_indexes.py
git add src/resume_tailor_harness/db.py tests/test_db_indexes.py
git commit -m "perf(db): idempotent indexes on job filter/sort columns"
```

---

### Task 7: Regenerate the OpenAPI + TypeScript contract

**Files:**

- Modify: `contracts/openapi.json` (generated)
- Modify: `contracts/ts/api.ts` (generated)
- Verify: `tests/api/test_openapi_contract.py` (drift gate — should pass after regen)

**Interfaces:**

- Consumes: every schema/endpoint added in Tasks 4–5.
- Produces: the frozen contract the web plan consumes (`BoardPage`, `BulkRequest`, `BulkResultOut`, new query params).

- [ ] **Step 1: Run the contract drift gate to confirm it now fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: FAIL — generated contract is stale (new params/schemas not yet exported).

- [ ] **Step 2: Regenerate**

Run: `bash scripts/gen_ts_client.sh`
Expected: `contracts/openapi.json` and `contracts/ts/api.ts` updated with `BoardPage`,
`facets`, `total`, the new board query params, and `/api/jobs/bulk`.

- [ ] **Step 3: Re-run the drift gate + full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (entire suite).

- [ ] **Step 4: Commit**

```bash
git add contracts/
git commit -m "chore(contracts): regenerate OpenAPI + TS client for board filter/facets/bulk"
```

---

## Self-Review

- **Spec coverage:** server-side filter/sort/paginate (Task 2) ✓; facet counts excl-self (Task 3) ✓; `facets`+`total` envelope (Task 4) ✓; act-by-query bulk + dryRun + progress-skip, all actions (Task 5) ✓; indexes (Task 6) ✓; contract regen + drift gate (Task 7) ✓; Approach A preserved — no criteria columns ✓; additive params ✓.
- **Placeholder scan:** every code step shows complete code; no TBD/TODO. Task 5 Step 6 references existing `_client`/`_seed` with an explicit fallback instruction.
- **Type consistency:** `BoardFilter` fields used identically across Tasks 1/2/4/5; `BulkResult`/`BulkResultOut` (`affected`/`skipped`/`reasons`) match; `board_facets(session, board, ...)` signature consistent Tasks 3/4; `to_board_page(page, model, facets)` consistent Tasks 4. The body filter field is `status_in`/`statusIn` (not `status`) to avoid colliding with the setStatus argument.
- **Naming (api-and-interface-design):** plural resource nouns retained; camelCase params/fields; `BoardPage` extends additively; one error envelope; pagination preserved; `dryRun`/`scope` are explicit enums validated at the boundary.

---

## Open follow-ups (not in scope here)

- Shortlist `source` facet would require widening `ShortlistRow` with `source`; deferred (YAGNI) — source filtering lives on Triage where it matters for pruning.
- `resolve_ids` paginates with `page_size=1_000_000` to fetch all matching ids in one shot; fine at 1k–10k. If volumes ever exceed that, give the board listers an `unpaginated` path.
- Per §7 of the spec, the React-side filter compute is retired in the web plan; once it lands, drop the TS half of `2026-06-23-shortlist-filter-contract` and keep the Python predicate behind an API golden test.
