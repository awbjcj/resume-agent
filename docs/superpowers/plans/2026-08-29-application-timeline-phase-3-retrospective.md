# Application Timeline — Phase 3: The Retrospective — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the recorded timeline into something you can read across jobs — a spreadsheet grid, two CSV exports, and four charts that say where applications die and how long each stage takes, without lying about small samples.

**Architecture:** One pivot function turns the event log into rows; the grid, both CSVs, and the analytics endpoint all read from it, so the presentations cannot disagree. A separate aggregation module computes funnel flows and stage cycle times. The small-sample rule is enforced in one shared web component, not repeated per chart.

**Tech Stack:** Python 3.13, FastAPI, pytest. React 19 + TypeScript, recharts 3.10 (`Sankey`, `FunnelChart`, `Treemap`, `RadialBar` all verified present in `web/node_modules/recharts/types/chart/` — **no new dependency**), TanStack Query, vitest.

**Prerequisite:** Phases 1 and 2 complete and merged.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-29-application-timeline-design.md`. Read the "Analytics" and "Surfaces" sections before Task 1.
- **Tests run offline.** `.venv/Scripts/python.exe -m pytest`.
- **No new Python or npm dependencies.**
- **`GET /api/analytics` must not change.** The existing cohort tables keep working untouched; new charts read a new endpoint.
- **The small-sample rule is structural, not advisory.** Counts always shown; rates always annotated `n=`; rates greyed below n=10; rates suppressed entirely below n=3. Job-search datasets are permanently small — this is not a phase to grow out of.
- **`custom` events are excluded from the funnel and cycle-time charts** and labelled as such, so the numbers stay honest.
- **Time is injectable.** Any function reading the clock takes `now: datetime | None = None`.
- **Load the `dataviz` skill before writing any chart component** (Task 7). Four independently styled recharts components is exactly the failure this phase must avoid.
- **After any API schema change**, run `make openapi && make client` and commit `contracts/` plus `web/src/lib/api/schema.ts`.

## Correctness amendments (reviewed 2026-08-29)

These amendments are binding and supersede narrower snippets later in the plan.

- `timeline_pivot.py` loads one canonical application-timeline dataset containing
  applications, jobs, and their complete ordered event rows. The display pivot,
  wide CSV, and long CSV are projections of that dataset. The long CSV must not
  issue an unrelated event query that can drift from the grid/export filters.
- Event order is deterministic: `occurred_at` ascending, nulls last, then
  `created_at`, then `id`. Technical-round columns use the stored `sequence`
  (including manual overrides), not a fresh enumeration that discards Phase 1's
  sequencing contract. Duplicate keys resolve deterministically and remain a
  warned, not blocked, condition.
- Cycle time uses `total_seconds() / 86400`, not `timedelta.days`, so sub-day
  stages are not silently rounded down to zero. The archived-row test must
  actually archive a job and prove exclusion.
- `/applications` is sortable as the approved design requires. Client-side
  controls cover company, status, and sort order; the default remains newest
  activity first. Tests pin sorting as well as filtering.
- Date cells use compact visible dates, but metadata cannot exist only in a
  native `title` attribute. Each populated cell exposes the same result,
  modality, platform, and interviewer detail to keyboard and touch users through
  an accessible disclosure/tooltip. The scroll container is `min-w-0` and owns
  horizontal overflow so the document never scrolls sideways.
- Sankey edge rates use the source node's total outgoing count as `n`. Counts and
  `n=` always render; percentages are muted below `n=10` and omitted below
  `n=3`. `RateLabel` is consumed by the stage-flow presentation rather than
  becoming dead code. Custom events stay visibly excluded.
- Pipeline timeline transforms take an injectable `now`; they do not read
  `Date.now()` internally. Zero-span date ranges and same-day pipelines have a
  deterministic centered layout.
- Offer comparison never implies currency conversion. Bars and tooltips carry
  their ISO currency, and mixed currencies are identified in the UI rather than
  plotted against a falsely shared monetary axis without explanation.
- The referenced `dataviz` skill is optional at execution time. If unavailable,
  use the repository's semantic CSS variables and the requested Emil/frontend
  design skills, then verify desktop/mobile layout, focus order, contrast,
  reduced motion, console, and network behavior in a real browser.
- Repeated and out-of-order stages are valid timeline facts but cannot be fed as
  cyclic links to Recharts Sankey. The flow projection collapses self-links and
  backward canonical-stage links, the web transform repeats that defense, and
  exit links use semantic colors in the SVG itself.
- Wide CSV/grid stage columns include terminal `rejected` and `withdrawn` dates.
  Long CSV preserves numeric zeroes, and every exported string is neutralized
  when it could be interpreted as a spreadsheet formula.
- Offer analytics emits every dated `offer_received` event that has at least one
  compensation component, newest first. It carries stable event/sequence
  identity so negotiation revisions from the same company remain distinct.
- Phase 1 sequencing is completed as part of this work: positive manual round
  overrides are exposed in the form; ordinary inserts are numbered by canonical
  chronological order; deletion closes gaps for an auto-numbered group; sparse
  manual groups are preserved; duplicate technical cells are logged and surfaced
  as visible overflow rather than silently disappearing.
- Manual round-order provenance is persisted separately from effective order.
  Automatic events fill the lowest unreserved positive positions in canonical
  date order; explicit values (including `1`) survive insert/delete. Clearing an
  override with PATCH `null`, changing date, or moving kind resequences both
  affected groups transactionally. The form displays only the explicit override,
  never an effective automatic value as though the user chose it.
- Event creation and status advancement share one database commit. A failure
  after the event is staged must roll back both the event and any newly created
  application instead of leaving status and history inconsistent.
- Funnel histories are projected once into strictly increasing canonical
  milestones. Flows, terminal exits, and cycle-time pairs all consume that same
  projection, so repeated/backward facts cannot split a candidate into
  disconnected paths or create misleading backward cycle rows.

---

## File Structure

| File                                                   | Responsibility                                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `src/resume_agent/tracking/timeline_pivot.py`          | **Create.** Event log → one row per application. The single source the grid, both CSVs, and the exports read. |
| `src/resume_agent/tracking/funnel.py`                  | **Create.** Sankey flows + stage cycle times. Aggregation only, no serialization.                             |
| `src/resume_agent/api/schemas/timeline_analytics.py`   | **Create.** Pivot and analytics response models.                                                              |
| `src/resume_agent/api/routers/applications.py`         | **Create.** Grid + both CSVs.                                                                                 |
| `src/resume_agent/api/routers/analytics.py`            | **Modify.** Add `GET /analytics/timeline`. Existing route untouched.                                          |
| `src/resume_agent/api/app.py`                          | **Modify.** Register the applications router.                                                                 |
| `web/src/features/applications/use-applications.ts`    | **Create.** Grid query hook.                                                                                  |
| `web/src/features/applications/ApplicationsTable.tsx`  | **Create.** The pivoted grid.                                                                                 |
| `web/src/features/applications/ApplicationsPage.tsx`   | **Create.** Page shell, filters, export buttons.                                                              |
| `web/src/app/router.tsx`                               | **Modify.** Add `/applications`.                                                                              |
| `web/src/components/layout/*`                          | **Modify.** Nav entry (locate the sidebar nav list).                                                          |
| `web/src/features/analytics/chart-theme.ts`            | **Create.** Shared palette + the small-sample helpers. One place, so four charts cannot drift.                |
| `web/src/features/analytics/RateLabel.tsx`             | **Create.** The small-sample rule as a component.                                                             |
| `web/src/features/analytics/StageFlowChart.tsx`        | **Create.** Sankey.                                                                                           |
| `web/src/features/analytics/CycleTimeChart.tsx`        | **Create.** Median-days bars.                                                                                 |
| `web/src/features/analytics/PipelineTimelineChart.tsx` | **Create.** Gantt of live applications.                                                                       |
| `web/src/features/analytics/OfferComparisonChart.tsx`  | **Create.** Stacked comp bars.                                                                                |
| `web/src/features/analytics/AnalyticsContainer.tsx`    | **Modify.** Mount the four charts above the existing cohort tables.                                           |

---

### Task 1: Timeline pivot

**Files:**

- Create: `src/resume_agent/tracking/timeline_pivot.py`
- Test: `tests/test_timeline_pivot.py`

**Interfaces:**

- Consumes: Phase 1's `ApplicationEvent`, `EventKind`, `REPEATABLE_KINDS`.
- Produces:
  - `@dataclass PivotCell(occurred_at, all_day, result, modality, platform, platform_other, interviewers, notes)`
  - `@dataclass PivotRow(job_id, company, title, status, source, fit_score, cells: dict[str, PivotCell], custom_count, total_comp, comp_currency, offer_deadline)`
  - `@dataclass PivotTable(rows: list[PivotRow], technical_round_columns: int, overflow_by_job: dict[int, int])`
  - `build_pivot(session, *, max_technical_rounds=6) -> PivotTable`

**Column key convention:** non-repeatable kinds key by their own name (`"recruiter_screen"`). `technical_round` keys as `"technical_round_1"`, `"technical_round_2"`, …. `technical_round_columns` is the max observed across all rows, capped; `overflow_by_job` records how many rounds each job has beyond the cap so the grid can render `+N` rather than silently dropping them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_timeline_pivot.py
from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.timeline_pivot import build_pivot
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def _application(session, company="Acme", status="interview", **job_kwargs):
    job = Job(source="greenhouse", company=company, title="SWE", **job_kwargs)
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, status=status)
    session.add(app)
    session.commit()
    session.refresh(app)
    return job, app


def _event(session, app, kind, day=None, **over):
    session.add(
        ApplicationEvent(
            application_id=app.id,
            kind=kind,
            occurred_at=_at(day) if day else None,
            **over,
        )
    )
    session.commit()


def test_each_application_is_one_row_keyed_by_kind():
    session = _session()
    _, app = _application(session)
    _event(session, app, "application_submitted", 3)
    _event(session, app, "recruiter_screen", 5)
    table = build_pivot(session)
    assert len(table.rows) == 1
    row = table.rows[0]
    assert row.company == "Acme"
    assert row.cells["application_submitted"].occurred_at == _at(3)
    assert row.cells["recruiter_screen"].occurred_at == _at(5)


def test_technical_rounds_get_numbered_columns():
    session = _session()
    _, app = _application(session)
    for day in (9, 11, 13):
        _event(session, app, "technical_round", day)
    table = build_pivot(session)
    assert table.technical_round_columns == 3
    assert table.rows[0].cells["technical_round_2"].occurred_at == _at(11)


def test_column_count_grows_to_the_maximum_observed():
    session = _session()
    _, one = _application(session, company="One")
    _event(session, one, "technical_round", 9)
    _, five = _application(session, company="Five")
    for day in (9, 10, 11, 12, 13):
        _event(session, five, "technical_round", day)
    assert build_pivot(session).technical_round_columns == 5


def test_rounds_beyond_the_cap_are_reported_as_overflow_not_dropped():
    session = _session()
    job, app = _application(session)
    for day in range(1, 10):  # nine rounds, cap is six
        _event(session, app, "technical_round", day)
    table = build_pivot(session, max_technical_rounds=6)
    assert table.technical_round_columns == 6
    assert table.overflow_by_job[job.id] == 3


def test_custom_events_are_counted_not_columned():
    session = _session()
    _, app = _application(session)
    _event(session, app, "custom", 3, custom_label="referral ping")
    _event(session, app, "custom", 4, custom_label="coffee chat")
    row = build_pivot(session).rows[0]
    assert row.custom_count == 2
    assert not any(key.startswith("custom") for key in row.cells)


def test_offer_row_carries_derived_total_comp_from_the_latest_offer():
    session = _session()
    _, app = _application(session, status="offer")
    _event(session, app, "offer_received", 20, comp_base=180000, comp_currency="USD")
    _event(
        session,
        app,
        "offer_received",
        25,
        comp_base=195000,
        comp_signing=25000,
        comp_currency="USD",
    )
    row = build_pivot(session).rows[0]
    assert row.total_comp == 220000  # the negotiated one, not the first
    assert row.comp_currency == "USD"


def test_offer_deadline_is_surfaced_on_the_row():
    session = _session()
    _, app = _application(session, status="offer")
    _event(session, app, "offer_deadline", 27)
    assert build_pivot(session).rows[0].offer_deadline == _at(27)


def test_archived_jobs_are_excluded():
    session = _session()
    job, app = _application(session)
    _event(session, app, "recruiter_screen", 3)
    job.archived_at = _at(4)
    session.add(job)
    session.commit()
    assert build_pivot(session).rows == []


def test_applications_with_no_events_still_appear():
    session = _session()
    _application(session, status="ready")
    table = build_pivot(session)
    assert len(table.rows) == 1
    assert table.rows[0].cells == {}


def test_rows_sort_by_most_recent_activity_first():
    session = _session()
    _, old = _application(session, company="Old")
    _event(session, old, "recruiter_screen", 3)
    _, recent = _application(session, company="Recent")
    _event(session, recent, "recruiter_screen", 20)
    assert [r.company for r in build_pivot(session).rows] == ["Recent", "Old"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_timeline_pivot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking.timeline_pivot'`

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/tracking/timeline_pivot.py`:

- The three dataclasses above, all frozen except `PivotTable`.
- `build_pivot(session, *, max_technical_rounds=6)`:
  1. Load `(Application, Job)` pairs excluding archived jobs, then all events for those applications in **one** query keyed by `application_id` — never per-row (the codebase has fought N+1s here before; see the board-read work in the hot-paths table).
  2. For each application, sort its events by `occurred_at` (nulls last).
  3. Non-repeatable kinds: key by kind, last-write-wins if duplicated.
  4. `technical_round`: key `technical_round_{n}` for n up to `max_technical_rounds`; count the remainder into `overflow_by_job`.
  5. `custom`: increment `custom_count`; never a column.
  6. `offer_received`: take the **latest** by date; `total_comp` = sum of the non-null components (`None` when all are null); carry `comp_currency`. This is the negotiated offer, not the first.
  7. `offer_deadline`: carry `occurred_at` onto the row.
  8. `technical_round_columns` = max round count across all rows, capped.
  9. Sort rows by most recent event date descending, undated last.

Add a module docstring stating that this is the single source the grid, both CSVs, and the exports read — so the presentations cannot disagree with each other.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_timeline_pivot.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking/timeline_pivot.py tests/test_timeline_pivot.py
git add src/resume_agent/tracking/timeline_pivot.py tests/test_timeline_pivot.py
git commit -m "feat(tracking): pivot the event log into application rows"
```

---

### Task 2: Funnel flows and cycle times

**Files:**

- Create: `src/resume_agent/tracking/funnel.py`
- Test: `tests/test_funnel.py`

**Interfaces:**

- Consumes: Phase 1's `FUNNEL_KINDS`, `EventResult`.
- Produces:
  - `@dataclass FlowEdge(source: str, target: str, count: int)`
  - `@dataclass StageCycleTime(from_kind: str, to_kind: str, median_days: float, sample_size: int)`
  - `stage_flows(session) -> list[FlowEdge]`
  - `stage_cycle_times(session) -> list[StageCycleTime]`

**Flow semantics:** for each application, take its funnel-kind events in date order. Emit an edge for each consecutive pair. Then emit one **exit** edge from the last stage reached to `"rejected"`, `"no_response"`, or `"withdrawn"` — determined by the application's terminal status, or by the last event's `result` when status is non-terminal and the last event resulted in `no_response`. Applications still live emit no exit edge; they are simply where they are.

**Median, not mean:** one application that sat for 200 days would swamp a mean. The median is what "is day-12 silence normal?" actually asks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_funnel.py
from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.funnel import stage_cycle_times, stage_flows
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def _app(session, status="interview"):
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, status=status)
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def _event(session, app, kind, day, **over):
    session.add(
        ApplicationEvent(
            application_id=app.id, kind=kind, occurred_at=_at(day), **over
        )
    )
    session.commit()


def _edge(edges, source, target):
    return next(
        (e.count for e in edges if e.source == source and e.target == target), 0
    )


def test_consecutive_stages_become_edges():
    session = _session()
    app = _app(session)
    _event(session, app, "application_submitted", 3)
    _event(session, app, "recruiter_screen", 5)
    _event(session, app, "technical_round", 9)
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "recruiter_screen") == 1
    assert _edge(edges, "recruiter_screen", "technical_round") == 1


def test_edges_accumulate_across_applications():
    session = _session()
    for _ in range(3):
        app = _app(session)
        _event(session, app, "application_submitted", 3)
        _event(session, app, "recruiter_screen", 5)
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "recruiter_screen") == 3


def test_a_rejected_application_emits_an_exit_edge_from_its_last_stage():
    session = _session()
    app = _app(session, status="rejected")
    _event(session, app, "application_submitted", 3)
    _event(session, app, "recruiter_screen", 5)
    assert _edge(stage_flows(session), "recruiter_screen", "rejected") == 1


def test_no_response_is_distinct_from_rejection():
    session = _session()
    app = _app(session, status="submitted")
    _event(session, app, "application_submitted", 3, result="no_response")
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "no_response") == 1
    assert _edge(edges, "application_submitted", "rejected") == 0


def test_a_live_application_emits_no_exit_edge():
    session = _session()
    app = _app(session, status="interview")
    _event(session, app, "application_submitted", 3)
    _event(session, app, "recruiter_screen", 5)
    edges = stage_flows(session)
    assert _edge(edges, "recruiter_screen", "rejected") == 0
    assert _edge(edges, "recruiter_screen", "no_response") == 0


def test_custom_events_never_enter_the_funnel():
    session = _session()
    app = _app(session)
    _event(session, app, "application_submitted", 3)
    _event(session, app, "custom", 4, custom_label="coffee chat")
    _event(session, app, "recruiter_screen", 5)
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "recruiter_screen") == 1
    assert all("custom" not in (e.source, e.target) for e in edges)


def test_cycle_time_is_the_median_gap_in_days():
    session = _session()
    for gap in (2, 4, 12):  # median 4, not the mean of 6
        app = _app(session)
        _event(session, app, "application_submitted", 1)
        _event(session, app, "recruiter_screen", 1 + gap)
    times = stage_cycle_times(session)
    entry = next(
        t
        for t in times
        if t.from_kind == "application_submitted" and t.to_kind == "recruiter_screen"
    )
    assert entry.median_days == 4
    assert entry.sample_size == 3


def test_cycle_time_reports_its_sample_size_so_the_ui_can_gate_on_it():
    session = _session()
    app = _app(session)
    _event(session, app, "application_submitted", 1)
    _event(session, app, "recruiter_screen", 3)
    assert stage_cycle_times(session)[0].sample_size == 1


def test_out_of_order_dates_never_produce_a_negative_gap():
    session = _session()
    app = _app(session)
    _event(session, app, "recruiter_screen", 3)
    _event(session, app, "application_submitted", 9)
    assert all(t.median_days >= 0 for t in stage_cycle_times(session))


def test_undated_and_archived_rows_are_ignored():
    session = _session()
    app = _app(session)
    _event(session, app, "application_submitted", 3)
    session.add(
        ApplicationEvent(application_id=app.id, kind="custom", custom_label="x")
    )
    session.commit()
    assert stage_flows(session) is not None  # no crash on the undated row


def test_empty_database_returns_empty_lists():
    session = _session()
    assert stage_flows(session) == []
    assert stage_cycle_times(session) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_funnel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tracking.funnel'`

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/tracking/funnel.py`:

- `_sequences(session) -> list[tuple[Application, list[ApplicationEvent]]]`: one batched load (reuse `upcoming_event_rows`-style joining, or add a sibling query), archived jobs excluded, events filtered to `kind in FUNNEL_KINDS` **and** `occurred_at is not None`, sorted by date. This filter is where `custom` drops out.
- `stage_flows`: consecutive pairs → edges, counted in a `Counter[(source, target)]`. Then the exit edge: if `application.status in {"rejected", "closed"}` emit `→ "rejected"` (or `→ "withdrawn"` for `closed`); elif the last event's `result == "no_response"` emit `→ "no_response"`; else nothing.
- `stage_cycle_times`: for each consecutive pair, collect `(to.occurred_at - from.occurred_at).days`, clamped at `>= 0` so a mis-dated event cannot produce a negative median. Use `statistics.median`. Return one entry per observed pair with its `sample_size`.
- Docstring: state why median rather than mean, and that `sample_size` exists so the UI can enforce the small-sample rule.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_funnel.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking/funnel.py tests/test_funnel.py
git add src/resume_agent/tracking/funnel.py tests/test_funnel.py
git commit -m "feat(tracking): funnel flows and stage cycle times"
```

---

### Task 3: Grid and CSV routes

**Files:**

- Create: `src/resume_agent/api/schemas/timeline_analytics.py`
- Create: `src/resume_agent/api/routers/applications.py`
- Modify: `src/resume_agent/api/app.py`
- Test: `tests/api/test_applications_routes.py`

**Interfaces:**

- Consumes: Task 1.
- Produces: `GET /api/applications`, `GET /api/applications.csv?shape=wide|long`.

**Both CSVs, deliberately:** wide is the grid you can read; long is one row per event, which is what feeds a pivot table in Sheets. Same pivot underneath, so they cannot disagree.

**The cap is display-only:** the wide CSV includes every technical-round column, uncapped. Truncating an export to fit a screen would be a data-loss bug.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_applications_routes.py
import csv
import io

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _job(client, company="Acme"):
    return client.post(
        "/api/jobs", json={"jdText": "x", "company": company, "title": "SWE"}
    ).json()["id"]


def _event(client, job_id, kind, day, **over):
    body = {"kind": kind, "occurredAt": f"2026-03-{day:02d}T12:00:00Z"}
    body.update(over)
    return client.post(f"/api/jobs/{job_id}/events", json=body)


def test_grid_returns_one_row_per_application_with_keyed_cells():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 3)
        _event(client, job_id, "technical_round", 9)
        body = client.get("/api/applications").json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["company"] == "Acme"
    assert "applicationSubmitted" in row["cells"] or "application_submitted" in row["cells"]
    assert body["technicalRoundColumns"] == 1


def test_grid_reports_overflow_rather_than_dropping_rounds():
    client = _client()
    with client:
        job_id = _job(client)
        for day in range(1, 10):
            _event(client, job_id, "technical_round", day)
        body = client.get("/api/applications").json()
    assert body["technicalRoundColumns"] == 6
    assert body["rows"][0]["overflowRounds"] == 3


def test_wide_csv_has_one_row_per_application():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 3)
        _event(client, job_id, "recruiter_screen", 5)
        resp = client.get("/api/applications.csv?shape=wide")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"


def test_long_csv_has_one_row_per_event():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 3)
        _event(client, job_id, "recruiter_screen", 5)
        resp = client.get("/api/applications.csv?shape=long")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"application_submitted", "recruiter_screen"}


def test_wide_csv_is_not_truncated_by_the_display_cap():
    client = _client()
    with client:
        job_id = _job(client)
        for day in range(1, 10):
            _event(client, job_id, "technical_round", day)
        resp = client.get("/api/applications.csv?shape=wide")
    header = list(csv.DictReader(io.StringIO(resp.text))).pop().keys()
    assert any("technical_round_9" in column for column in header)


def test_unknown_shape_is_422():
    client = _client()
    with client:
        resp = client.get("/api/applications.csv?shape=sideways")
    assert resp.status_code == 422


def test_empty_workspace_returns_an_empty_grid_and_a_header_only_csv():
    client = _client()
    with client:
        assert client.get("/api/applications").json()["rows"] == []
        text = client.get("/api/applications.csv?shape=wide").text
    assert text.strip().count("\n") == 0  # header only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_applications_routes.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Write minimal implementation**

`api/schemas/timeline_analytics.py`: `PivotCellOut`, `PivotRowOut` (with `cells: dict[str, PivotCellOut]`, `overflow_rounds: int`), `PivotTableOut` (`rows`, `technical_round_columns`). All `CamelModel`.

`api/routers/applications.py`:

- `GET /applications` → `PivotTableOut.model_validate(build_pivot(session))`.
- `GET /applications.csv` with `shape: str = "wide"`:
  - Reject anything but `wide`/`long` with `ApiException(422, "VALIDATION_ERROR", ...)`.
  - `wide`: `build_pivot(session, max_technical_rounds=999)` — **uncapped**, because the cap is a display concern. Columns: `job_id, company, title, status, source, fit_score`, then one date column per kind in `FUNNEL_KINDS` order, then `technical_round_1..n`, then `offer_deadline, total_comp, comp_currency, custom_count`.
  - `long`: one row per event — `job_id, company, title, kind, custom_label, sequence, occurred_at, all_day, timezone, duration_minutes, modality, platform, platform_other, location_or_link, interviewers, result, notes, reflection, comp_base, comp_bonus, comp_equity_annual, comp_signing, comp_currency, source`.
  - Build with `csv.DictWriter` into an `io.StringIO`; return a `Response` with `media_type="text/csv; charset=utf-8"` and a `Content-Disposition: attachment` filename.

Register in `app.py` beside the other guarded routers.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_applications_routes.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Regenerate the contract, lint, commit**

```bash
make openapi && make client
ruff check src/resume_agent/api/
git add src/resume_agent/api/ tests/api/test_applications_routes.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(api): applications grid and wide/long CSV exports"
```

---

### Task 4: Timeline analytics endpoint

**Files:**

- Modify: `src/resume_agent/api/routers/analytics.py`
- Modify: `src/resume_agent/api/schemas/timeline_analytics.py`
- Test: `tests/api/test_timeline_analytics.py`

**Interfaces:**

- Consumes: Tasks 1 and 2.
- Produces: `GET /api/analytics/timeline` → `TimelineAnalyticsOut(flows, cycle_times, active_pipeline, offers)`.

`GET /api/analytics` **must not change** — verify with a test.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_timeline_analytics.py
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def _job(client, company="Acme"):
    return client.post(
        "/api/jobs", json={"jdText": "x", "company": company, "title": "SWE"}
    ).json()["id"]


def _event(client, job_id, kind, day, **over):
    body = {"kind": kind, "occurredAt": f"2026-03-{day:02d}T12:00:00Z"}
    body.update(over)
    client.post(f"/api/jobs/{job_id}/events", json=body)


def test_existing_analytics_endpoint_is_unchanged():
    client = _client()
    with client:
        body = client.get("/api/analytics").json()
    assert set(body) == {"bySource", "byBand"}


def test_timeline_endpoint_returns_all_four_chart_payloads():
    client = _client()
    with client:
        body = client.get("/api/analytics/timeline").json()
    assert set(body) == {"flows", "cycleTimes", "activePipeline", "offers"}


def test_flows_carry_source_target_and_count():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 3)
        _event(client, job_id, "recruiter_screen", 5)
        flows = client.get("/api/analytics/timeline").json()["flows"]
    edge = next(f for f in flows if f["source"] == "application_submitted")
    assert edge["target"] == "recruiter_screen"
    assert edge["count"] == 1


def test_cycle_times_carry_the_sample_size_for_the_small_sample_rule():
    client = _client()
    with client:
        job_id = _job(client)
        _event(client, job_id, "application_submitted", 3)
        _event(client, job_id, "recruiter_screen", 7)
        entry = client.get("/api/analytics/timeline").json()["cycleTimes"][0]
    assert entry["medianDays"] == 4
    assert entry["sampleSize"] == 1


def test_active_pipeline_excludes_terminal_applications():
    client = _client()
    with client:
        live = _job(client, "Live")
        _event(client, live, "technical_round", 9)
        dead = _job(client, "Dead")
        _event(client, dead, "rejected", 10)
        pipeline = client.get("/api/analytics/timeline").json()["activePipeline"]
    assert [lane["company"] for lane in pipeline] == ["Live"]


def test_offers_carry_the_components_and_derived_total():
    client = _client()
    with client:
        job_id = _job(client)
        _event(
            client,
            job_id,
            "offer_received",
            20,
            compBase=180000,
            compBonus=27000,
            compEquityAnnual=60000,
            compSigning=25000,
            compCurrency="USD",
        )
        offers = client.get("/api/analytics/timeline").json()["offers"]
    assert offers[0]["totalComp"] == 292000
    assert offers[0]["compBase"] == 180000


def test_empty_workspace_returns_empty_arrays_not_nulls():
    client = _client()
    with client:
        body = client.get("/api/analytics/timeline").json()
    assert body == {"flows": [], "cycleTimes": [], "activePipeline": [], "offers": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_timeline_analytics.py -v`
Expected: FAIL — 404 on `/api/analytics/timeline`.

- [ ] **Step 3: Write minimal implementation**

Add to `api/schemas/timeline_analytics.py`: `FlowEdgeOut(source, target, count)`, `CycleTimeOut(from_kind, to_kind, median_days, sample_size)`, `PipelineLaneOut(job_id, company, title, status, events: list[LaneEventOut])` where `LaneEventOut(kind, sequence, occurred_at, all_day, result)`, `OfferOut(job_id, company, occurred_at, comp_base, comp_bonus, comp_equity_annual, comp_signing, comp_currency, total_comp)`, and `TimelineAnalyticsOut` wrapping all four.

Add to `api/routers/analytics.py`, leaving `get_analytics` untouched:

```python
@router.get("/analytics/timeline", response_model=TimelineAnalyticsOut)
def get_timeline_analytics(session: Session = Depends(get_session)):
    ...
```

Active pipeline = applications whose status is **not** in `{rejected, closed}`, each with its dated events in order. Offers = every `offer_received` event with at least one non-null comp component, newest first, `total_comp` derived.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_timeline_analytics.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Regenerate the contract, lint, commit**

```bash
make openapi && make client
ruff check src/resume_agent/api/
git add src/resume_agent/api/ tests/api/test_timeline_analytics.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(api): timeline analytics endpoint"
```

---

### Task 5: Web — applications grid page

**Files:**

- Create: `web/src/features/applications/use-applications.ts`
- Create: `web/src/features/applications/ApplicationsTable.tsx`
- Create: `web/src/features/applications/ApplicationsPage.tsx`
- Create: `web/src/features/applications/ApplicationsTable.test.tsx`
- Modify: `web/src/app/router.tsx:153` (add the route beside `analytics`)
- Modify: the sidebar nav list (locate with `grep -rn "Analytics" web/src/components web/src/app`)

**Interfaces:**

- Consumes: Task 3.
- Produces: `useApplications()` (query key `["applications"]`), `<ApplicationsTable table={PivotTable} />`, `<ApplicationsPage />`.

**Layout rule:** cells show the **date only**; modality, platform, result, and interviewers go in a `title` tooltip. A grid showing everything inline is forty columns wide and unreadable. The table scrolls horizontally inside its own container — the page body must never scroll sideways.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/applications/ApplicationsTable.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

import { ApplicationsTable } from "./ApplicationsTable";

const cell = (over: Record<string, unknown> = {}) => ({
  occurredAt: "2026-03-09T12:00:00Z",
  allDay: true,
  result: "advanced",
  modality: "virtual",
  platform: "zoom",
  ...over,
});

const table = (over: Record<string, unknown> = {}) => ({
  technicalRoundColumns: 2,
  rows: [
    {
      jobId: 42,
      company: "Acme",
      title: "Senior SWE",
      status: "interview",
      source: "greenhouse",
      fitScore: 82,
      overflowRounds: 0,
      customCount: 0,
      totalComp: null,
      compCurrency: null,
      offerDeadline: null,
      cells: {
        application_submitted: cell({ occurredAt: "2026-03-03T12:00:00Z" }),
        technical_round_1: cell(),
      },
    },
  ],
  ...over,
});

describe("ApplicationsTable", () => {
  it("renders one row per application, linked to the job", () => {
    render(<ApplicationsTable table={table() as never} />);
    expect(screen.getByRole("link", { name: /Acme/ })).toHaveAttribute(
      "href",
      expect.stringContaining("42"),
    );
  });

  it("renders a column per observed technical round", () => {
    render(<ApplicationsTable table={table() as never} />);
    expect(
      screen.getByRole("columnheader", { name: /Tech 1/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /Tech 2/ }),
    ).toBeInTheDocument();
  });

  it("shows only the date in a cell, with detail in the tooltip", () => {
    render(<ApplicationsTable table={table() as never} />);
    const cellEl = screen.getByTitle(/zoom/i);
    expect(cellEl.textContent).not.toMatch(/zoom/i);
    expect(cellEl.textContent).toMatch(/Mar/);
  });

  it("shows an em dash for a stage that never happened", () => {
    render(<ApplicationsTable table={table() as never} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("surfaces overflow rounds rather than hiding them", () => {
    const withOverflow = table();
    withOverflow.rows[0].overflowRounds = 3;
    render(<ApplicationsTable table={withOverflow as never} />);
    expect(screen.getByText("+3")).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been tracked", () => {
    render(
      <ApplicationsTable
        table={{ rows: [], technicalRoundColumns: 0 } as never}
      />,
    );
    expect(
      screen.getByText(/no applications tracked yet/i),
    ).toBeInTheDocument();
  });

  it("keeps horizontal overflow inside the table container", () => {
    const { container } = render(
      <ApplicationsTable table={table() as never} />,
    );
    expect(container.querySelector(".overflow-x-auto")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- ApplicationsTable`
Expected: FAIL — cannot resolve `./ApplicationsTable`.

- [ ] **Step 3: Write minimal implementation**

`use-applications.ts`: a `useQuery` on `["applications"]` hitting `GET /api/applications`.

`ApplicationsTable.tsx`:

- Empty state: "No applications tracked yet."
- Wrapper `<div className="overflow-x-auto">` around the `<table>`.
- Columns: Company (link to the job, reusing the same deep-link pattern as Phase 2's `UpcomingCard`), Title, Status, then Submitted / HR call / OA / Questionnaire / Phone screen / Tech 1..n / Design / Behavioral / HM / Onsite / Team match / Offer, then Deadline, TC, Other.
- Cells: `toLocaleDateString()` of `occurredAt`, or `—`. `title` attribute joins result, modality, platform, interviewers.
- `overflowRounds > 0` renders `+{n}` in the last tech column.
- `totalComp` rendered with `toLocaleString()` and currency.

`ApplicationsPage.tsx`: heading, a status filter and a company search input filtering client-side (the dataset is small — a server round-trip would be over-engineering), the table, and two download links: `/api/applications.csv?shape=wide` ("Export grid") and `?shape=long` ("Export events").

Add the route at `web/src/app/router.tsx` beside line 153's analytics entry:

```tsx
      { path: "applications", element: <SetupGate>{page(<ApplicationsPage />)}</SetupGate> },
```

and a nav entry labelled "Applications" next to Analytics.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- ApplicationsTable`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/applications/ web/src/app/router.tsx web/src/components/
git commit -m "feat(web): applications grid page with CSV exports"
```

---

### Task 6: Web — the small-sample rule

**Files:**

- Create: `web/src/features/analytics/chart-theme.ts`
- Create: `web/src/features/analytics/RateLabel.tsx`
- Create: `web/src/features/analytics/RateLabel.test.tsx`

**Interfaces:**

- Produces:
  - `SUPPRESS_BELOW = 3`, `GREY_BELOW = 10`
  - `rateConfidence(n: number): "suppressed" | "low" | "ok"`
  - `<RateLabel count={number} total={number} />`
  - `CHART_COLORS`, `STAGE_LABELS`, `axisProps`, `tooltipProps`

**Build this before any chart.** The rule must exist in exactly one place; four charts each doing their own thresholding is how it rots. Do this task before Task 7 even though no chart consumes it yet — that ordering is the point.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/analytics/RateLabel.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GREY_BELOW, SUPPRESS_BELOW, rateConfidence } from "./chart-theme";
import { RateLabel } from "./RateLabel";

describe("rateConfidence", () => {
  it("suppresses below three", () => {
    expect(rateConfidence(0)).toBe("suppressed");
    expect(rateConfidence(2)).toBe("suppressed");
  });

  it("greys from three up to nine", () => {
    expect(rateConfidence(3)).toBe("low");
    expect(rateConfidence(9)).toBe("low");
  });

  it("is confident from ten", () => {
    expect(rateConfidence(10)).toBe("ok");
    expect(rateConfidence(250)).toBe("ok");
  });

  it("uses the documented thresholds", () => {
    expect(SUPPRESS_BELOW).toBe(3);
    expect(GREY_BELOW).toBe(10);
  });
});

describe("RateLabel", () => {
  it("shows the count but no percentage below n=3", () => {
    render(<RateLabel count={1} total={2} />);
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("shows a greyed percentage with n= between 3 and 9", () => {
    render(<RateLabel count={2} total={5} />);
    const rate = screen.getByText(/40%/);
    expect(rate).toBeInTheDocument();
    expect(rate.className).toMatch(/muted/);
    expect(screen.getByText(/n=5/)).toBeInTheDocument();
  });

  it("shows a full-strength percentage with n= from 10", () => {
    render(<RateLabel count={5} total={20} />);
    const rate = screen.getByText(/25%/);
    expect(rate.className).not.toMatch(/muted/);
    expect(screen.getByText(/n=20/)).toBeInTheDocument();
  });

  it("never divides by zero", () => {
    render(<RateLabel count={0} total={0} />);
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(screen.getByText(/0 of 0/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- RateLabel`
Expected: FAIL — cannot resolve `./chart-theme`.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/src/features/analytics/chart-theme.ts
/**
 * Shared chart vocabulary and the small-sample rule.
 *
 * Job-search datasets are permanently small — twelve applications is a
 * normal state, not a phase to grow out of — so honesty about sample size
 * is structural here rather than a caveat in a tooltip. Counts always show;
 * rates are annotated with n=, greyed below ten, and suppressed below three.
 */

