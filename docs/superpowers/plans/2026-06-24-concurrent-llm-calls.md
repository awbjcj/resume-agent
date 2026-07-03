# Concurrent LLM Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the independent, I/O-bound LLM calls in discovery (relevance / extract / score) and tailor (across jobs _and_ each job's reviewer panel) concurrently with asyncio, bounded by one global semaphore, so wall-clock time stops growing linearly with job count.

**Architecture:** A small `concurrency.py` provides `gather_isolated` (run coroutines concurrently, return results in input order, isolate per-item failures, report completion count for progress). The `Runner` seam gains `arun`; a single `asyncio.Semaphore` is acquired **only inside the leaf agent call** (`acall`), never around orchestration coroutines, so nested tailor fan-out (jobs × panel) cannot deadlock. Each phase keeps a **sync** public signature and runs `asyncio.run(...)` internally: load rows → fan out the pure LLM calls → apply results to the `Session` + commit on the single event-loop thread (no locks, no per-worker sessions). Retry/backoff is delegated to agno's per-agent config (`retries`, `delay_between_retries`, `exponential_backoff`).

**Tech Stack:** Python 3.13, asyncio, agno 2.6.12 (`Agent.arun` → non-blocking `await asyncio.sleep` backoff), SQLModel/SQLite, pydantic-settings, pytest.

**Spec:** `docs/superpowers/specs/2026-06-24-concurrent-llm-calls-design.md`

---

## Design notes the implementer must respect

- **Leaf-only semaphore.** The `asyncio.Semaphore` is acquired solely in `acall(agent, prompt, *, sem)`. Orchestration coroutines (the per-job loop, the panel gather) never hold a permit while awaiting a child that needs one — that is what prevents the nested-fan-out deadlock. Do **not** move the semaphore into `gather_isolated`.
- **Semaphore construction.** On Python 3.10+ `asyncio.Semaphore(n)` does **not** bind to a loop at construction; it binds lazily on first `async with`. So constructing it _before_ `asyncio.run(...)` and using it inside is correct here.
- **Validate semaphore size.** `Settings.llm_concurrency` must be `>= 1`; `0` would create a zero-permit semaphore and hang every `acall`. Retry count/delay must be `>= 0`.
- **Pure LLM functions only inside the fan-out.** The async siblings (`aextract_job_criteria`, `ascore_fit`, `ajudge_relevance`, `areview_one`, `atailor`, `arevise`, `arun_tailor_review`) touch **no** `Session`. All DB mutation happens after the gather, serially, on the main thread.
- **Error isolation semantics.** Discovery already skips a failed job (leaves it in its prior status for the next run); `gather_isolated` reproduces this. Tailor previously had _no_ per-job isolation — a failure aborted the whole run and lost earlier work only if uncommitted. The new tailor path **improves** this: a failed job is skipped (left in `approved`), peers still persist. This is an intentional, documented behavior change on the _error_ path; the _success_ path produces identical DB state.
- **Keep the sync siblings.** `score_fit`, `extract_job_criteria`, `judge_relevance`, `review_one`, `run_panel`, `tailor`, `revise`, `run_tailor_review` stay as-is (still call `agent.run`). Their unit tests stay green unchanged. Only the higher-level phase orchestrators switch to the async siblings.
- **Fakes that flow into async paths need `arun`.** Confirmed sites: `tests/test_discovery_pipeline.py` (`_ExtractAgent`, `_FitAgent`, `_Judge`, `_ReextractAgent`, `_SicLocFitAgent`, `_OneBadExtractAgent`, `_RawStrExtractAgent`, `_OneBadFitAgent`), `tests/test_tailor_service.py` (`_ContentAgent`, `_FactCheck`), `tests/test_services_discovery.py` (`_bundle()` dynamic fakes). Add `async def arun(self, prompt): return self.run(prompt)` to each. The final task runs the full suite to catch any straggler.

---

### Task 1: Concurrency & retry settings

**Files:**

- Modify: `src/resume_agent/config.py:16-31` (Settings fields)
- Test: `tests/test_config.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or append to `tests/test_config.py`:

```python
import pytest


def test_concurrency_settings_defaults(monkeypatch):
    for key in ("LLM_CONCURRENCY", "LLM_RETRIES", "LLM_RETRY_DELAY"):
        monkeypatch.delenv(key, raising=False)
    from resume_agent.config import Settings

    s = Settings()
    assert s.llm_concurrency == 8
    assert s.llm_retries == 2
    assert s.llm_retry_delay == 1


def test_concurrency_settings_reject_invalid_values(monkeypatch):
    from pydantic import ValidationError

    from resume_agent.config import Settings

    for key in ("LLM_CONCURRENCY", "LLM_RETRIES", "LLM_RETRY_DELAY"):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("LLM_CONCURRENCY", "0")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("LLM_CONCURRENCY", "1")
    monkeypatch.setenv("LLM_RETRIES", "-1")
    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("LLM_RETRIES", "0")
    monkeypatch.setenv("LLM_RETRY_DELAY", "-1")
    with pytest.raises(ValidationError):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'llm_concurrency'`
or missing validation fields.

- [ ] **Step 3: Add the fields**

In `src/resume_agent/config.py`, add the import:

```python
from pydantic import Field
```

Then, after the `cors_origins` line inside `Settings`:

```python
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    # Concurrency + retry for LLM fan-out (discovery + tailor).
    llm_concurrency: int = Field(default=8, ge=1)  # max in-flight LLM calls
    llm_retries: int = Field(default=2, ge=0)  # agno per-agent retries
    llm_retry_delay: int = Field(default=1, ge=0)  # agno delay seconds, exponential
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py tests/test_config.py
git commit -m "feat: add llm_concurrency and retry settings"
```

---

### Task 2: `gather_isolated` fan-out helper

**Files:**

- Create: `src/resume_agent/concurrency.py`
- Test: `tests/test_concurrency.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_concurrency.py`:

```python
import asyncio

from resume_agent.concurrency import Result, gather_isolated


def test_gather_isolated_preserves_order_and_isolates_errors():
    async def fn(x):
        # Later items finish first, proving order is by input index not completion.
        await asyncio.sleep(0.01 * (3 - x))
        if x == 1:
            raise ValueError("boom")
        return x * 10

    results = asyncio.run(gather_isolated([0, 1, 2], fn))

    assert results[0].ok and results[0].value == 0
    assert (not results[1].ok) and isinstance(results[1].error, ValueError)
    assert results[2].ok and results[2].value == 20


