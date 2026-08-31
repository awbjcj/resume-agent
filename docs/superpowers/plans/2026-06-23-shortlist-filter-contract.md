# Shortlist Filter Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the shortlist filter-and-rank predicate — which genuinely runs in two runtimes — behind one cross-language behavioral contract, so the Python (Streamlit) and TypeScript (React) copies can no longer drift.

**Architecture:** The filter/sort/rank predicate exists twice on purpose: `src/resume_tailor_harness/dashboard/filtering.py` filters in-process for Streamlit, `web/src/lib/filters/*` filters in-browser for instant React response. Neither can be deleted. We make the _behavior_ the interface: a checked-in fixture of `(rows, filterState) → ordered [jobId]` cases in `contracts/`, plus two thin conformance harnesses (pytest + vitest) that prove each implementation satisfies it. We also remove the one known divergence — composite rank rounds banker's-style in Python and half-up in JS — by sorting on the unrounded composite (rounding becomes display-only).

**Tech Stack:** Python 3 / pytest / dataclasses; TypeScript / vitest / Vite. Shared artifact is a JSON contract file in the camelCase `ShortlistItem` wire shape (the same shape `contracts/openapi.json` already defines).

**Domain terms (CONTEXT.md):** _Filter contract_, _Conformance harness_, _Composite rank_.

---

## File Structure

| File                                       | Responsibility                                                                     | Action                       |
| ------------------------------------------ | ---------------------------------------------------------------------------------- | ---------------------------- |
| `contracts/shortlist_filter.contract.json` | The Filter contract: seed cases `(now, rows, filterState) → expected ordered ids`  | Create                       |
| `contracts/README.md`                      | Document the contract + the rule "filter-behavior changes require a contract case" | Modify                       |
| `tests/test_shortlist_filter_contract.py`  | Python conformance harness; `row_from_wire` / `filter_state_from_wire` builders    | Create                       |
| `web/src/lib/filters/contract.test.ts`     | TS conformance harness; `rowFromWire` / `filterStateFromWire` builders             | Create                       |
| `src/resume_tailor_harness/dashboard/filtering.py`  | Sort composite on unrounded value; keep rounded `composite_score` for display      | Modify (`88-109`, `134-135`) |
| `web/src/lib/filters/sort.ts`              | Same reconciliation in TS                                                          | Modify (`25-40`, `69-73`)    |

Builders live inside their harness files — only one harness consumes each, so keep them local (DRY does not mean premature sharing across the language boundary).

---

### Task 1: Create the Filter contract file

**Files:**

- Create: `contracts/shortlist_filter.contract.json`

The contract rows use the camelCase `ShortlistItem` wire shape; `filterState` uses the camelCase `FilterState` keys with sets expressed as arrays. Missing row/state keys default (null / empty set) in the harness builders, so each case lists only the fields it exercises. `expected` is the ordered list of `jobId` after `applyFilters → sortRows`.

- [ ] **Step 1: Write the contract file**

```json
{
  "version": 1,
  "now": "2026-06-16T00:00:00Z",
  "cases": [
    {
      "name": "fit sort, nulls last, fitMin drops low scores (null fit is neutral)",
      "filterState": { "sort": "fit", "fitMin": 50 },
      "rows": [
        { "jobId": 1, "fitScore": 40 },
        { "jobId": 2, "fitScore": null },
        { "jobId": 3, "fitScore": 90 },
        { "jobId": 4, "fitScore": 55 }
      ],
      "expected": [3, 4, 2]
    },
    {
      "name": "salary sort desc, salaryMax then salaryMin, nulls last",
      "filterState": { "sort": "salary" },
      "rows": [
        { "jobId": 1, "salaryMax": 100 },
        { "jobId": 2, "salaryMin": 200 },
        { "jobId": 3 }
      ],
      "expected": [2, 1, 3]
    },
    {
      "name": "skills overlap matches after normalization (case + trim)",
      "filterState": { "sort": "fit", "skills": ["python"] },
      "rows": [
        {
          "jobId": 1,
          "skills": [{ "name": "PyThon ", "covered": true, "required": true }]
        },
        {
          "jobId": 2,
          "skills": [{ "name": "Golang", "covered": false, "required": true }]
        }
      ],
      "expected": [1]
    },
    {
      "name": "composite sort, balanced preset, neutral salary/recency",
      "filterState": { "sort": "composite", "preset": "balanced" },
      "rows": [
        { "jobId": 1, "fitScore": 90 },
        { "jobId": 2, "fitScore": 50 },
        { "jobId": 3, "fitScore": 70 }
      ],
      "expected": [1, 3, 2]
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add contracts/shortlist_filter.contract.json
git commit -m "feat(contracts): add shortlist filter behavioral contract"
```