export const SUPPRESS_BELOW = 3;
export const GREY_BELOW = 10;

export type RateConfidence = "suppressed" | "low" | "ok";

export function rateConfidence(sampleSize: number): RateConfidence {
  if (sampleSize < SUPPRESS_BELOW) return "suppressed";
  if (sampleSize < GREY_BELOW) return "low";
  return "ok";
}
```

Add `CHART_COLORS` (a categorical array plus semantic entries for the exit branches — rejected, no-response, withdrawn), `STAGE_LABELS` (mirroring `KIND_LABELS` from Phase 1 Task 10 — note in a comment that they must stay in sync), and shared `axisProps` / `tooltipProps` objects so all four charts share axis styling.

**Load the `dataviz` skill now** and take the palette from it, mapped onto this project's existing CSS custom properties so charts respect the light/dark theme.

`RateLabel.tsx` renders per the rule: always `{count} of {total}`; the percentage appended only when not suppressed, with `text-muted-foreground` when `low`, and `n={total}` alongside.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- RateLabel`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/analytics/chart-theme.ts web/src/features/analytics/RateLabel.tsx web/src/features/analytics/RateLabel.test.tsx
git commit -m "feat(web): shared chart theme and the small-sample rule"
```

---

### Task 7: Web — the four charts

**Files:**

- Create: `web/src/features/analytics/StageFlowChart.tsx`
- Create: `web/src/features/analytics/CycleTimeChart.tsx`
- Create: `web/src/features/analytics/PipelineTimelineChart.tsx`
- Create: `web/src/features/analytics/OfferComparisonChart.tsx`
- Create: `web/src/features/analytics/charts.test.tsx`
- Modify: `web/src/features/analytics/use-analytics.ts` (add `useTimelineAnalytics`)
- Modify: `web/src/features/analytics/AnalyticsContainer.tsx`

**Interfaces:**

- Consumes: Tasks 4 and 6.
- Produces: the four chart components, each taking its slice of the timeline payload.

**Load the `dataviz` skill before writing these.**

**Testing note:** recharts renders through a `ResponsiveContainer` that measures zero in jsdom, so charts render nothing measurable. Test **empty states, guard rails, and the data transforms** — not SVG geometry. Extract each chart's data transform as a named export and test it directly; that is where the bugs actually live.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/analytics/charts.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CycleTimeChart, toCycleRows } from "./CycleTimeChart";
import { OfferComparisonChart, toOfferRows } from "./OfferComparisonChart";
import { PipelineTimelineChart, toLanes } from "./PipelineTimelineChart";
import { StageFlowChart, toSankeyData } from "./StageFlowChart";

describe("StageFlowChart", () => {
  it("renders an explanatory empty state rather than a blank box", () => {
    render(<StageFlowChart flows={[]} />);
    expect(screen.getByText(/not enough history/i)).toBeInTheDocument();
  });

  it("builds nodes and indexed links from flow edges", () => {
    const data = toSankeyData([
      { source: "application_submitted", target: "recruiter_screen", count: 5 },
      { source: "recruiter_screen", target: "rejected", count: 2 },
    ]);
    expect(data.nodes).toHaveLength(3);
    expect(data.links[0]).toEqual({ source: 0, target: 1, value: 5 });
    expect(data.links[1].value).toBe(2);
  });

  it("labels nodes with human stage names", () => {
    const data = toSankeyData([
      { source: "technical_phone_screen", target: "onsite_loop", count: 1 },
    ]);
    expect(data.nodes[0].name).toBe("Technical phone screen");
  });
});

describe("CycleTimeChart", () => {
  it("renders an empty state with no data", () => {
    render(<CycleTimeChart cycleTimes={[]} />);
    expect(screen.getByText(/not enough history/i)).toBeInTheDocument();
  });

  it("keeps low-sample rows but marks them", () => {
    const rows = toCycleRows([
      {
        fromKind: "application_submitted",
        toKind: "recruiter_screen",
        medianDays: 4,
        sampleSize: 1,
      },
      {
        fromKind: "recruiter_screen",
        toKind: "technical_round",
        medianDays: 6,
        sampleSize: 12,
      },
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].lowConfidence).toBe(true);
    expect(rows[1].lowConfidence).toBe(false);
  });

  it("labels each bar with both stages", () => {
    const rows = toCycleRows([
      {
        fromKind: "application_submitted",
        toKind: "recruiter_screen",
        medianDays: 4,
        sampleSize: 5,
      },
    ]);
    expect(rows[0].label).toBe("Application submitted → Recruiter screen");
  });
});

describe("PipelineTimelineChart", () => {
  it("renders an empty state when nothing is live", () => {
    render(<PipelineTimelineChart pipeline={[]} />);
    expect(screen.getByText(/no active applications/i)).toBeInTheDocument();
  });

  it("gives each application one lane sorted by its next event", () => {
    const lanes = toLanes([
      {
        jobId: 1,
        company: "Later",
        title: "SWE",
        status: "interview",
        events: [
          {
            kind: "technical_round",
            sequence: 1,
            occurredAt: "2026-03-20T12:00:00Z",
            allDay: false,
            result: "pending",
          },
        ],
      },
      {
        jobId: 2,
        company: "Sooner",
        title: "SWE",
        status: "interview",
        events: [
          {
            kind: "technical_round",
            sequence: 1,
            occurredAt: "2026-03-05T12:00:00Z",
            allDay: false,
            result: "pending",
          },
        ],
      },
    ]);
    expect(lanes.map((l) => l.company)).toEqual(["Sooner", "Later"]);
  });

  it("drops lanes whose events are all undated", () => {
    const lanes = toLanes([
      {
        jobId: 1,
        company: "Acme",
        title: "SWE",
        status: "interview",
        events: [],
      },
    ]);
    expect(lanes).toEqual([]);
  });
});

describe("OfferComparisonChart", () => {
  it("renders nothing at all when there are no offers", () => {
    const { container } = render(<OfferComparisonChart offers={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("splits an offer into its four components", () => {
    const rows = toOfferRows([
      {
        jobId: 1,
        company: "Acme",
        occurredAt: "2026-03-20T12:00:00Z",
        compBase: 180000,
        compBonus: 27000,
        compEquityAnnual: 60000,
        compSigning: 25000,
        compCurrency: "USD",
        totalComp: 292000,
      },
    ]);
    expect(rows[0]).toMatchObject({
      company: "Acme",
      base: 180000,
      bonus: 27000,
      equity: 60000,
      signing: 25000,
    });
  });

  it("treats missing components as zero so the bar still stacks", () => {
    const rows = toOfferRows([
      {
        jobId: 1,
        company: "Acme",
        occurredAt: "2026-03-20T12:00:00Z",
        compBase: 180000,
        compBonus: null,
        compEquityAnnual: null,
        compSigning: null,
        compCurrency: "USD",
        totalComp: 180000,
      },
    ]);
    expect(rows[0].bonus).toBe(0);
    expect(rows[0].base).toBe(180000);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm --prefix web run test:run -- charts`
