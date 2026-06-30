# Agent Quality & Workflow — Phase 3: Cost / Latency (design)

**Status:** approved (design); **implementation plan deliberately deferred** (see §6)
**Date:** 2026-06-30
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 3 of the four-phase effort — **last**, so we don't optimize a moving target.
Cuts cost/latency per tailored resume *only after* quality is stable (Phases 1–2) and
**measurable** (Phase 0). Design-only; TDD plan deferred until §6.

---

## 1. Background

- **No prompt caching exists.** Agents are built as `Claude(id=, api_key=)` with no
  `cache_control` (`llm_runner.py:194`). "Cache-aware prompt ordering" is therefore not
  *re-ordering* an existing cache — it requires **enabling** Anthropic prompt caching first,
  which depends on what agno 2.6.x exposes for cache markers.
- **No cost/usage capture exists.** `acall` returns the agent result; nobody reads token usage
  (`llm_runner.py:251`). Phase 0 explicitly **deferred** this (RunOutput metrics shape
  unconfirmed). So Phase 3's evaluation basis — "did this cut cost without hurting quality?" —
  does not exist yet.
- The panel runs **all 5 reviewers every round**; the stable prefix (instructions, JD,
  profile/evidence) is re-sent uncached on every call.

## 2. Goals / Non-goals

**Goals**
- Cut **$ and/or latency** per tailored resume with quality **held within a tolerance band**.

**Non-goals (this phase)**
- No quality regression beyond the band.
- No lever adopted without a **measured** cost win.

## 3. Design (locked)

### 3.1 Measurement first — Phase 3 is blocked on real cost capture  *(decision Q8)*

**Task 0 of Phase 3** (no lever ships before it):
- Confirm agno `RunOutput` usage/metrics fields (agno 2.6.x), or a validated proxy.
- Wire token usage into the eval report → a **baseline cost number** per case.
- Confirm agno's Anthropic `cache_control` surface (whether/where cache markers can be set).

Rationale: you cannot optimize what you cannot measure; a call-count×tier proxy is blind to
exactly the things this phase changes (cache hits, prompt-size deltas), so it would mis-rank the
levers.

### 3.2 Levers and the adoption gate  *(decision Q9)*

**Ships unconditionally** (once the caching surface is confirmed):
- **Cache-aware prompt ordering.** Transparent — output is byte-identical, only cheaper/faster.
  Structure every call so the **stable prefix** (instructions + JD + profile/evidence) is
  identical across the 5 reviewers and across rounds (maximizing prompt-cache hits), with the
  variable **resume-under-review last**. Zero quality risk → no A/B needed on quality.

**Eval-gated** — each ships **only if** the harness shows quality held within the tolerance band
**and** cost drops. The harness ranks them; adopt greedily while quality holds:

```
tolerance band: mean Δ(output_quality) <= 2  AND  trap_recall unchanged
```

- **Tier escalation** — run a cheaper tier first, escalate to premium only when contested
  (e.g. score near the threshold, or a gate boundary). Quality risk: the cheap tier may misjudge.
- **Skip-passed reviewers** — skip re-running non-gate reviewers that passed last round
  (the deferred Phase 1 §3.3 item). Quality risk: stale carried-forward scores after a
  whole-resume revise; the fact-check gate must still always re-run.
- **Regression early-stop** — stop the loop when a revision diverges (the deferred Phase 1
  §3.2 action). Marginal at `max_rounds=3`, but now measurable.

## 4. Which eval metric proves it

The new **cost number** (down) plus `output_quality` / `trap_recall` (held within band). The
report shows cost **before/after per lever**, so each risky lever earns its place or is dropped.

## 5. Risk

Medium. Cache-ordering is risk-free; the three gated levers each trade some quality for cost and
are only adopted if the band holds, so the downside is bounded by the band definition. The
project's fact-lock invariant constrains skip-passed (gate always re-runs).

## 6. Gating (when the implementation plan may be written)

Deferred until:
1. The Phase 0 eval harness is green **and** a baseline eval run is recorded, and
2. **Phases 1 and 2 are merged** — quality work must settle before optimizing it, or we
   optimize a moving target, and
3. (cache-ordering only) agno's Anthropic `cache_control` surface is confirmed.

## 7. Open items for the implementation plan

- Confirm `RunOutput` usage shape (this is Phase 0 open item 4.8.2, now owned by Phase 3 task 0).
- Confirm agno exposes Anthropic `cache_control` and where it attaches (system vs message).
- Pin the tolerance band precisely (the §3.2 values are the starting proposal).
- Decide the tier-escalation **trigger** (score proximity to threshold? contested gate?
  per-reviewer vs whole-panel?).