---

### Task 2: Python conformance harness

**Files:**

- Create: `tests/test_shortlist_filter_contract.py`

The harness loads the contract, builds a `ShortlistRow` and `FilterState` from each camelCase case (mapping camel→snake — this also guards the field mapping), runs `apply_filters → sort_rows`, and asserts the ordered ids.

- [ ] **Step 1: Write the failing harness**

```python
import json
from datetime import datetime
from pathlib import Path

import pytest

from resume_tailor_harness.dashboard.filtering import FilterState, apply_filters, sort_rows
from resume_tailor_harness.tracking.queries import ShortlistRow, SkillTag

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "shortlist_filter.contract.json"

_SET_KEYS = {
    "remote", "sponsorship", "seniority", "employmentType", "industry",
    "country", "region", "city", "companySize", "skills",
}
_CAMEL_TO_SNAKE = {
    "jobId": "job_id", "fitScore": "fit_score", "fitRationale": "fit_rationale",
    "sponsorshipSignal": "sponsorship_signal", "salaryMin": "salary_min",
    "salaryMax": "salary_max", "salaryCurrency": "salary_currency",
    "remotePolicy": "remote_policy", "employmentType": "employment_type",
    "companySize": "company_size", "postedAt": "posted_at", "sicMajor": "sic_major",
    "sicLabel": "sic_label", "sicDivision": "sic_division",
    "locationCountry": "location_country", "locationRegion": "location_region",
    "locationCity": "location_city",
}
_STATE_CAMEL_TO_SNAKE = {
    "salaryMin": "salary_min", "fitMin": "fit_min", "employmentType": "employment_type",
    "companySize": "company_size",
}


def _parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def row_from_wire(d: dict) -> ShortlistRow:
    fields = {_CAMEL_TO_SNAKE.get(k, k): v for k, v in d.items() if k != "skills"}
    fields["posted_at"] = _parse_dt(fields.get("posted_at"))
    skills = [SkillTag(name=s["name"], covered=s.get("covered", False), required=s.get("required", False))
              for s in d.get("skills", [])]
    return ShortlistRow(
        job_id=fields["job_id"],
        company=fields.get("company"), title=fields.get("title"), location=fields.get("location"),
        fit_score=fields.get("fit_score"), fit_rationale=fields.get("fit_rationale"),
        sponsorship_signal=fields.get("sponsorship_signal"),
        salary_min=fields.get("salary_min"), salary_max=fields.get("salary_max"),
        salary_currency=fields.get("salary_currency"), remote_policy=fields.get("remote_policy"),
        seniority=fields.get("seniority"), employment_type=fields.get("employment_type"),
        industry=fields.get("industry"), company_size=fields.get("company_size"),
        posted_at=fields.get("posted_at"), skills=skills,
        sic_major=fields.get("sic_major"), sic_label=fields.get("sic_label"),
        sic_division=fields.get("sic_division"), location_country=fields.get("location_country"),
        location_region=fields.get("location_region"), location_city=fields.get("location_city"),
    )


def filter_state_from_wire(d: dict) -> FilterState:
    state = FilterState()
    for k, v in d.items():
        if k in _SET_KEYS:
            setattr(state, _STATE_CAMEL_TO_SNAKE.get(k, k), set(v))
        else:
            setattr(state, _STATE_CAMEL_TO_SNAKE.get(k, k), v)
    return state


def _load_cases():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return data["now"], data["cases"]


_NOW, _CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_python_satisfies_filter_contract(case):
    now = _parse_dt(_NOW)
    rows = [row_from_wire(r) for r in case["rows"]]
    state = filter_state_from_wire(case["filterState"])
    out = sort_rows(apply_filters(rows, state), state, now=now)
    assert [r.job_id for r in out] == case["expected"]
```

