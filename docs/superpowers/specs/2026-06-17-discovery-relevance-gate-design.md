# Discovery Relevance Gate — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation
**Surface:** `discovery/connectors/` (server-side query + lexical gate), `discovery/pipeline.py` (new `run_relevance` stage), `discovery/search_config.py` (new config fields)

---

## 1. Problem & Goal

The discovery funnel fetches wildly off-target jobs into the `raw` list — an AI-engineer
search returns "Class A CDL Driver" and "Creative Lead". Each junk row then costs **two
LLM calls** (`extract` + `score_fit`) before it is ranked low and ignored. That is wasted
tokens, wasted time, and a noisy shortlist.

**Root cause (confirmed in code):** the single relevance gate is `filter_by_search`
(`discovery/connectors/text.py:21`):

```python
haystack = f"{job.title or ''}\n{job.jd_text}".lower()
if any(term in haystack for term in terms):   # OR + substring, no word boundary
```

Three compounding defects, all visible in `config/search.yaml`:

1. **Substring, not word-boundary.** The keyword `rag` matches `ga**rag**e`, `sto**rag**e`,
   `ave**rag**e`, `d**rag**`. A trucking JD that mentions a garage is kept. Smoking gun.
2. **OR-any, one hit wins.** A single loose term anywhere in a long JD passes the whole job.
3. **Long phrase keywords are dead weight.** `Applied AI Engineer automotive` is matched as a
   whole substring — it never appears verbatim — so the careful phrases contribute nothing,
   while the short dangerous terms (`rag`, `python`, `automation`) do all the (bad) filtering.

Separately, the **Adzuna** connector jams all 27 titles + 14 keywords into one space-delimited
`what` blob (`discovery/connectors/adzuna.py:44`), which Adzuna treats as a loose full-text
query — so almost no narrowing happens at the source.

**Goal:** make the raw list *closely* match the target role. Two independent levers:
1. **Search first** — push a tight query to the sources that support it (Adzuna).
2. **Filter close** — replace the OR-substring gate with a precise, tiered relevance gate
   placed **before** the expensive LLM stages.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Match method | **Tiered**: a free deterministic lexical gate, then a cheap haiku LLM gate on survivors only |
| Lexical gate primitive | **Title-anchored**: title must contain ≥1 role-anchor word AND no exclude word; body is not a gate |
| Term source | **New explicit config fields** `role_anchors` + `exclude_terms` (shipped with defaults in `.example`) |
| Match scope | **Title only** for both anchors and excludes (word-boundary, case-insensitive); body never triggers reject |
| LLM gate target | **New `target_role` description field** (falls back to `titles` if unset); gate sees target + title + truncated snippet |
| Server-side search | **Targeted Adzuna query**: `what_or` of role phrases, `what_exclude`, `category`, `where`+`distance`, `salary_min`, `max_days_old`, pagination |
| Placement | Lexical gate at the **connector edge** (junk never persisted; telemetry note); haiku gate as a new **`run_relevance` pipeline stage** with DB reject reasons |
| Degradation | **Fail-open everywhere** — empty fields / no API key / LLM error ⇒ skip that gate; gates only *reject* on a confident signal; existing config + all tests keep working |
| Verification | **Golden corpus** of labeled real JD samples + a **live before/after** `pull` reporting junk-rate and LLM-calls saved |

---

## 3. Architecture

The funnel today: `connector.fetch()` → `filter_by_search()` → `ingest` (raw) → `run_extract`
→ `apply_filters` → `run_score`. The two new tiers slot in **before** the LLM stages:

```
                         ┌──────────── TIER 1 (free, deterministic) ─────────────┐
connector.fetch() ─▶ relevance_gate(title-anchored)  ─▶  ingest → DB(raw)
                         │  reject CDL/Creative/garage silently                   │
                         │  telemetry: "+12 added; filtered 30 off-target"        │
                         └────────────────────────────────────────────────────────┘
                                                   │
                         ┌──────────── TIER 2 (cheap LLM, observable) ───────────┐
DB(raw) ─▶ run_relevance(haiku)  ─▶  survivors stay `raw`                         │
                         │  off-target ─▶ status=rejected, reject_reason="off-target role"
                         └────────────────────────────────────────────────────────┘
                                                   │
DB(raw) ─▶ run_extract ─▶ apply_filters ─▶ run_score ─▶ shortlisted   (unchanged)
```

Why this split:
- The expensive resources (extract + fit) run *after* the gates, so cost is saved regardless of
  method — **order matters more than method**.
- Tier 1 is free and removes the bulk of junk; keeping it at the connector edge means junk never
  hits the DB or the dedup path.
- Tier 2 is the only place spending tokens, so it earns DB-level observability: every reject is a
  row with a `reject_reason`, and survivors flow on as `raw` with no new status to thread.