Expected: FAIL — none of the four modules resolve.

- [ ] **Step 3: Write minimal implementation**

Each file exports a named transform plus the component.

`StageFlowChart.tsx` — `toSankeyData(flows)` builds `{ nodes: [{name}], links: [{source, target, value}] }` with **index-based** links (recharts `Sankey` requires indices, not names), names via `STAGE_LABELS`. Component: empty state "Not enough history yet — log a few stages to see where applications go." Otherwise `<ResponsiveContainer><Sankey data={...} /></ResponsiveContainer>` with exit branches (`rejected` / `no_response` / `withdrawn`) coloured from `CHART_COLORS`' semantic entries. A caption: "Custom events are excluded."

`CycleTimeChart.tsx` — `toCycleRows(cycleTimes)` → `{ label, medianDays, sampleSize, lowConfidence: rateConfidence(sampleSize) !== "ok" }`, sorted in `FUNNEL_KINDS` order. Horizontal `BarChart`; low-confidence bars render at reduced opacity, and the tooltip carries `n=`.

`PipelineTimelineChart.tsx` — `toLanes(pipeline)` drops lanes with no dated events and sorts by earliest upcoming (falling back to latest past). Render as a CSS-grid Gantt rather than a recharts chart — recharts has no Gantt and faking one with a stacked bar is worse than laying out divs. One row per application, dots positioned by date across a shared time axis, a `today` marker line, upcoming events visually distinct from past ones.