def test_gather_isolated_reports_completion_count():
    seen: list[int] = []

    async def fn(x):
        await asyncio.sleep(0.001)
        return x

    asyncio.run(gather_isolated([0, 1, 2], fn, on_complete=seen.append))
    assert sorted(seen) == [1, 2, 3]


def test_gather_isolated_empty():
    assert asyncio.run(gather_isolated([], lambda x: x)) == []  # type: ignore[arg-type]


def test_result_defaults():
    r = Result(ok=False)
    assert r.value is None and r.error is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_concurrency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.concurrency'`.

- [ ] **Step 3: Write the module**

Create `src/resume_agent/concurrency.py`:

```python
"""Error-isolated concurrent fan-out for LLM calls.

asyncio (not threads) so the single event-loop thread can mutate the SQLModel
Session before/after the fan-out without locks — only the leaf network calls run
concurrently. Concurrency is bounded by the semaphore the caller threads into the
leaf calls (see ``resume_agent.llm_runner.acall``); this helper imposes no limit
of its own, so nested fan-out (tailor jobs x reviewer panel) cannot deadlock on
permits held by its own parents.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class Result(Generic[R]):
    """Outcome of one fanned-out call: a value on success, else the exception."""

    ok: bool
    value: R | None = None
    error: Exception | None = None


async def gather_isolated(
    items: Sequence[T],
    fn: Callable[[T], Awaitable[R]],
    *,
    on_complete: Callable[[int], None] | None = None,
) -> list[Result[R]]:
    """Run ``fn(item)`` for every item concurrently; results in input order.

    A raising item is captured as ``Result(ok=False, error=...)`` and never
    aborts its peers. ``on_complete`` is called with the running completed count
    as each task finishes (single-threaded, so it may call a ProgressReporter
    directly). Concurrency is bounded by the caller's leaf-call semaphore.
    """
    results: list[Result[R]] = [Result(ok=False) for _ in items]
    completed = 0

    async def run_one(index: int, item: T) -> None:
        nonlocal completed
        try:
            results[index] = Result(ok=True, value=await fn(item))
        except Exception as exc:  # isolate: one failure must not abort the batch
            results[index] = Result(ok=False, error=exc)
        finally:
            completed += 1
            if on_complete is not None:
                on_complete(completed)

    await asyncio.gather(*(run_one(i, item) for i, item in enumerate(items)))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_concurrency.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/concurrency.py tests/test_concurrency.py
git commit -m "feat: add gather_isolated concurrent fan-out helper"
```

---

### Task 3: `Runner.arun`, `acall`, and `retry_kwargs`

**Files:**

- Modify: `src/resume_agent/llm_runner.py:1-19` (imports + Runner + AgentRunner), append `acall` + `retry_kwargs`
- Test: `tests/test_llm_runner.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_runner.py`:

```python
def test_agent_runner_arun_delegates():
    import asyncio

    from resume_agent.llm_runner import AgentRunner

    class _AsyncAgent:
        async def arun(self, prompt):
            return f"got {prompt}"

    out = asyncio.run(AgentRunner(_AsyncAgent()).arun("hi"))
    assert out == "got hi"


def test_acall_respects_semaphore_limit():
    import asyncio

    from resume_agent.concurrency import gather_isolated
    from resume_agent.llm_runner import acall

    state = {"now": 0, "max": 0}

    class _Result:
        def __init__(self, content):
            self.content = content

    class _Agent:
        def run(self, prompt):  # unused in async path
            return _Result(prompt)

        async def arun(self, prompt):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.02)
            state["now"] -= 1
            return _Result(prompt)

    agent = _Agent()

    async def go():
        sem = asyncio.Semaphore(2)
        return await gather_isolated(range(6), lambda i: acall(agent, str(i), sem=sem))

    results = asyncio.run(go())
    assert state["max"] <= 2  # the semaphore actually bounds in-flight calls
    assert all(r.ok for r in results)


def test_retry_kwargs_reads_settings(monkeypatch):
    monkeypatch.setenv("LLM_RETRIES", "5")
    monkeypatch.setenv("LLM_RETRY_DELAY", "3")
    from resume_agent.config import get_settings
    from resume_agent.llm_runner import retry_kwargs

    get_settings.cache_clear()
    try:
        assert retry_kwargs() == {
            "retries": 5,
            "delay_between_retries": 3,
            "exponential_backoff": True,
        }
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner.py -k "arun or acall or retry_kwargs" -v`
Expected: FAIL — `AttributeError`/`ImportError` for `arun` / `acall` / `retry_kwargs`.

- [ ] **Step 3: Implement**

In `src/resume_agent/llm_runner.py`, replace the top of the file (lines 1-19) with:

```python
import asyncio
from typing import Any, Protocol

from resume_agent.config import get_settings


class Runner(Protocol):
    """Minimal surface the pipeline expects from an LLM agent (sync + async)."""

    def run(self, prompt: str) -> Any: ...

    async def arun(self, prompt: str) -> Any: ...


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run`` / ``arun``."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, prompt: str) -> Any:
        return self._agent.run(prompt)

    async def arun(self, prompt: str) -> Any:
        return await self._agent.arun(prompt)
```

Then append at the end of `src/resume_agent/llm_runner.py`:

```python
async def acall(agent: Runner, prompt: str, *, sem: asyncio.Semaphore) -> Any:
    """Run one agent call, holding a semaphore permit only for its duration.

    The permit is the global concurrency cap; acquiring it solely here (the leaf)
    keeps nested fan-out deadlock-free.
    """
    async with sem:
        return await agent.arun(prompt)


def retry_kwargs() -> dict[str, Any]:
    """agno per-agent retry config, spread into every ``Agent(...)`` we build."""
    s = get_settings()
    return {
        "retries": s.llm_retries,
        "delay_between_retries": s.llm_retry_delay,
        "exponential_backoff": True,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm_runner.py -v`
