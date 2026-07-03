# Phase 3 — Cost / Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut $/latency per tailored resume while quality stays within a tolerance band — starting with the one transparent win (per-agent system-prompt caching) and gating every behavior-changing lever on the eval harness.

**Architecture:** First make the cost **visible**: split and surface Anthropic cache-read/cache-write tokens in the eval report (the token-capture seam already exists from Phase 0's `UsageCollector`). Then ship the one risk-free lever — `cache_system_prompt=True` on the static-instruction tailor-family agents, wired through `build_model` behind a settings flag — and prove it with `cache_read_tokens`. Behavior-changing levers (tier-escalation, skip-passed, regression early-stop) land behind **default-off** config flags, adopted only when the harness shows quality held within the band; the lowest-risk one (regression early-stop) is implemented here, the two heavier ones are interface-locked for adoption after the baseline.

**Tech Stack:** Python 3, agno (`Claude(cache_system_prompt=...)`, `RunOutput.metrics.cache_read_tokens`/`cache_write_tokens`), Pydantic v2, pytest, `uv`.

## Global Constraints

- **Measure before optimizing.** No lever is adopted (no default flipped) without a **measured** cost win and a held quality band. The tolerance band is: `mean(candidate - baseline output_quality) >= -2 AND trap_recall unchanged`.
- **Cache surface (confirmed against agno docs):** `Claude(id=..., cache_system_prompt=True)` caches the **system prompt** (the agent `instructions`/`description`), not the user message. Metrics land on `RunOutput.metrics` as `cache_write_tokens` (first call) and `cache_read_tokens` (subsequent). Only Anthropic supports this; other providers ignore it. The cached prefix must clear Anthropic's minimum cacheable size or no cache forms (no error) — the report's `cache_read_tokens` is the proof it took effect.
- **Cache-ordering is transparent** (output byte-identical) → ships unconditionally, no quality A/B. Every other lever changes behavior → eval-gated, default-off.
- **Fact-lock is untouchable:** the provenance gate and `fact-check` reviewer **always** re-run on every written round; no cost lever may skip them.
- **agno discipline:** build agents **once**, never in a loop; keep sync (`run`) and async (`arun`) twins in lockstep.
- Tests run **offline**, agents faked, no API key/network.
- **Gating (do not start until all hold):** Phase 0 harness green + baseline `make eval` recorded, **and Phases 1 and 2 merged** (optimize quality only after it has settled). Cache-ordering additionally requires the agno cache surface confirmed — it is (above).
- Branch: `feat/agent-quality-evals`. Commit after every task.

## Review corrections applied before implementation

- Phase 0 already captures cache read/write metrics; Task 1 only adds missing report aggregates
  and preserves existing collector behavior.
- Agno 2.6.12's `cache_system_prompt` caches only each agent's static system prompt. It does not
  implement the design's originally claimed shared JD/profile user-prefix cache.
- Regression early-stop is gate-aware: it activates only after a clean round exists, then stops
  if a later round breaks the gate or scores below the best prior clean round.
- The quality tolerance uses an explicit signed delta; the prior `<= 2` wording accidentally
  accepted arbitrarily large quality losses.

---

### Task 1: Surface cache-read / cache-write tokens in the eval report

**Files:**

- Modify: `evals/usage.py` (`UsageTotals`, `UsageCollector.observe`)
- Modify: `evals/report.py` (`render_report` aggregate block)
- Test: `tests/eval/test_usage.py` (append), `tests/eval/test_report.py` (append)

**Interfaces:**

- Consumes: agno `RunOutput.metrics` fields `cache_read_tokens`, `cache_write_tokens`
- Produces: `UsageTotals` carries `cache_read_tokens: int = 0` and `cache_write_tokens: int = 0`; `render_report` prints both as run aggregates so a cache win is legible per run

> **Adapt to what Phase 0 shipped:** Phase 0 Task 5A's `UsageTotals` lists "cache tokens" generically. If it already has these two fields, this task only adds the report lines; if it has a single combined cache field, split it into read/write here (Anthropic prices cache **writes** ~1.25× and **reads** ~0.1× a normal input token, so the split is what makes a cache win visible).

- [ ] **Step 1: Write the failing test**

```python
# tests/eval/test_usage.py  (append)
from evals.usage import UsageCollector, UsageTotals


class _Metrics:
    def __init__(self, read, write):
        self.input_tokens = 100
        self.output_tokens = 50
        self.total_tokens = 150
        self.cache_read_tokens = read
        self.cache_write_tokens = write
        self.duration = 0.0
        self.cost = None


class _Result:
    def __init__(self, read, write):
        self.metrics = _Metrics(read, write)
        self.content = "x"


def test_usage_accumulates_cache_read_and_write():
    collector = UsageCollector()
    collector.observe(_Result(0, 1000))   # cache write (first call)
    collector.observe(_Result(1000, 0))   # cache read (second call)
    snap = collector.snapshot()
    assert snap.cache_write_tokens == 1000
    assert snap.cache_read_tokens == 1000


def test_usage_totals_cache_fields_default_zero():
    assert UsageTotals().cache_read_tokens == 0
    assert UsageTotals().cache_write_tokens == 0
```

```python
# tests/eval/test_report.py  (append; reuse the module's _result helper)
from evals.report import render_report
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


def test_report_shows_cache_token_aggregates():
    config = ReviewConfig(reviewers=[ReviewerSpec(name="ats-keyword", weight=1)])
    md = render_report([_result("c1", 90, 90)], config)
    assert "cache_read_tokens" in md and "cache_write_tokens" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/eval/test_usage.py tests/eval/test_report.py -v -k cache`
Expected: FAIL — Phase 0 already supplies `UsageTotals.cache_*`; the report omits the aggregate lines.

- [ ] **Step 3: Write the implementation**

In `evals/usage.py`, add the two fields to the frozen `UsageTotals` (defaulting to `0`) and accumulate them in `UsageCollector.observe`, reading defensively with `getattr` so a provider without cache metrics contributes zero:

```python
# in UsageTotals (frozen dataclass): add
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

# in UsageCollector.observe(result): when result.metrics is present, add
        self._cache_read += getattr(metrics, "cache_read_tokens", 0) or 0
        self._cache_write += getattr(metrics, "cache_write_tokens", 0) or 0

# in UsageCollector.snapshot(): include
        cache_read_tokens=self._cache_read,
        cache_write_tokens=self._cache_write,
```

(Initialize `self._cache_read = 0` and `self._cache_write = 0` in `UsageCollector.__init__` alongside the existing counters.)

In `evals/report.py`, extend the aggregate block in `render_report` (after the `Total tokens` line) with the cache aggregates:

```python
    cache_read = sum(r.usage.cache_read_tokens for r in results)
    cache_write = sum(r.usage.cache_write_tokens for r in results)
    lines += [
        f"**Cache read tokens:** {cache_read}",
        f"**Cache write tokens:** {cache_write}",
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/eval/test_usage.py tests/eval/test_report.py -v -k cache`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evals/usage.py evals/report.py tests/eval/test_usage.py tests/eval/test_report.py
git commit -m "Surfaces Anthropic cache read/write tokens in the eval report"
```

---

### Task 2: Lever A — system-prompt caching (ships unconditionally)

**Files:**

- Modify: `src/resume_agent/config.py` (`Settings`: add `prompt_cache_enabled`)
- Modify: `src/resume_agent/llm_runner.py` (`build_model`: add `cache_system_prompt` param)
- Modify: `src/resume_agent/tailor/agents.py` (tailor-family builders request caching)
- Modify: `src/resume_agent/tailor/match_plan.py`, `evals/judge.py` (same one-line change)
- Test: `tests/test_llm_runner.py` (append), `tests/test_tailor_agents.py` (append)

**Interfaces:**

- Consumes: `Settings.prompt_cache_enabled`
- Produces: `build_model(model_id, api_key=None, *, cache_system_prompt: bool = False)` — Anthropic branch passes `cache_system_prompt`; other providers ignore it. Tailor-family agents (tailor, reviser, revision, reviewers), the match-plan agent, and the judge build their model with `cache_system_prompt=Settings.prompt_cache_enabled` (default `True`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_runner.py  (append)
from resume_agent.llm_runner import build_model


def test_build_model_sets_cache_system_prompt_for_anthropic():
    model = build_model("claude-test", api_key="k", cache_system_prompt=True)
    assert getattr(model, "cache_system_prompt") is True


def test_build_model_default_no_cache():
    model = build_model("claude-test", api_key="k")
    assert getattr(model, "cache_system_prompt", False) is False


def test_build_model_other_provider_ignores_cache_flag():
    # openai branch must not raise when the cache flag is requested
    model = build_model("openai:gpt-test", api_key="k", cache_system_prompt=True)
    assert model is not None
```

```python
# tests/test_tailor_agents.py  (append)
from resume_agent.config import get_settings
from resume_agent.tailor.agents import build_tailor_agent


def test_tailor_agent_caches_system_prompt_when_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "prompt_cache_enabled", True, raising=False)
    agent = build_tailor_agent("claude-test")
    assert getattr(agent._agent.model, "cache_system_prompt") is True
```

(If `get_settings()` returns a cached singleton that `monkeypatch.setattr` can't patch per-attribute, instead set the env var the setting reads, or patch `resume_agent.tailor.agents.get_settings` to return a stub with `prompt_cache_enabled=True`. Match the pattern used elsewhere in `tests/` for overriding settings.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner.py -v -k cache`
Expected: FAIL — `build_model() got an unexpected keyword argument 'cache_system_prompt'`

- [ ] **Step 3: Write the implementation**

Add the setting to `Settings` in `src/resume_agent/config.py` (near the other LLM settings):

```python
    prompt_cache_enabled: bool = True  # cache static system prompts on Anthropic (transparent)
```

Extend `build_model` in `src/resume_agent/llm_runner.py` (lines 173–196):

```python
def build_model(
    model_id: str, api_key: str | None = None, *, cache_system_prompt: bool = False
) -> Any:
    """Construct the agno model for a (possibly provider-prefixed) ``model_id``.

    ``cache_system_prompt`` enables Anthropic prompt caching of the static system
    prompt; it is a no-op on other providers (they do not accept the kwarg).
    """
    provider, model = split_provider(model_id)
    key = api_key or resolve_api_key(model_id) or None
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model, api_key=key)
    if provider == "gemini":
        from agno.models.google import Gemini

        return Gemini(id=model, api_key=key)
    if provider == "deepseek":
        from agno.models.deepseek import DeepSeek

        return DeepSeek(id=model, api_key=key)
    from agno.models.anthropic import Claude

    return Claude(id=model, api_key=key, cache_system_prompt=cache_system_prompt)
```

In `src/resume_agent/tailor/agents.py`, add a small flag reader and pass it from every tailor-family builder:

```python
def _prompt_cache() -> bool:
    return get_settings().prompt_cache_enabled
```

Then in each of `build_tailor_agent`, `build_reviser_agent`, `build_revision_agent`, `build_reviewer_agent`, change the `build_model(...)` call to request caching, e.g. for `build_tailor_agent`:

```python
    model = build_model(model_id or model_for_tier("premium"), cache_system_prompt=_prompt_cache())
```

Apply the identical change in `src/resume_agent/tailor/match_plan.py` (`build_match_plan_agent`) and `evals/judge.py` (`build_judge_agent`):

```python
    model = build_model(model_id or model_for_tier("premium"), cache_system_prompt=get_settings().prompt_cache_enabled)
```

(`evals/judge.py` already imports nothing from `config`; add `from resume_agent.config import get_settings`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner.py tests/test_tailor_agents.py -v -k cache`
Expected: PASS

- [ ] **Step 5: Verify the win on a live run (manual, one-time)**

After the offline suite is green, run the live tier twice within the cache TTL and confirm the second run reports non-zero cache reads:

```bash
make eval
```

Inspect the report's **Cache read tokens** aggregate — it must be `> 0` once the static instructions are re-sent across rounds/cases. If it stays `0`, the cached prefix is below Anthropic's minimum cacheable size; record that in the run notes (the lever is still safe/transparent, just inert) and consider the deferred JD/profile-prefix lever below.

- [ ] **Step 6: Full offline suite + lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/config.py src/resume_agent/llm_runner.py src/resume_agent/tailor/agents.py src/resume_agent/tailor/match_plan.py evals/judge.py tests/test_llm_runner.py tests/test_tailor_agents.py
git commit -m "Enables Anthropic system-prompt caching for tailor-family agents"
```

---

### Task 3: Lever D — regression early-stop (eval-gated, default-off)

**Files:**

- Modify: `src/resume_agent/tailor/review_config.py` (`ReviewConfig`: add `early_stop_on_regression`)
- Modify: `src/resume_agent/tailor/workflow.py` (both loops)
- Test: `tests/test_tailor_workflow.py` (append)

**Interfaces:**

- Consumes: nothing new
- Produces: `ReviewConfig.early_stop_on_regression: bool = False`. Once a gate-passing round exists, the loop stops when a later round breaks the gate or scores below the best prior clean round. It does not stop while all rounds are gate-failing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_workflow.py  (append; reuse the module's fake Result/Tailor helpers)
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.workflow import run_tailor_review


class _Res:
    def __init__(self, content):
        self.content = content


class _CleanTailor:
    def run(self, prompt):
        return _Res(ResumeContent(
            contact=Contact(name="Ada"),
            experience=[TailoredExperience(company="AE", title="Eng", provenance="e1",
                        bullets=[TailoredBullet(text="Built API", provenance="e1b1")])]))
    async def arun(self, prompt):
        return self.run(prompt)


class _DescendingReviewer:
    def __init__(self):
        self.scores = [80, 70, 60]
        self.i = 0
    def run(self, prompt):
        score = self.scores[min(self.i, len(self.scores) - 1)]
        self.i += 1
        return _Res(ReviewCritique(reviewer="ats-keyword", score=score, passed=False))
    async def arun(self, prompt):
        return self.run(prompt)


def _facts():
    return ProfileFacts(contact=Contact(name="Ada"), experience=[
        Experience(id="e1", company="AE", title="Eng", bullets=[Bullet(id="e1b1", text="Built API")])])


def _cfg(stop: bool) -> ReviewConfig:
    return ReviewConfig(max_rounds=3, score_threshold=85, early_stop_on_regression=stop,
                        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)])


def test_early_stop_halts_after_regression():
    rounds = run_tailor_review("jd", JobCriteria(), _facts(), _cfg(True),
                               _CleanTailor(), {"ats-keyword": _DescendingReviewer()}, _CleanTailor())
    assert len(rounds) == 2  # round1=80, round2=70 regressed -> stop


def test_no_early_stop_runs_all_rounds():
    rounds = run_tailor_review("jd", JobCriteria(), _facts(), _cfg(False),
                               _CleanTailor(), {"ats-keyword": _DescendingReviewer()}, _CleanTailor())
    assert len(rounds) == 3  # never passes threshold; runs to max_rounds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_workflow.py -v -k early_stop`
Expected: FAIL — `ReviewConfig() got an unexpected keyword argument 'early_stop_on_regression'`

- [ ] **Step 3: Write the implementation**

Add the flag to `ReviewConfig` in `src/resume_agent/tailor/review_config.py`:

```python
    early_stop_on_regression: bool = False  # cost lever; safe — Phase 1 still surfaces the best round
```

In `src/resume_agent/tailor/workflow.py`, add the early-stop guard to **both** loops, immediately after the existing `if verdict.passed or round_num == config.max_rounds: break`. Sync (`run_tailor_review`, after line 56):

```python
        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        if (
            config.early_stop_on_regression
            and len(rounds) >= 2
            and any(round_.verdict.gate_passed for round_ in rounds[:-1])
            and (
                not rounds[-1].verdict.gate_passed
                or rounds[-1].verdict.aggregate_score
                < max(
                    round_.verdict.aggregate_score
                    for round_ in rounds[:-1]
                    if round_.verdict.gate_passed
                )
            )
        ):
            break
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts, config.length_budget),
            reviser_agent,
        )
    return rounds
```

Apply the identical guard in `arun_tailor_review` (after its `break`, line 95), before the `content = await arevise(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_workflow.py -v -k early_stop`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire the A/B config**

Create `config/review.early_stop.yaml` — a copy of `config/review.yaml` with `early_stop_on_regression: true`. Adopt (flip the default) only if the harness shows it cuts rounds/cost while `mean(candidate - baseline output_quality) >= -2 AND trap_recall unchanged`:

```bash
make eval                                                            # baseline
.venv/Scripts/python.exe -m evals.run_eval --config config/review.early_stop.yaml
```

- [ ] **Step 6: Full offline suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`

```bash
git add src/resume_agent/tailor/review_config.py src/resume_agent/tailor/workflow.py config/review.early_stop.yaml tests/test_tailor_workflow.py
git commit -m "Adds default-off regression early-stop cost lever"
```

---

## Deferred levers — interface-locked, implement after the baseline ranks them

Per the spec (§3.2: _"adopt greedily while quality holds"_) and writing-plans' YAGNI, the two heavier behavior-changing levers are **not** built speculatively. Build each as its own task **only after** a recorded baseline shows the prior lever earned its place and the band holds. Each is specified enough to start without re-deriving the design.

### Lever B — Tier escalation (eval-gated)

- **Config:** `ReviewConfig.escalation_enabled: bool = False`, `escalation_band: int = 5`.
- **Behavior:** each non-gate reviewer runs at its **cheap** tier first; if its score is within `escalation_band` of `score_threshold` (contested), re-run that reviewer at **premium** and keep the premium critique. Gates (fact-check, provenance) always run at their configured tier.
- **Shape:** build a `{name: (cheap_runner, premium_runner)}` map once in the bundle; add an `escalate` wrapper consumed by `run_panel`/`arun_panel` (passed via `config`), never building agents inside the loop.
- **Risk:** the cheap tier may misjudge a contested score. **Adopt only if** `mean(candidate - baseline output_quality) >= -2 AND trap_recall unchanged` and cost drops.

### Lever C — Skip passed reviewers (eval-gated, highest risk)

- **Config:** `ReviewConfig.skip_passed_enabled: bool = False`.
- **Behavior:** on a revise round, skip re-running non-gate reviewers that **passed** the previous round and carry their prior critique forward into the verdict. The **fact-check and provenance gates always re-run** (revision is exactly when new fabrication can enter).
- **Shape:** thread a `skip: set[str]` into `_panel_inputs`/`run_panel`; merge carried critiques into `aggregate`'s scored set. Touches `panel.py`, `workflow.py`, `verdict.py`.
- **Risk (spec-flagged as unsound):** a whole-resume `revise` can stale a carried-forward score (an ATS fix can hurt concision). **Adopt only if** the band holds across repeated runs; pairs best **after** Phase 2's surgical-patch protocol (deferred there) makes revisions local.

### Further cache lever — cache the JD/profile prefix (investigate)

agno's `cache_system_prompt` caches only the system prompt. The larger stable prefix (JD + profile/evidence, currently in the **user** message) is not cached. Caching it requires relocating it into the system message or attaching a manual `cache_control` block — a bigger change with its own correctness surface. Investigate only if Task 2's `cache_read_tokens` shows the instruction-only cache is too small to matter.

---

## Self-Review

**Spec coverage (`2026-06-30-phase3-cost-latency-design.md`):**

- §3.1 measurement first (Task 0): confirm `RunOutput` usage shape + cache surface, wire token usage into the report — Task 1 (cache split) builds on Phase 0's capture; the cache surface is confirmed in Global Constraints. ✓
- §3.2 ships unconditionally — cache-aware system-prompt caching, transparent, no quality A/B — Task 2. ✓
- §3.2 eval-gated by tolerance band — regression early-stop implemented default-off with an A/B config (Task 3); tier-escalation and skip-passed interface-locked for post-baseline adoption (Deferred levers), each with the explicit signed-delta quality gate. ✓
- §5 fact-lock constraint on skip-passed (gate always re-runs) — encoded in the Lever C spec. ✓
- §7 open items: tolerance band pinned (Global Constraints); tier-escalation trigger specified (Lever B); cache attaches to the system prompt (confirmed). ✓

**Placeholder scan:** Tasks 1–3 contain complete edits and tests. The Deferred-levers section is **intentionally** interface-only (not placeholder code) with explicit adoption gates — building them now would violate YAGNI and the spec's "adopt greedily" rule.

**Type consistency:** `cache_system_prompt` flows `Settings.prompt_cache_enabled` → `build_model(..., cache_system_prompt=)` → tailor-family/match-plan/judge builders. `cache_read_tokens`/`cache_write_tokens` flow agno metrics → `UsageCollector` → `UsageTotals` → `render_report`. `early_stop_on_regression` is read only inside both workflow loops. ✓

## Notes for the implementer

- This phase **does** change `src/resume_agent/tailor/` (unlike Phases 0–1) — that is expected; it is gated on Phases 1 and 2 being merged so quality is settled first.
- Cache caveat: `cache_read_tokens > 0` is the only proof the cache took effect. A `0` reading means the cached prefix is below Anthropic's minimum — the lever is still safe, just inert; pursue the JD/profile-prefix lever instead.
- Do not flip any eval-gated default (`early_stop_on_regression`, and later `escalation_enabled`/`skip_passed_enabled`) without a recorded run showing the band held. Eight stochastic cases are directional, not proof — confirm across repeated timestamped runs.