`OfferComparisonChart.tsx` — `toOfferRows(offers)` → `{ company, base, bonus, equity, signing }` with `?? 0`. Returns `null` when empty (not an empty state — a comp chart with no offers is noise). Stacked `BarChart` with four `<Bar stackId="comp">`, currency-formatted axis.

`use-analytics.ts` — add `useTimelineAnalytics()` on key `["analytics-timeline"]`.

`AnalyticsContainer.tsx` — mount the four charts **above** the existing cohort tables, each in a `<Card>`, in the order: Stage flow, Cycle time, Active pipeline, Offer comparison.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix web run test:run -- charts`
Expected: PASS (12 tests)

- [ ] **Step 5: Lint and commit**

```bash
npm --prefix web run lint
git add web/src/features/analytics/
git commit -m "feat(web): stage flow, cycle time, pipeline timeline, and offer charts"
```

---

### Task 8: Phase 3 verification and documentation

- [ ] **Step 1: Run the full gate**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
npm --prefix web run lint
npm --prefix web run test:run
npm --prefix web run build
```

Expected: all green.

- [ ] **Step 2: Verify the charts against real data by eye**

Start the app with a workspace holding at least a few applications. Confirm:

- The Sankey shows plausible flows and its exit branches are distinguishable.
- Cycle-time bars are labelled with both stages and carry `n=`.
- Low-sample rates are greyed; anything under n=3 shows counts only.
- The offer chart is absent when there are no offers.
- The applications grid scrolls horizontally **inside its container** — the page body must not scroll sideways.
- Both CSVs open correctly in a spreadsheet, and the wide CSV includes every technical-round column even past the display cap.