Expected: PASS (all, including the existing provider tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/llm_runner.py tests/test_llm_runner.py
git commit -m "feat: add Runner.arun, acall semaphore leaf, retry_kwargs"
```

---

### Task 4: Wire `retry_kwargs()` into every agent builder

**Files:**

- Modify: `src/resume_agent/discovery/extract.py:22-33`
- Modify: `src/resume_agent/discovery/fit.py:40-51`
- Modify: `src/resume_agent/discovery/relevance.py:30-44`
- Modify: `src/resume_agent/discovery/url_ingest/llm.py:15-26`
- Modify: `src/resume_agent/cover_letter/agents.py:21-44`
- Modify: `src/resume_agent/tailor/agents.py:57-97`
- Test: `tests/test_discovery_extract.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discovery_extract.py`:

```python
def test_build_extract_agent_carries_retry_config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    from resume_agent.config import get_settings

    get_settings.cache_clear()
    try:
        runner = build_extract_agent(model_id="claude-haiku-4-5-20251001")
        agent = runner._agent  # AgentRunner wraps the agno Agent
        assert agent.retries == 2
        assert agent.exponential_backoff is True
        assert agent.delay_between_retries == 1
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py::test_build_extract_agent_carries_retry_config -v`
Expected: FAIL — `assert 0 == 2` (agno default `retries=0`).

- [ ] **Step 3: Add `retry_kwargs()` to each builder**

In every builder below, add the import and spread `**retry_kwargs()` into the `Agent(...)` call (after `use_json_mode=...`).

`src/resume_agent/discovery/extract.py` — change the import line:

```python
from resume_agent.llm_runner import AgentRunner, Runner, build_model, retry_kwargs, use_json_mode_for
```

and the `Agent(...)`:

```python
        Agent(
            model=model,
            description="You extract structured hiring criteria from job descriptions.",
            instructions=_INSTRUCTIONS,
            output_schema=JobCriteriaExtract,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
```

`src/resume_agent/discovery/fit.py` — import:

```python
from resume_agent.llm_runner import AgentRunner, Runner, build_model, retry_kwargs, use_json_mode_for
```

and add `**retry_kwargs(),` after `use_json_mode=use_json_mode_for(model),` in `build_fit_agent`.

`src/resume_agent/discovery/relevance.py` — import (add `retry_kwargs` to the existing multi-line import) and add `**retry_kwargs(),` after `use_json_mode=use_json_mode_for(model),` inside the `Agent(...)` in `build_relevance_agent` (the branch after the `if not resolve_api_key(...)` guard).

`src/resume_agent/discovery/url_ingest/llm.py` — import:

```python
from resume_agent.llm_runner import AgentRunner, Runner, build_model, retry_kwargs, use_json_mode_for
```

and add `**retry_kwargs(),` in `build_url_extract_agent`'s `Agent(...)`.

`src/resume_agent/cover_letter/agents.py` — import:

```python
from resume_agent.llm_runner import AgentRunner, Runner, build_model, retry_kwargs, use_json_mode_for
```

and add `**retry_kwargs(),` in **both** `build_cover_letter_agent` and `build_cover_letter_reviser_agent`.

`src/resume_agent/tailor/agents.py` — import:

```python
from resume_agent.llm_runner import AgentRunner, Runner, build_model, retry_kwargs, use_json_mode_for
```

and add `**retry_kwargs(),` in **all three** of `build_tailor_agent`, `build_reviser_agent`, `build_reviewer_agent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/extract.py src/resume_agent/discovery/fit.py src/resume_agent/discovery/relevance.py src/resume_agent/discovery/url_ingest/llm.py src/resume_agent/cover_letter/agents.py src/resume_agent/tailor/agents.py tests/test_discovery_extract.py
git commit -m "feat: configure agno retry/backoff on every agent builder"
```

---

### Task 5: Async discovery siblings

**Files:**

- Modify: `src/resume_agent/discovery/extract.py` (append `aextract_job_criteria`)
- Modify: `src/resume_agent/discovery/fit.py` (append `ascore_fit`)
- Modify: `src/resume_agent/discovery/relevance.py` (append `ajudge_relevance`)
- Test: `tests/test_discovery_extract.py`, `tests/test_discovery_fit.py`, `tests/test_discovery_relevance.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_discovery_extract.py`:

```python
def test_aextract_job_criteria_uses_arun_and_semaphore():
    import asyncio

    from resume_agent.discovery.extract import aextract_job_criteria

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            self.received = prompt
            return _FakeResult(_extract(industry="fintech"))

    agent = _AsyncAgent()

    async def go():
        return await aextract_job_criteria("jd text", agent, sem=asyncio.Semaphore(2))

    out = asyncio.run(go())
    assert isinstance(out, JobCriteria)
    assert out.industry == "fintech"
    assert agent.received == "jd text"
```

Append to `tests/test_discovery_fit.py` (mirror its existing fake style; `FitScore` and a `_Result`/fake are already imported/defined there — reuse them):

```python
def test_ascore_fit_uses_arun():
    import asyncio

    from resume_agent.discovery.fit import FitScore, ascore_fit

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            class _R:
                content = FitScore(score=88, rationale="ok")

            return _R()

    out = asyncio.run(ascore_fit("input", _AsyncAgent(), sem=asyncio.Semaphore(2)))
    assert isinstance(out, FitScore) and out.score == 88
```

Append to `tests/test_discovery_relevance.py`:

```python
def test_ajudge_relevance_uses_arun():
    import asyncio

    from resume_agent.discovery.relevance import RelevanceVerdict, ajudge_relevance

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            class _R:
                content = RelevanceVerdict(keep=True, reason="ok")

            return _R()

    out = asyncio.run(
        ajudge_relevance("target", "Eng", "jd", _AsyncAgent(), sem=asyncio.Semaphore(2))
    )
    assert isinstance(out, RelevanceVerdict) and out.keep is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_relevance.py -k "aextract or ascore or ajudge" -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement the siblings**

`src/resume_agent/discovery/extract.py` — add `import asyncio` at top and `acall` to the `llm_runner` import, then append:

```python
async def aextract_job_criteria(
    jd_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> JobCriteria:
    result = await acall(agent, jd_text, sem=sem)
    extracted = result.content
    if not isinstance(extracted, JobCriteriaExtract):
        raise TypeError(f"Expected JobCriteriaExtract from agent, got {type(extracted).__name__}")
    return extracted.to_criteria()
```

`src/resume_agent/discovery/fit.py` — add `import asyncio` and `acall` to the import, then append:

```python
async def ascore_fit(input_text: str, agent: Runner, *, sem: asyncio.Semaphore) -> FitScore:
    result = await acall(agent, input_text, sem=sem)
    fit = result.content
    if not isinstance(fit, FitScore):
        raise TypeError(f"Expected FitScore from agent, got {type(fit).__name__}")
    return fit
```

`src/resume_agent/discovery/relevance.py` — add `import asyncio` and `acall` to the import, then append:

```python
async def ajudge_relevance(
    target_role: str, title: str | None, jd_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> RelevanceVerdict:
    result = await acall(agent, compose_relevance_input(target_role, title, jd_text), sem=sem)
    verdict = result.content
    if not isinstance(verdict, RelevanceVerdict):
        raise TypeError(f"Expected RelevanceVerdict from agent, got {type(verdict).__name__}")
    return verdict
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_relevance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/extract.py src/resume_agent/discovery/fit.py src/resume_agent/discovery/relevance.py tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_relevance.py
git commit -m "feat: add async siblings for extract/score/relevance"
```

---

### Task 6: Make discovery phases concurrent

**Files:**

- Modify: `src/resume_agent/discovery/pipeline.py` (imports + `run_extract`, `run_score`, `run_relevance`)
- Test: `tests/test_discovery_pipeline.py` (add `arun` to existing fakes; add concurrency tests)

- [ ] **Step 1: Add `arun` to the existing pipeline fakes**

In `tests/test_discovery_pipeline.py`, add this method to every fake class that
can flow into `run_extract`, `run_score`, or `run_relevance`: `_ExtractAgent`,
`_FitAgent`, `_Judge`, `_ReextractAgent`, `_SicLocFitAgent`,
`_OneBadExtractAgent`, `_RawStrExtractAgent`, and `_OneBadFitAgent` (right after
their `run` method):

```python
    async def arun(self, prompt):
        return self.run(prompt)
```

- [ ] **Step 2: Write the failing concurrency test**

Append to `tests/test_discovery_pipeline.py`:

```python
def test_run_extract_runs_concurrently_and_isolates_failures(monkeypatch):
    import time

    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    from resume_agent.config import get_settings

    get_settings.cache_clear()

    class _SlowExtract:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            import asyncio

            await asyncio.sleep(0.05)
            if "boom" in prompt:
                return _Result("not-a-criteria-object")  # wrong type -> TypeError -> isolated
            return _Result(_extract(industry="fintech"))

    try:
        with _session() as s:
            for i in range(5):
                add_job(
                    s, source="manual", jd_text=("boom" if i == 2 else f"jd{i}"),
                    title=f"T{i}", company=f"C{i}",
                )
            t0 = time.perf_counter()
            run_extract(s, _SlowExtract())
            elapsed = time.perf_counter() - t0

            extracted = jobs_by_status(s, JobStatus.extracted.value)
            raw = jobs_by_status(s, JobStatus.raw.value)
            assert len(extracted) == 4  # four succeeded
            assert len(raw) == 1  # the 'boom' job left raw (failure isolated)
        # 5 x 50ms serial = 250ms; concurrent ~50ms. Generous margin for CI.
        assert elapsed < 0.2
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest "tests/test_discovery_pipeline.py::test_run_extract_runs_concurrently_and_isolates_failures" -v`
Expected: FAIL — currently serial, so `elapsed` ≈ 0.25s, `assert elapsed < 0.2` fails (and `_SlowExtract.run` raises `NotImplementedError` because the code still calls `.run`).

- [ ] **Step 4: Rewrite the three phases**

In `src/resume_agent/discovery/pipeline.py`, update the imports at the top:

```python
import asyncio
from pathlib import Path

from sqlmodel import Session

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.discovery.extract import Runner, aextract_job_criteria, extract_job_criteria  # noqa: F401
from resume_agent.discovery.filter import apply_filters
from resume_agent.discovery.fit import FitScore, ascore_fit, compose_fit_input, score_fit  # noqa: F401
from resume_agent.discovery.relevance import ajudge_relevance, judge_relevance  # noqa: F401
```

(Keep the remaining existing imports unchanged.)

Replace `run_extract` (currently lines ~30-58) with:

```python
def run_extract(
    session: Session,
    agent: Runner,
    reporter: ProgressReporter | None = None,
    job_ids: set[int] | None = None,
) -> None:
    jobs = jobs_by_status(session, JobStatus.raw.value)
    if job_ids is not None:
        jobs = [job for job in jobs if job.id in job_ids]
    if reporter:
        reporter.begin(
            len(jobs), "Extracting criteria", phase_index=2, phase_count=_DISCOVER_PHASES
        )
    if jobs:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None
        results = asyncio.run(
            gather_isolated(
                jobs,
                lambda job: aextract_job_criteria(job.jd_text, agent, sem=sem),
                on_complete=on_complete,
            )
        )
        for job, res in zip(jobs, results):
            # A single job's unparseable LLM output must not discard the rest;
            # leave it raw so the next discover retries it (mirrors run_relevance).
            if not res.ok:
                continue
            job.criteria_json = res.value.model_dump(mode="json")
            job.status = JobStatus.extracted.value
            session.add(job)
    session.commit()
```

Replace `run_score` (currently lines ~82-117) with:

```python
def run_score(
    session: Session,
    profile_facts: ProfileFacts,
    agent: Runner,
    canonicalizer: Canonicalizer | None = None,
    aliases_path: Path | str = SKILL_ALIASES_PATH,
    reporter: ProgressReporter | None = None,
    job_ids: set[int] | None = None,
) -> None:
    jobs = jobs_by_status(session, JobStatus.filtered.value)
    if job_ids is not None:
        jobs = [job for job in jobs if job.id in job_ids]
    if reporter:
        reporter.begin(len(jobs), "Scoring fit", phase_index=3, phase_count=_DISCOVER_PHASES)
    if jobs:
        locations = [_job_location_text(job) for job in jobs]
        pairs = list(zip(jobs, locations))
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None
        results = asyncio.run(
            gather_isolated(
                pairs,
                lambda pair: ascore_fit(
                    compose_fit_input(pair[0].jd_text, profile_facts, pair[1]), agent, sem=sem
                ),
                on_complete=on_complete,
            )
        )
        for (job, location_text), res in zip(pairs, results):
            # One job's unparseable fit output must not abort scoring; leave it
            # filtered so the next discover retries it.
            if not res.ok:
                continue
            fit = res.value
            job.fit_score = fit.score
            job.fit_rationale = fit.rationale
            _write_taxonomy_fields(job, fit, location_text)
            job.status = JobStatus.shortlisted.value
            session.add(job)
    session.commit()
    if canonicalizer is not None:
        _refresh_skill_aliases(
            jobs_by_status(session, JobStatus.shortlisted.value), canonicalizer, aliases_path
        )
```

Replace `run_relevance` (currently lines ~161-203) with:

```python
def run_relevance(
    session: Session,
    config: SearchConfig,
    agent: Runner | None,
    reporter: ProgressReporter | None = None,
    job_ids: set[int] | None = None,
) -> int:
    """Reject off-target raw jobs via the cheap relevance gate."""
    target = _relevance_target(config)
    if target is None or agent is None:
        return 0

    jobs = jobs_by_status(session, JobStatus.raw.value)
    if job_ids is not None:
        jobs = [job for job in jobs if job.id in job_ids]
    # Empty-text jobs are kept (skipped), exactly as before; only judge the rest.
    judged = [job for job in jobs if (job.jd_text or "").strip()]
    skipped = len(jobs) - len(judged)
    if reporter:
        reporter.begin(
            len(jobs), "Checking relevance", phase_index=1, phase_count=_DISCOVER_PHASES
        )
    rejected = 0
    if judged:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(skipped + n)) if reporter else None
        results = asyncio.run(
            gather_isolated(
                judged,
                lambda job: ajudge_relevance(target, job.title, job.jd_text or "", agent, sem=sem),
                on_complete=on_complete,
            )
        )
        for job, res in zip(judged, results):
            if not res.ok:
                continue
            verdict = res.value
            if not verdict.keep:
                reason = (verdict.reason or "model rejected").strip()
                job.status = JobStatus.rejected.value
                job.reject_reason = f"off-target role: {reason}"
                job.reject_category = "relevance"
                session.add(job)
                rejected += 1
    if reporter:
        reporter.step(len(jobs))  # ensure the bar reaches total even if all skipped
    session.commit()
    return rejected
```

- [ ] **Step 5: Run the full pipeline test file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v`
Expected: PASS (existing tests + the new concurrency test).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "feat: run discovery relevance/extract/score concurrently"
```

---

### Task 7: Async tailor leaf calls, panel, and workflow

**Files:**

- Modify: `src/resume_agent/tailor/tailoring.py` (append `atailor`, `arevise`)
- Modify: `src/resume_agent/tailor/panel.py` (extract `_panel_inputs`; add `areview_one`, `arun_panel`)
- Modify: `src/resume_agent/tailor/workflow.py` (append `arun_tailor_review`)
- Test: `tests/test_tailor_panel.py`, `tests/test_tailor_workflow.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tailor_panel.py`:

```python
def test_arun_panel_runs_reviewers_concurrently_in_order():
    import asyncio
    import time

    from resume_agent.tailor.panel import arun_panel

    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="a"), ReviewerSpec(name="b"), ReviewerSpec(name="c")]
    )

    class _Slow:
        def __init__(self, name):
            self.name = name

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ReviewCritique(reviewer=self.name, score=80, passed=True))

    agents = {n: _Slow(n) for n in ("a", "b", "c")}

    async def go():
        return await arun_panel(_content(), _facts(), "jd", config, agents, sem=asyncio.Semaphore(8))

    t0 = time.perf_counter()
    critiques = asyncio.run(go())
    elapsed = time.perf_counter() - t0

    assert [c.reviewer for c in critiques] == ["a", "b", "c"]  # input order preserved
    assert elapsed < 0.12  # ~50ms concurrent vs ~150ms serial


def test_arun_panel_settles_reviewers_before_raising():
    import asyncio

    import pytest

    from resume_agent.tailor.panel import arun_panel

    config = ReviewConfig(reviewers=[ReviewerSpec(name="boom"), ReviewerSpec(name="slow")])
    events: list[str] = []

    class _Agent:
        def __init__(self, name, *, fail=False):
            self.name = name
            self.fail = fail

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            events.append(f"{self.name}:start")
            await asyncio.sleep(0.01 if self.fail else 0.05)
            if self.fail:
                events.append(f"{self.name}:raise")
                raise RuntimeError("reviewer down")
            events.append(f"{self.name}:done")
            return _Result(ReviewCritique(reviewer=self.name, score=80, passed=True))

    agents = {"boom": _Agent("boom", fail=True), "slow": _Agent("slow")}

    async def go():
        return await arun_panel(_content(), _facts(), "jd", config, agents, sem=asyncio.Semaphore(8))

    with pytest.raises(RuntimeError):
        asyncio.run(go())
    assert "slow:done" in events
```

Append to `tests/test_tailor_workflow.py` (it already constructs `JobCriteria`, `ProfileFacts`, `ReviewConfig`, and a sync content/critique fake — reuse those imports; add an async fake):

```python
def test_arun_tailor_review_passes_with_async_agents():
    import asyncio

    from resume_agent.models.job import JobCriteria
    from resume_agent.models.profile import Contact, ProfileFacts
    from resume_agent.models.resume import ResumeContent
    from resume_agent.models.review import ReviewCritique
    from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
    from resume_agent.tailor.workflow import arun_tailor_review

    class _Result:
        def __init__(self, content):
            self.content = content

    class _Content:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _Result(ResumeContent(contact=Contact(name="Ada")))

    class _FactCheck:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    async def go():
        return await arun_tailor_review(
            "jd", JobCriteria(), ProfileFacts(contact=Contact(name="Ada")), config,
            _Content(), {"fact-check": _FactCheck()}, _Content(), sem=asyncio.Semaphore(8),
        )

    rounds = asyncio.run(go())
    assert len(rounds) == 1
    assert rounds[0].round_num == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py::test_arun_panel_runs_reviewers_concurrently_in_order tests/test_tailor_panel.py::test_arun_panel_settles_reviewers_before_raising tests/test_tailor_workflow.py::test_arun_tailor_review_passes_with_async_agents -v`
Expected: FAIL — `arun_panel` / `arun_tailor_review` not defined.

- [ ] **Step 3: Implement async tailor leaf calls**

In `src/resume_agent/tailor/tailoring.py`, add `import asyncio` at the top and `acall` to the `llm_runner` import (`from resume_agent.llm_runner import Runner, acall`), then append:

```python
async def atailor(input_text: str, agent: Runner, *, sem: asyncio.Semaphore) -> ResumeContent:
    result = await acall(agent, input_text, sem=sem)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from tailor agent, got {type(content).__name__}")
    return content


async def arevise(input_text: str, agent: Runner, *, sem: asyncio.Semaphore) -> ResumeContent:
    result = await acall(agent, input_text, sem=sem)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from reviser agent, got {type(content).__name__}")
    return content
```

- [ ] **Step 4: Implement the panel changes**

Rewrite `src/resume_agent/tailor/panel.py`. Add `import asyncio` at the top and `acall` to the `llm_runner` import. Add `_panel_inputs`, refactor `run_panel` to use it, and add the async pair. Replace `run_panel` (lines ~48-65) with:

```python
def _panel_inputs(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
) -> list[tuple[str, str]]:
    """(reviewer_name, input_text) pairs, smallest sufficient input per role."""
    evidence = resolve_evidence(content, profile_facts)
    stats = resume_stats(content)
    inputs: list[tuple[str, str]] = []
    for spec in config.reviewers:
        if spec.gate:
            text = compose_evidence_review_input(content, jd_text, evidence)
        else:
            text = compose_lean_review_input(content, jd_text, stats)
        inputs.append((spec.name, text))
    return inputs


def run_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
) -> list[ReviewCritique]:
    """Run configured reviewers serially (sync path; kept for sync callers)."""
    return [
        review_one(text, reviewer_agents[name])
        for name, text in _panel_inputs(content, profile_facts, jd_text, config)
    ]


async def areview_one(input_text: str, agent: Runner, *, sem: asyncio.Semaphore) -> ReviewCritique:
    result = await acall(agent, input_text, sem=sem)
    critique = result.content
    if not isinstance(critique, ReviewCritique):
        raise TypeError(f"Expected ReviewCritique from reviewer, got {type(critique).__name__}")
    return critique


async def arun_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
    *,
    sem: asyncio.Semaphore,
) -> list[ReviewCritique]:
    """Run configured reviewers concurrently; results in reviewer order.

    Reviewer errors are re-raised only after all reviewers settle. There is no
    reviewer-level isolation: one failed reviewer fails this job, which is then
    isolated at the job level in tailor_jobs.
    """
    inputs = _panel_inputs(content, profile_facts, jd_text, config)
    outputs = await asyncio.gather(
        *(areview_one(text, reviewer_agents[name], sem=sem) for name, text in inputs),
        return_exceptions=True,
    )
    critiques: list[ReviewCritique] = []
    first_error: BaseException | None = None
    for output in outputs:
        if isinstance(output, BaseException):
            first_error = first_error or output
        else:
            critiques.append(output)
    if first_error is not None:
        raise first_error
    return critiques
```

- [ ] **Step 5: Implement the async workflow**

In `src/resume_agent/tailor/workflow.py`, update the imports to add the async siblings:

```python
from resume_agent.tailor.panel import arun_panel, run_panel
from resume_agent.tailor.tailoring import (
    atailor,
    arevise,
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)
```

and add `import asyncio` at the top. Append:

```python
async def arun_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    *,
    sem: asyncio.Semaphore,
) -> list[TailorRound]:
    """Async twin of run_tailor_review: draft + panel run via the shared semaphore.

    Rounds stay sequential (each depends on the previous); the panel within a
    round runs concurrently. Touches no Session — DB writes happen after gather.
    """
    content = await atailor(
        compose_tailor_input(jd_text, criteria, profile_facts, config.length_budget),
        tailor_agent,
        sem=sem,
    )
    rounds: list[TailorRound] = []
    for round_num in range(1, config.max_rounds + 1):
        provenance = provenance_critique(content, profile_facts)
        if provenance.passed:
            panel = await arun_panel(
                content, profile_facts, jd_text, config, reviewer_agents, sem=sem
            )
            critiques = [provenance, *panel]
        else:
            critiques = [provenance]
        verdict = aggregate(critiques, config)
        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        content = await arevise(
            compose_revise_input(content, verdict.critiques, profile_facts, config.length_budget),
            reviser_agent,
            sem=sem,
        )
    return rounds
```

- [ ] **Step 6: Run the tailor unit tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py tests/test_tailor_workflow.py tests/test_tailor_tailoring.py -v`
Expected: PASS (existing sync tests + new async tests).

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/tailor/tailoring.py src/resume_agent/tailor/panel.py src/resume_agent/tailor/workflow.py tests/test_tailor_panel.py tests/test_tailor_workflow.py
git commit -m "feat: add async tailor leaf calls, concurrent panel, async workflow"
```

---

### Task 8: Concurrent tailor service (jobs × panel)

**Files:**

- Modify: `src/resume_agent/tailor/service.py` (split persist; rewrite `tailor_job`, `tailor_jobs`)
- Test: `tests/test_tailor_service.py` (add `arun` to fakes; add concurrency + isolation tests)

- [ ] **Step 1: Add `arun` to the existing service fakes**

In `tests/test_tailor_service.py`, add to both `_ContentAgent` and `_FactCheck` (after their `run` method):

```python
    async def arun(self, prompt):
        return self.run(prompt)
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_tailor_service.py`:

```python
def test_tailor_jobs_runs_jobs_concurrently(monkeypatch):
    import asyncio
    import time

    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    from resume_agent.config import get_settings

    get_settings.cache_clear()

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _SlowContent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ResumeContent(contact=Contact(name="Ada")))

    class _SlowFactCheck:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    try:
        with _session() as s:
            jobs = [
                save_job(s, Job(
                    source="manual", jd_text=f"jd{i}", status=JobStatus.approved.value,
                    criteria_json=JobCriteria().model_dump(mode="json"),
                ))
                for i in range(4)
            ]
            t0 = time.perf_counter()
            results = tailor_jobs(
                s, jobs, ProfileFacts(contact=Contact(name="Ada")), config,
                tailor_agent=_SlowContent(), reviewer_agents={"fact-check": _SlowFactCheck()},
                reviser_agent=_SlowContent(),
            )
            elapsed = time.perf_counter() - t0
            assert len(results) == 4
        # Per job: 1 draft + 1 panel call = ~100ms sequential within a job; 4 jobs
        # concurrent ~100ms, serial ~400ms.
        assert elapsed < 0.3
    finally:
        get_settings.cache_clear()


def test_tailor_jobs_isolates_a_failing_job():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _Boom:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            raise RuntimeError("model down")

    with _session() as s:
        ok_job = save_job(s, Job(
            source="manual", jd_text="ok", status=JobStatus.approved.value,
            criteria_json=JobCriteria().model_dump(mode="json"),
        ))
        bad_job = save_job(s, Job(
            source="manual", jd_text="bad", status=JobStatus.approved.value,
            criteria_json=JobCriteria().model_dump(mode="json"),
        ))
        # ok_job uses good agents; bad_job's tailor agent raises. Use a single
        # tailor agent that raises only for the bad job's jd text.
        class _Selective:
            def run(self, prompt):
                raise NotImplementedError

            async def arun(self, prompt):
                if "bad" in prompt:
                    raise RuntimeError("model down")
                return _Result(ResumeContent(contact=Contact(name="Ada")))

        results = tailor_jobs(
            s, [ok_job, bad_job], ProfileFacts(contact=Contact(name="Ada")), config,
            tailor_agent=_Selective(), reviewer_agents={"fact-check": _FactCheck()},
            reviser_agent=_Selective(),
        )

        assert _require_id(ok_job.id) in results  # peer persisted
        assert _require_id(bad_job.id) not in results  # failure isolated
        assert ok_job.status == JobStatus.tailored.value
        assert bad_job.status == JobStatus.approved.value  # left for retry


def test_tailor_jobs_rejects_unpersisted_job_before_llm_work():
    import pytest

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _NoCall:
        def run(self, prompt):
            raise AssertionError("LLM should not be called")

        async def arun(self, prompt):
            raise AssertionError("LLM should not be called")

    with _session() as s:
        job = Job(
            source="manual", jd_text="jd", status=JobStatus.approved.value,
            criteria_json=JobCriteria().model_dump(mode="json"),
        )
        with pytest.raises(ValueError):
            tailor_jobs(
                s, [job], ProfileFacts(contact=Contact(name="Ada")), config,
                tailor_agent=_NoCall(), reviewer_agents={"fact-check": _NoCall()},
                reviser_agent=_NoCall(),
            )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_service.py -k "concurrently or isolates or unpersisted" -v`
Expected: FAIL — `_SlowContent.run`/`_Boom.run` raise `NotImplementedError` because `tailor_jobs` still calls `.run` serially (and the timing assertion fails). The unpersisted-job test documents the current guard and may already pass before the rewrite.

- [ ] **Step 4: Rewrite the service**

Replace the whole body of `src/resume_agent/tailor/service.py` with:

```python
import asyncio
from collections.abc import Mapping, Sequence

from sqlmodel import Session

from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.progress import ProgressReporter
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import TailorRound, arun_tailor_review
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _persist_rounds(
    session: Session, job: Job, rounds: list[TailorRound]
) -> list[ResumeVersion]:
    """Persist each review round as a ResumeVersion and mark the job tailored."""
    versions: list[ResumeVersion] = []
    for r in rounds:
        version = ResumeVersion(
            job_id=job.id,
            round=r.round_num,
            content_json=r.content.model_dump(mode="json"),
            review_score=r.verdict.aggregate_score,
            fact_check_passed=r.verdict.gate_passed,
            critique_json=[c.model_dump(mode="json") for c in r.verdict.critiques],
        )
        versions.append(save_resume_version(session, version))
    job.status = JobStatus.tailored.value
    save_job(session, job)
    return versions


def tailor_job(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[ResumeVersion]:
    """Run the loop for one job and persist each round. Marks the job tailored."""
    if job.id is None:
        raise ValueError("Cannot tailor a job that has not been persisted")
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    sem = asyncio.Semaphore(get_settings().llm_concurrency)
    rounds = asyncio.run(
        arun_tailor_review(
            job.jd_text, criteria, profile_facts, config,
            tailor_agent, reviewer_agents, reviser_agent, sem=sem,
        )
    )
    return _persist_rounds(session, job, rounds)


def tailor_jobs(
    session: Session,
    targets: Sequence[Job],
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
    reporter: ProgressReporter | None = None,
) -> dict[int, list[ResumeVersion]]:
    """Tailor targets concurrently (jobs x reviewer panel under one semaphore).

    Returns ``{job_id: versions}``. LLM work for all jobs fans out under a shared
    cap; DB writes happen serially afterwards on this thread. A job whose LLM work
    fails is skipped (left in its prior status for the next run) so it never aborts
    its peers. Progress steps as each job's LLM work completes.
    """
    for job in targets:
        if job.id is None:
            raise ValueError("Cannot tailor a job that has not been persisted")
    if reporter:
        reporter.begin(len(targets), "Tailoring")
    results: dict[int, list[ResumeVersion]] = {}
    if targets:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        on_complete = (lambda n: reporter.step(n)) if reporter else None

        def _criteria(job: Job) -> JobCriteria:
            return JobCriteria.model_validate(job.criteria_json or {})

        rounds_results = asyncio.run(
            gather_isolated(
                list(targets),
                lambda job: arun_tailor_review(
                    job.jd_text, _criteria(job), profile_facts, config,
                    tailor_agent, reviewer_agents, reviser_agent, sem=sem,
                ),
                on_complete=on_complete,
            )
        )
        for job, res in zip(targets, rounds_results):
            if not res.ok:
                continue  # leave job in its prior status; next tailor run retries it
            if job.id is not None:
                results[job.id] = _persist_rounds(session, job, res.value)
    if reporter:
        reporter.done()
    return results
```

- [ ] **Step 5: Run the tailor service tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_service.py -v`
Expected: PASS (existing + new concurrency/isolation tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tailor/service.py tests/test_tailor_service.py
git commit -m "feat: run tailor jobs and panels concurrently under one cap"
```

---

### Task 9: Fix service-level integration fakes and run the full suite

**Files:**

- Modify: `tests/test_services_discovery.py:92-108` (`_bundle()` fakes need `arun`)
- Test: entire suite

- [ ] **Step 1: Give the `_bundle()` fakes an async path**

In `tests/test_services_discovery.py`, replace the `extract = type(...)` / `fit = type(...)` dynamic fakes inside `_bundle()` with explicit classes that have both `run` and `arun`:

```python
def _bundle():
    from resume_agent.discovery.fit import FitScore
    from resume_agent.models.job import JobCriteriaExtract, SponsorshipSignal
    from resume_agent.services.agents import DiscoveryBundle

    def _criteria():
        return JobCriteriaExtract.model_validate(dict(
            sponsorship_signal=SponsorshipSignal.offered, seniority=None,
            employment_type=None, tech_stack=[], industry=None, company_size=None,
            yoe_min=None, salary_range=None, remote_policy=None, location=None,
            must_have_skills=[], nice_to_have_skills=[],
        ))

    class _Extract:
        def run(self, p):
            return _FakeResult(_criteria())

        async def arun(self, p):
            return self.run(p)

    class _Fit:
        def run(self, p):
            return _FakeResult(FitScore(score=77, rationale="ok"))

        async def arun(self, p):
            return self.run(p)

    return DiscoveryBundle(extract=_Extract(), fit=_Fit(), relevance=None, canonicalizer=None)
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS — all tests green. If any test fails because a fake it passes into discovery/tailor lacks `arun`, add `async def arun(self, prompt): return self.run(prompt)` to that fake and re-run. (Known candidates already handled: all discovery pipeline fakes, tailor service fakes, and services discovery fakes.)

- [ ] **Step 3: Lint**

Run: `.venv/Scripts/python.exe -m ruff check`
Expected: clean. Fix any unused-import warnings (e.g. a now-unused `score_fit`/`extract_job_criteria` re-export — keep them, they have `# noqa: F401`, but remove genuinely dead imports).

- [ ] **Step 4: Commit**

```bash
git add tests/test_services_discovery.py
git commit -m "test: give service-level discovery fakes an async path"
```

---

### Task 10: Update developer docs

**Files:**

- Modify: `CLAUDE.md` ("Known design notes" + a Hot-paths/concurrency mention)

- [ ] **Step 1: Replace the deferral note**

In `CLAUDE.md`, under "Known design notes", replace the bullet:

```markdown
- **Tailor loop is synchronous.** Parallel reviewer panels and job-level concurrency are deferred
  while this pass reduces cost through leaner prompts.
```

with:

```markdown
- **Discovery + tailor LLM calls run concurrently** via asyncio. Each phase keeps a sync public
  signature and runs `asyncio.run(gather_isolated(...))` internally: load rows → fan out the pure
  async LLM siblings (`aextract_job_criteria`, `ascore_fit`, `ajudge_relevance`, `arun_tailor_review`)
  → apply to the Session + commit on the single event-loop thread (no locks). One global
  `asyncio.Semaphore(Settings.llm_concurrency)` per `asyncio.run` caps in-flight calls
  (`llm_concurrency` is validated `>= 1`); it is acquired
  **only** inside `llm_runner.acall` (the leaf), so nested tailor fan-out (jobs × panel) can't deadlock.
  Retry/backoff is agno's per-agent config via `retry_kwargs()` (`exponential_backoff=True`); note it
  retries bare `Exception`, so a parse failure costs `llm_retries` extra calls — kept low (default 2).
  A job whose LLM work fails is skipped (left in its prior status) and retried next run.
```

- [ ] **Step 2: Add the new module to the Hot paths table**

In `CLAUDE.md`, add a row to the "Hot paths" table:

```markdown
| `src/resume_agent/concurrency.py` | `gather_isolated` — ordered, error-isolated async fan-out |
```

- [ ] **Step 3: Verify docs only, then commit**

Run: `.venv/Scripts/python.exe -m pytest -q` (sanity: still green)
Expected: PASS.

```bash
git add CLAUDE.md
git commit -m "docs: record concurrent LLM fan-out design"
```

---

## Self-Review

**Spec coverage:**

- Goal/success (concurrent discovery + tailor, bounded, identical success-path DB) → Tasks 2, 6, 8.
- asyncio + `arun`, contained behind sync signatures → Tasks 3, 6, 8 (asyncio.run inside `run_*`/`tailor_jobs`; note: contained at the pipeline/tailor layer that services call, equivalent to the spec's "service boundary").
- Both tailor axes under one shared semaphore → Tasks 7 (arun_panel/arun_tailor_review) + 8 (one sem, nested).
- Leaf-only semaphore / deadlock avoidance → Task 3 (`acall`) + design notes.
- Reviewer-panel failures settle sibling calls before re-raising → Task 7.
- agno backoff retry + bare-except caveat → Tasks 1, 3, 4 + docs Task 10.
- New `concurrency.py` → Task 2.
- Progress under concurrency (step on completion) → Tasks 6, 8 (`on_complete`).
- Error isolation + input-order apply → Task 2 (`gather_isolated`) + Tasks 6, 8.
- Config fields → Task 1.
- Testing (cap, isolation, ordering, speedup, fakes get `arun`) → Tasks 2, 3, 6, 8, 9.
- Docs → Task 10.

**Placeholder scan:** none — every code step shows complete code; every test shows full assertions.

**Type consistency:** `Result(ok, value, error)`, `gather_isolated(items, fn, *, on_complete)`, `acall(agent, prompt, *, sem)`, `retry_kwargs()`, and the async siblings (`aextract_job_criteria`, `ascore_fit`, `ajudge_relevance`, `areview_one`, `arun_panel`, `atailor`, `arevise`, `arun_tailor_review`, `_persist_rounds`) use identical names and signatures across the tasks that define and call them.

**Known tradeoffs (intentional):**

- Timing-based assertions (`elapsed < ...`) use 4–5× margins; if a loaded CI flakes, raise the bound — they prove "not serial," not exact latency.
- Tailor error path now isolates per job (improvement over serial all-or-nothing); documented in Task 8 and CLAUDE.md.
- `asyncio.run` is created per phase in discovery (3 loops/discover) — phases are sequential so a per-phase semaphore is equivalent to a shared one; only tailor needs one shared sem (its nesting is within a single phase).
- `llm_concurrency` is validated as `>= 1`; a value of `0` would otherwise deadlock every leaf call waiting on the semaphore.