### 3.1 Tier 1 — lexical title-anchored gate

Replaces `filter_by_search`. A job is **kept** iff:
- its **title** contains **≥1** `role_anchor` as a whole token (word-boundary, case-insensitive,
  multi-word phrases allowed), **and**
- its **title** contains **no** `exclude_term` (same matching).

Body text is never a gate. If `role_anchors` is empty ⇒ the anchor requirement is skipped
(fall back to today's keyword behavior so nothing breaks). If a job has no title, the anchor
check falls back to scanning the whole document so a data hiccup doesn't drop a real job; excludes
(title-only) simply don't fire.

```
title='Class A CDL Driver'   anchors? none          → REJECT
title='Creative Lead'        excl 'creative'        → REJECT
title='AI Applications Eng.'  anchors? 'engineer','ai'; excl none → KEEP
title='AI Engineer'  body '...creative problem solving...'  → KEEP (body ignored)
```

### 3.2 Tier 2 — haiku relevance stage (`run_relevance`)

A new pipeline stage between ingest and `run_extract`. For each `raw` job it asks a cheap model:

```
Target role: <target_role or titles[] fallback>
Title: <job.title>
Snippet: <first ~500 chars of jd_text>
→ Is this job a plausible match for the target role? keep | reject (+ one-line reason)
```

- **Keep** ⇒ job stays `raw` (picked up by `run_extract`).
- **Reject** ⇒ `status=rejected`, `reject_reason="off-target role: <reason>"`.
- **Fail-open:** no `target_role` *and* no `titles`, or no `anthropic_api_key`, or any agent
  error ⇒ the stage is a no-op and the job passes through. The gate only ever rejects on a
  confident model "no".

Token budget: title + truncated snippet only (never the full JD), cheap model (`settings.cheap_model`).

### 3.3 Server-side Adzuna query

`adzuna.py:_get_results` is rebuilt to push a tight query instead of a blob:

| Param | Source | Purpose |
|---|---|---|
| `what_or` | strongest role phrases (anchors + a curated subset of keywords) | match any core role term |
| `what_exclude` | `exclude_terms` joined | drop junk at the source |
| `category` | `"it-jobs"` (constant) | restrict to the tech taxonomy |
| `where` + `distance` | `locations[0]` + a configurable radius | geo-narrow |
| `salary_min` | `min_salary` | server-side floor |
| `max_days_old` | a configurable freshness window | recency |
| `results_per_page` + pagination | — | fetch enough, deterministically |

Deliberately **not** used: `title_only` and `what_and` (both over-filter and silently drop real
roles). The local Tier-1 gate still runs on Adzuna results as a backstop.

Greenhouse / Lever are company ATS boards with **no full-text search** — fetch-all-then-gate is the
only option; Tier 1 handles them. RemoteOK / LinkedIn are disabled today and unchanged.

---

## 4. Config changes (`SearchConfig` / `search.yaml`)

New fields, all optional (fail-open):

```yaml
role_anchors:          # Tier-1: title must contain one of these (whole word)
  - engineer
  - ai
  - machine learning
  - applied scientist
  - ml
  - llm
exclude_terms:         # Tier-1 + Adzuna what_exclude: title must contain none of these
  - driver
  - cdl
  - nurse
  - sales
  - recruiter
  - creative
target_role: >         # Tier-2: one-line description for the haiku gate
  Applied AI / LLM engineering roles, including forward-deployed,
  autonomy solutions, and ML platform engineering.
adzuna_distance: 40        # optional; miles radius for `where`
adzuna_max_days_old: 30    # optional; freshness window
```

Existing `keywords` / `titles` keep their roles: `keywords` feed the Adzuna `what_or`; `titles`
are the `target_role` fallback. No migration — these are config-only additions.

---

## 5. Out of scope

- Semantic embeddings (deferred; revisit only if lexical + haiku prove insufficient).
- RemoteOK tag-endpoint search and LinkedIn keyword tuning (those connectors are disabled).
- Any change to extract / `apply_filters` / fit scoring — the gates sit entirely upstream.

---

## 6. Acceptance criteria

1. With the shipped default `role_anchors`/`exclude_terms`, a fixture "Class A CDL Driver" and
   "Creative Lead" JD are **rejected at Tier 1**; genuine AI/LLM/autonomy roles are **kept**.
2. The `rag`→`garage` substring class of false-positive cannot recur (word-boundary regression test).
3. `run_relevance` rejects a clearly off-target survivor (mocked agent) with a `reject_reason`, and
   is a **no-op** when under-configured or the agent errors (fail-open tests).
4. Adzuna issues a single narrowed request (asserted params) instead of the blob.
5. A live `pull` on the real config shows a materially lower junk-rate and fewer downstream
   `extract` calls than `main`.
6. Full suite stays green; no existing config or test requires changes.