This step exists because none of it is provable in jsdom: recharts measures zero there, so the unit tests deliberately cover transforms and guard rails only.

- [ ] **Step 3: Document**

Add an "Analytics over the timeline" section to `src/resume_agent/tracking/CLAUDE.md`:

- `timeline_pivot.py` is the single source for the grid, both CSVs, and the exports — presentations must never compute their own pivot.
- The technical-round cap is display-only; the wide CSV is uncapped, and truncating an export is a data-loss bug.
- Why median rather than mean for cycle times.
- The small-sample thresholds and that they live in `web/src/features/analytics/chart-theme.ts` alone.
- That `custom` events are excluded from the funnel and cycle-time charts, and why.

Add to the root `CLAUDE.md` hot-paths table:

| Path                                          | Role                                                                 |
| --------------------------------------------- | -------------------------------------------------------------------- |
| `src/resume_agent/tracking/timeline_pivot.py` | Event log → application rows; the one source for grid, CSVs, exports |
| `src/resume_agent/tracking/funnel.py`         | Sankey flow edges + median stage cycle times                         |

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/resume_agent/tracking/CLAUDE.md
git commit -m "docs: timeline analytics notes"
```

---

## Phase 3 Done When

- One pivot function backs the grid, both CSVs, and the exports; they cannot disagree.
- Technical-round columns grow to the maximum observed, capped at 6 for display, with overflow shown as `+N` and the wide CSV uncapped.
- `GET /api/analytics` is byte-for-byte unchanged; the new charts read `/api/analytics/timeline`.
- Both CSVs export correctly: wide is one row per application, long is one row per event.
- The four charts render, and the small-sample rule is enforced from one module.
- `custom` events are excluded from the funnel and cycle-time charts and the exclusion is stated in the UI.
- **The charts and both CSVs have been checked by eye against real data** — jsdom cannot prove any of it.
- Full gate green.
