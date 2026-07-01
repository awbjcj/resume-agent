# Agent Quality & Workflow — Phase 3: Cost / Latency (design)

**Status:** approved for implementation by explicit user request; risky levers remain default-off and eval-gated
**Date:** 2026-06-30
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 3 of the four-phase effort — **last**, so we don't optimize a moving target.
Cuts cost/latency per tailored resume *only after* quality is stable (Phases 1–2) and
**measurable** (Phase 0). Default-off levers are authorized; §6 governs adoption.

---

## 1. Background

- **Prompt caching now exists (system prompt only).** `build_model` forwards a
  `cache_system_prompt` flag, gated by `Settings.prompt_cache_enabled`, into the Anthropic model
  constructor. JD/profile *user* content is still sent uncached on every call — only the stable
  system-prompt prefix is cached.
- **Cost/usage capture now exists in the eval harness.** `evals/usage.py`'s `UsageCollector` /
  `MeteredRunner` wrap eval agent calls and read token usage + cost off the agent result;
  `evals/report.py` surfaces it per case and in aggregate. Provider cost can still come back
  `None` (reported as unknown) when a call's result lacks usage metrics.
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
- **Per-agent system-prompt caching.** Agno 2.6.12 exposes
  `Claude(cache_system_prompt=True)`, which caches the static system prompt only. It does not
  cache the dynamic JD/profile/evidence user message and cannot share one cache entry across
  reviewers whose role instructions differ. This is transparent and can still hit across rounds
  and cases for each agent. A larger shared user-prefix cache would require a different message
  construction API and is explicitly deferred rather than being falsely claimed here.

**Eval-gated** — each ships **only if** the harness shows quality held within the tolerance band
**and** cost drops. The harness ranks them; adopt greedily while quality holds:

```
tolerance band: mean(candidate - baseline output_quality) >= -2  AND  trap_recall unchanged
```

- **Tier escalation** — run a cheaper tier first, escalate to premium only when contested
  (e.g. score near the threshold, or a gate boundary). Quality risk: the cheap tier may misjudge.
- **Skip-passed reviewers** — skip re-running non-gate reviewers that passed last round
  (the deferred Phase 1 §3.3 item). Quality risk: stale carried-forward scores after a
  whole-resume revise; the fact-check gate must still always re-run.
- **Regression early-stop** — after at least one clean round exists, stop when a later round
  breaks the gate or scores below the best prior clean round. Do not stop while every round is
  still gate-failing; those rounds need an opportunity to repair the fact lock.

## 4. Which eval metric proves it

The new **cost number** (down) plus `output_quality` / `trap_recall` (held within band). The
report shows cost **before/after per lever**, so each risky lever earns its place or is dropped.

## 5. Risk

Medium. Cache-ordering is risk-free; the three gated levers each trade some quality for cost and
are only adopted if the band holds, so the downside is bounded by the band definition. The
project's fact-lock invariant constrains skip-passed (gate always re-runs).

## 6. Evidence and adoption gate

Production adoption claims remain deferred until:
1. The Phase 0 eval harness is green **and** a baseline eval run is recorded, and
2. **Phases 1 and 2 are merged** — quality work must settle before optimizing it, or we
   optimize a moving target, and
3. (system-prompt caching only) agno's Anthropic `cache_system_prompt` surface is confirmed.

The user explicitly authorized implementation before a paid live baseline exists. Offline tests
may prove contracts and default-off behavior, but they do not prove a cost win or justify enabling
an eval-gated lever.

## 7. Open items for the implementation plan

- Confirm `RunOutput` usage shape (this is Phase 0 open item 4.8.2, now owned by Phase 3 task 0).
- Confirm agno exposes Anthropic `cache_control` and where it attaches (system vs message).
- Pin the tolerance band precisely (the §3.2 values are the starting proposal).
- Decide the tier-escalation **trigger** (score proximity to threshold? contested gate?
  per-reviewer vs whole-panel?).