- [ ] **Step 2: Run the harness to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_shortlist_filter_contract.py -v`
Expected: 4 cases PASS. (If `composite` case fails, that is a real defect surfaced by the contract — Task 4 reconciles it; for the seed data above it should pass.)

- [ ] **Step 3: Lint**

Run: `ruff check tests/test_shortlist_filter_contract.py`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_shortlist_filter_contract.py
git commit -m "test(contracts): python conformance harness for filter contract"
```

---

### Task 3: TypeScript conformance harness

**Files:**

- Create: `web/src/lib/filters/contract.test.ts`

The harness reads the same contract file (resolved relative to this file via `import.meta.url`, so it works regardless of vitest's cwd), hydrates each case into `ShortlistItem` + `FilterState` (arrays → `Set`), runs `applyFilters → sortRows`, and asserts the ordered ids.

- [ ] **Step 1: Write the failing harness**

```ts
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { applyFilters } from "./apply";
import { sortRows } from "./sort";
import {
  emptyFilterState,
  type FilterState,
  type ShortlistItem,
} from "./types";

const here = dirname(fileURLToPath(import.meta.url));
const contractPath = resolve(
  here,
  "../../../../contracts/shortlist_filter.contract.json",
);
const contract = JSON.parse(readFileSync(contractPath, "utf-8")) as {
  now: string;
  cases: {
    name: string;
    filterState: Record<string, unknown>;
    rows: Partial<ShortlistItem>[];
    expected: number[];
  }[];
};

const SET_KEYS = new Set([
  "remote",
  "sponsorship",
  "seniority",
  "employmentType",
  "industry",
  "country",
  "region",
  "city",
  "companySize",
  "skills",
]);

function rowFromWire(d: Partial<ShortlistItem>): ShortlistItem {
  return {
    jobId: 0,
    company: null,
    title: null,
    location: null,
    fitScore: null,
    fitRationale: null,
    sponsorshipSignal: null,
    salaryMin: null,
    salaryMax: null,
    salaryCurrency: null,
    remotePolicy: null,
    seniority: null,
    employmentType: null,
    industry: null,
    companySize: null,
    postedAt: null,
    skills: [],
    sicMajor: null,
    sicLabel: null,
    sicDivision: null,
    locationCountry: null,
    locationRegion: null,
    locationCity: null,
    ...d,
  } as ShortlistItem;
}

function filterStateFromWire(d: Record<string, unknown>): FilterState {
  const state = emptyFilterState();
  for (const [k, v] of Object.entries(d)) {
    if (SET_KEYS.has(k)) {
      (state as unknown as Record<string, unknown>)[k] = new Set(v as string[]);
    } else {
      (state as unknown as Record<string, unknown>)[k] = v;
    }
  }
  return state;
}

describe("TS satisfies the shortlist filter contract", () => {
  const now = new Date(contract.now);
  for (const c of contract.cases) {
    it(c.name, () => {
      const rows = c.rows.map(rowFromWire);
      const state = filterStateFromWire(c.filterState);
      const out = sortRows(applyFilters(rows, state), state, now);
      expect(out.map((r) => r.jobId)).toEqual(c.expected);
    });
  }
});
```

- [ ] **Step 2: Run the harness to verify it passes**

Run (from `web/`): `npm run test -- src/lib/filters/contract.test.ts`
Expected: 4 cases PASS.

- [ ] **Step 3: Type-check**

Run (from `web/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/filters/contract.test.ts
git commit -m "test(contracts): typescript conformance harness for filter contract"
```

---

### Task 4: Reconcile composite rounding — sort on the unrounded value

**Files:**

- Modify: `src/resume_tailor_harness/dashboard/filtering.py:88-109,134-135`
- Modify: `web/src/lib/filters/sort.ts:25-40,69-73`

**Why (no behavior change for current data):** `composite_score` rounds with Python banker's rounding; `compositeScore` rounds half-up in JS. At an exact 4th-decimal tie they disagree, which can flip two jobs' order between the two boards. The rounded value is presentation only — sorting must read the raw weighted sum (bit-identical across both IEEE-754 runtimes). This is a deepening of the _Composite rank_ term: ordering is defined on the raw score; rounding never enters it.

- [ ] **Step 1: Python — split raw from rounded, sort on raw**

In `src/resume_tailor_harness/dashboard/filtering.py`, replace the body of `composite_score` (lines `88-109`) with a raw helper + a rounding wrapper:

```python
def _composite_raw(row: ShortlistRow, preset: str, now: datetime) -> float:
    w_fit, w_salary, w_recency = PRESETS.get(preset, PRESETS["balanced"])

    fit_n = float(row.fit_score) if row.fit_score is not None else NEUTRAL

    salary = _salary_value(row)
    salary_n = (
        min(salary, SALARY_CEILING) / SALARY_CEILING * 100
        if salary is not None
        else NEUTRAL
    )

    age = _age_days(row, now)
    # Clamp both ends: a future-dated/clock-skewed posting has negative age and
    # would otherwise score >100, over-ranking it above genuinely fresh jobs.
    recency_n = (
        min(100.0, max(0.0, 100.0 - (age / RECENCY_WINDOW_DAYS * 100.0)))
        if age is not None
        else NEUTRAL
    )

    return w_fit * fit_n + w_salary * salary_n + w_recency * recency_n


def composite_score(row: ShortlistRow, preset: str, now: datetime) -> float:
    """Display value. Ordering uses the raw score (see _composite_raw)."""
    return round(_composite_raw(row, preset, now), 4)
```

Then in `sort_rows`, change the composite branch (line `134-135`) to sort on the raw value:

```python
    if state.sort == "composite":
        return sorted(rows, key=lambda row: _composite_raw(row, state.preset, now), reverse=True)
```

- [ ] **Step 2: TypeScript — same split**

In `web/src/lib/filters/sort.ts`, replace `compositeScore` (lines `25-40`) with a raw helper + wrapper:

```ts
function compositeRaw(row: ShortlistItem, preset: Preset, now: Date): number {
  const [wFit, wSalary, wRecency] = PRESETS[preset] ?? PRESETS.balanced;
  const fitN = row.fitScore ?? NEUTRAL;

  const salary = salaryValue(row);
  const salaryN =
    salary !== null
      ? (Math.min(salary, SALARY_CEILING) / SALARY_CEILING) * 100
      : NEUTRAL;

  const age = ageDays(row, now);
  const recencyN =
    age !== null
      ? Math.min(100, Math.max(0, 100 - (age / RECENCY_WINDOW_DAYS) * 100))
      : NEUTRAL;

  return wFit * fitN + wSalary * salaryN + wRecency * recencyN;
}

export function compositeScore(
  row: ShortlistItem,
  preset: Preset,
  now: Date,
): number {
  // Display value. Ordering uses the raw score (see compositeRaw).
  return Math.round(compositeRaw(row, preset, now) * 10000) / 10000;
}
```

Then change the composite branch in `sortRows` (lines `69-73`) to sort on the raw value:

```ts
if (state.sort === "composite") {
  return arr.sort(
    (a, b) =>
      compositeRaw(b, state.preset, now) - compositeRaw(a, state.preset, now),
  );
}
```

- [ ] **Step 3: Add a contract case that pins composite ordering at a rounding boundary**

Append to `contracts/shortlist_filter.contract.json` `cases` array (before the closing `]`):

```json
    ,{
      "name": "composite sort, freshest preset, raw score breaks rounded display tie",
      "filterState": { "sort": "composite", "preset": "freshest" },
      "rows": [
        { "jobId": 1, "fitScore": 60, "postedAt": "2026-06-15T23:59:58Z" },
        { "jobId": 2, "fitScore": 60, "postedAt": "2026-06-16T00:00:00Z" },
        { "jobId": 3, "fitScore": 59, "postedAt": "2026-06-16T00:00:00Z" }
      ],
      "expected": [2, 1, 3]
    }
```

- [ ] **Step 4: Run both harnesses + full suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_shortlist_filter_contract.py tests/test_dashboard_filtering.py -v`
Expected: all PASS (existing `composite_score` unit tests still pass — the public rounded value is unchanged).

Run (from `web/`): `npm run test -- src/lib/filters && npx tsc --noEmit`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/dashboard/filtering.py web/src/lib/filters/sort.ts contracts/shortlist_filter.contract.json
git commit -m "fix(filters): order composite rank on unrounded score in both runtimes"
```

---

### Task 5: Migrate shared cases into the contract; document the rule

**Files:**

- Modify: `contracts/README.md`
- Modify: `tests/test_dashboard_filtering.py` (move cross-language cases into the contract; keep language-local edges)
- Modify: `web/src/lib/filters/apply.test.ts`, `web/src/lib/filters/sort.test.ts` (same)

**Principle:** Any case that asserts behavior _both_ runtimes must share belongs in the contract (asserted in both). Language-local concerns — `None` vs `undefined`, tz-naive datetimes, empty-set short-circuits — stay in the per-language unit tests.

- [ ] **Step 1: Add filter-membership + sponsorship/remote facet cases to the contract**

Add cases to `contracts/shortlist_filter.contract.json` covering: salaryMin gates USD only (non-USD passes through), each facet set (remote/sponsorship/seniority/employmentType/industry/companySize/country/region/city) gating membership, null/unknown facet values passing selected filters as neutral, and a multi-facet AND case. Use the same shape as Task 1. Pick expected ids by hand from the predicate. Include the null-neutral case before thinning the existing per-language tests that currently pin it.

- [ ] **Step 2: Run both harnesses**

Run: `.venv/Scripts/python.exe -m pytest tests/test_shortlist_filter_contract.py -q`
Run (from `web/`): `npm run test -- src/lib/filters/contract.test.ts`
Expected: all new cases PASS in both. Any failure is a genuine cross-runtime drift — fix the lagging implementation, not the contract.

- [ ] **Step 3: Thin the per-language tests**

In `tests/test_dashboard_filtering.py` and the `web/src/lib/filters/*.test.ts` files, delete only the membership/sort assertions now covered by the contract, including the null-neutral facet behavior once the contract case exists. Keep language-local edge cases. Run each suite to confirm still green.

Run: `.venv/Scripts/python.exe -m pytest tests/test_dashboard_filtering.py -q`
Run (from `web/`): `npm run test -- src/lib/filters`
Expected: PASS.

- [ ] **Step 4: Document the contract in `contracts/README.md`**

Add a section:

```markdown
## shortlist_filter.contract.json

The cross-language behavioral contract for shortlist filter-and-rank. Rows use the
camelCase `ShortlistItem` wire shape; `filterState` uses camelCase `FilterState`
keys (sets as arrays); `expected` is the ordered `jobId` list after
`applyFilters → sortRows`.

Two conformance harnesses assert it:

- `tests/test_shortlist_filter_contract.py` (Python — `dashboard/filtering.py`)
- `web/src/lib/filters/contract.test.ts` (TypeScript — `lib/filters/*`)

**Rule:** any change to filter, sort, or composite-rank behavior MUST add or update a
case here. A case that only one runtime needs does not belong in the contract.
```

- [ ] **Step 5: Commit**

```bash
git add contracts/ tests/test_dashboard_filtering.py web/src/lib/filters/
git commit -m "test(contracts): migrate shared filter cases into the contract; thin per-language tests"
```

---

## Self-Review

- **Spec coverage:** Filter contract (Task 1) ✓; both conformance harnesses (Tasks 2–3) ✓; rounding reconciliation via unrounded ordering (Task 4) ✓; camelCase wire shape + field-mapping guard (Tasks 2–3 builders) ✓; scope = applyFilters + sortRows + compositeScore + normalizeSkill (Task 1 skills case exercises normalize; Tasks 1/5 cover apply+sort+composite) ✓; facets deferred (noted, not implemented) ✓.
- **Placeholder scan:** Task 5 Steps 1/3 describe adding/removing cases without enumerating every one — acceptable because the predicate and expected-id derivation are fully specified by the existing `_passes`/`passes` code and the worked seed cases; the engineer derives expected ids mechanically. All code steps show complete code.
- **Type consistency:** `row_from_wire`/`filter_state_from_wire` (Python) and `rowFromWire`/`filterStateFromWire` (TS) match the contract keys; `_composite_raw`/`compositeRaw` referenced consistently in Task 4; `ShortlistRow`/`ShortlistItem`/`FilterState`/`SkillTag` match their definitions.

---

## Open follow-ups (not in scope)

- Facet builders (`available_countries/states/cities/industries/skill_cloud` ↔ `facets.ts`) are duplicated too but derivational and lower-stakes — give them their own contract later if drift appears.
- The coarse server-side filters in `services/board.py:list_shortlist` (min_fit, sort) overlap this predicate but are unused by the React path (it pulls all pages and filters client-side). Decide separately whether to keep them.
