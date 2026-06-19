# Source-Priority Upgrade-Merge — Design (Spec B)

**Date:** 2026-06-19
**Status:** Draft (design); pending user review
**Branch:** `feat/discovery-structured-backends-and-priority`
**Surface:** `discovery/ingest.py` (`add_job`), `tracking/repository.py` (`find_existing` / a new
upgrade path), a small `source tier` map. **No config, no schema change.**

> This is **Spec B** of the 2026-06-19 two-part upgrade. It is a **downstream** dedup-policy change,
> independent of **Spec A** (the structured-backend family) but made **urgent** by it: Workday is the
> high-overlap source that always arrives *after* aggregators have already claimed the job.

---

## 1. Problem & Goal

Today's dedup, top to bottom:

- `ingest_jobs` → `add_job` → `find_existing(session, url, jd_text, dedup_key)` queries the **DB**
  (by `url`, else exact `jd_text`, else `dedup_key`) and returns the **first** match.
- If a match exists, `add_job` returns **`None`** — the incoming job is **dropped entirely**. No
  merge, no field upgrade.

Because the lookup hits the DB, this is **across runs**, so:

> **The first source that *ever* ingests a `(company, title)` owns it permanently.**

Registry order ("priority") only breaks ties for the *same brand-new* job seen by two connectors *in
the same run* — a razor-thin case. In steady state it is **first-seen-wins**, which correlates with
**nothing** about source quality.

### The concrete failure (and why Spec A makes it daily)

A GM req shows up in **Adzuna, LinkedIn, and GM's Workday board**. If Adzuna scrapes it Monday, then
the new Workday backend pulls the same req Tuesday with the **canonical apply URL and full JD** —
`find_existing` matches the Adzuna copy and **throws the Workday copy away**. You are permanently
stuck with an aggregator redirect when you had the direct link. Spec A's Workday backend is precisely
the *high-value, second-arriving* source, so adding it turns this latent bug into an everyday one.

**Goal:** make source priority *real* — when a **higher-tier** source re-sees an existing job,
**upgrade** the stored posting fields instead of dropping the new copy, **without** disturbing the
user's progress on that job.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Priority model | **(X) Upgrade-on-better-source.** Higher-tier re-see overwrites posting fields; it does not drop. |
| Calibration | **Fixed 2-tier**, not per-source numeric knobs. **Tier 1 (canonical):** direct/ATS sources. **Tier 2 (fallback):** aggregators. |
| State safety | **Preserve user progress.** Never reset `status`, and never touch related rows (`Application`, `ResumeVersion`, `CoverLetter`, notes). |
| Post-application caution | If the job's `status` has **advanced past `raw`**, upgrade **only `url` + `source`** (gain the canonical apply link) and **freeze** `jd_text`/`title`/etc. so a resume already tailored to the old text isn't silently re-based. While `status == raw`, upgrade **all** posting fields. |
| Equal / lower tier | **No-op** (return `None`, current behavior) — no churn from same-tier re-pulls. |

### Tier assignment

```python
TIER_CANONICAL = {"greenhouse", "lever", "ashby", "workday", "tesla", "google", "companies", "url"}
TIER_FALLBACK  = {"adzuna", "remoteok", "linkedin"}
# rank: canonical = 0 (higher priority), fallback = 1, unknown defaults to fallback
```

A direct ATS / company / pasted-URL posting always wins over an aggregator copy. Among canonical
sources (or among fallbacks) the tier is equal → first-seen stays.

---

## 3. Architecture

`add_job` changes from "drop on duplicate" to "upgrade-or-skip on duplicate":

```python
def add_job(session, *, source, jd_text, url, company, title, location, posted_at):
    ...
    existing = find_existing(session, url, jd_text, dedup_key)
    if existing is not None:
        return maybe_upgrade(session, existing, incoming_fields, source)   # Job | None
    # ... unchanged insert path ...
```

`maybe_upgrade(session, existing, fields, new_source)`:

1. `if rank(new_source) >= rank(existing.source): return None` — equal/lower tier, keep existing.
2. Higher tier → upgrade in place (same `Job.id`, related rows untouched):
   - **`status == raw`** → overwrite `url, jd_text, company, title, location, posted_at, source`;
     recompute `dedup_key`.
   - **`status` advanced** → overwrite **only `url, source`**; leave the rest frozen.
3. `save_job(session, existing)` (the existing `add`/`commit`/`refresh` path) and return it.

Because `Application` / `ResumeVersion` / `CoverLetter` are separate tables keyed by `job_id`,
mutating the `Job` row's posting columns **does not cascade** to them — status and progress are
inherently preserved. The post-application rule above is the extra guard against silently re-basing a
tailored resume's source text.

### Telemetry (optional, low-cost)

`ingest_jobs` can distinguish *added* vs *upgraded* so `run_pull`'s note can read e.g.
`+3 added, 2 upgraded` instead of hiding upgrades. Nice-to-have, not required for correctness.

---

## 4. Out of scope

- **Connector execution order / shared `limit` budgeting.** Tier governs *who wins a duplicate*, not
  *who runs first*. Registry order is unchanged.
- **Per-source numeric priority config.** Explicitly rejected (YAGNI; nobody tunes it correctly).
- **Dashboard ranking.** Display order is a separate concern.

---

## 5. Noted risk (flagged, not fixed here)

`compute_dedup_key` is `normalize(company)|normalize(title)` with **location dropped**. So GM
"Software Engineer" in Austin and Detroit collapse to **one** job. Spec A's Workday backend, which
pulls many same-title reqs across locations, makes this real data loss. It is **orthogonal** to
priority (it's about dedup *granularity*, not dedup *winner*), so it is **not** bundled here —
recommended as a small follow-up micro-spec (add location to the key, or a location-aware secondary
check). Calling it out so it is not silently inherited.

---

## 6. Acceptance criteria

1. A **canonical** source (e.g. `workday`) re-seeing a job first ingested by a **fallback** source
   (e.g. `adzuna`) **upgrades** the stored `url`/`jd_text`/`source` in place (same `Job.id`).
2. A **fallback** source re-seeing a **canonical** job is a **no-op** (returns `None`; nothing
   overwritten).
3. **Equal-tier** re-see (e.g. `adzuna` then `remoteok`, or `greenhouse` then `workday`) is a
   **no-op** — first-seen stays.
4. Upgrade **preserves** `status`, `Application`, `ResumeVersion`, `CoverLetter`, and notes for that
   job (asserted via related-row queries before/after).
5. When `status` has **advanced past `raw`**, a higher-tier re-see upgrades **only `url` + `source`**
   and leaves `jd_text`/`title`/`location` unchanged.
6. `ingest_jobs` return value / telemetry reflects upgrades without double-counting them as new adds.
7. Full suite green; **no config or schema change**; existing dedup tests updated only where the
   drop→upgrade behavior intentionally changed.
