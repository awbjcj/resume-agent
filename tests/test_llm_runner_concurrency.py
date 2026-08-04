"""Concurrency guarantees for the shared agent and the spend gate.

Two properties, both invisible to a single-call test and both load-bearing for
the concurrent fan-out that `discovery/pipeline.py` runs:

* one agno model object is shared by every coroutine in a batch, and applying a
  key nulls its cached clients — so a key flip must never land mid-request;
* the spend gate is synchronous SQLite I/O that can wait on a write lock, so it
  must not run on the event loop those coroutines share.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from resume_agent.config import Settings
from resume_agent.llm_runner import AgentRunner
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.spend import SpendDecision
from resume_agent.tenancy.workspace import WorkspacePaths

CONCURRENCY = 20


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _context(tmp_path, settings: Settings) -> UserContext:
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=settings,
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
        platform_provider_keys={"anthropic": "railway-key"},
        user_provider_keys={"anthropic": "user-key"},
    )


class _ClientWatchingAgent:
    """Records any request whose client was pulled out from under it."""

    def __init__(self) -> None:
        self.model = SimpleNamespace(
            id="claude-sonnet-5",
            provider="anthropic",
            api_key=None,
            client=None,
            async_client=None,
        )
        self.violations: list[str] = []

    async def arun(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        if self.model.async_client is None:
            # What agno does on first use: build and cache a client.
            self.model.async_client = object()
        before = self.model.async_client
        await asyncio.sleep(0.01)
        if self.model.async_client is not before:
            self.violations.append(prompt)
        return SimpleNamespace(
            content="ok",
            metrics=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    def run(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        return asyncio.run(self.arun(prompt))


class _FlippingGate:
    """A gate whose funded key changes on every single call."""

    calls = 0

    def __init__(self, **_kwargs: object) -> None:
        pass

    def open(self, model_id: str, **_kwargs: object) -> SpendDecision:
        type(self).calls += 1
        key = "railway-key" if type(self).calls % 2 else "user-key"
        return SpendDecision(key, key == "user-key", "anthropic", model_id, "test")


def test_concurrent_calls_never_lose_their_client_to_a_key_flip(tmp_path, monkeypatch):
    """A key change must land between phases, never under an in-flight sibling."""
    _FlippingGate.calls = 0
    monkeypatch.setattr("resume_agent.tenancy.spend.SpendGate", _FlippingGate)
    settings = _settings()
    agent = _ClientWatchingAgent()
    runner = AgentRunner(agent, settings=settings)

    async def drive() -> list[object]:
        return await asyncio.gather(
            *(runner.arun(f"job-{index}") for index in range(CONCURRENCY))
        )

    with use_context(_context(tmp_path, settings)):
        results = asyncio.run(drive())

    assert len(results) == CONCURRENCY
    assert agent.violations == []
    # The flip is not simply ignored: it is deferred. Once the runner is idle,
    # the next call applies the currently resolved key.
    assert _FlippingGate.calls == CONCURRENCY


class _SlowGate:
    """A gate that blocks the calling thread, as real SQLite I/O does."""

    delay = 0.1

    def __init__(self, **_kwargs: object) -> None:
        pass

    def open(self, model_id: str, **_kwargs: object) -> SpendDecision:
        time.sleep(type(self).delay)
        return SpendDecision("railway-key", False, "anthropic", model_id, "test")


@pytest.mark.parametrize("batch", [10])
def test_budget_check_does_not_serialise_the_fan_out(tmp_path, monkeypatch, batch):
    """Blocking I/O on the shared loop stalls every sibling in the batch."""
    monkeypatch.setattr("resume_agent.tenancy.spend.SpendGate", _SlowGate)
    settings = _settings()
    runner = AgentRunner(_ClientWatchingAgent(), settings=settings)

    async def drive() -> None:
        await asyncio.gather(*(runner.arun(f"job-{i}") for i in range(batch)))

    with use_context(_context(tmp_path, settings)):
        started = time.monotonic()
        asyncio.run(drive())
        elapsed = time.monotonic() - started

    serial = _SlowGate.delay * batch
    assert elapsed < serial / 2, f"{elapsed:.3f}s looks serialised (serial={serial}s)"


def test_gate_decision_is_reused_within_its_ttl_and_re_derived_after(tmp_path):
    """The TTL is a ceiling on staleness, not a per-call re-derivation."""
    from resume_agent.tenancy.spend import SpendGate

    settings = _settings(spend_gate_ttl_seconds=30.0)
    context = _context(tmp_path, settings)
    derivations = 0

    with use_context(context):
        gate = SpendGate(settings=settings)
        first = gate.select("claude-sonnet-5")
        cached = gate.select("claude-sonnet-5")
        assert first == cached
        assert len(context.spend_decisions) == 1

        # Expiry drops the entry rather than serving it stale.
        entry = context.spend_decisions["claude-sonnet-5"]
        entry.stamped -= 31.0  # type: ignore[union-attr]
        gate.select("claude-sonnet-5")
        derivations += 1

    assert derivations == 1


def test_settling_a_call_that_exhausts_the_budget_drops_the_decision(tmp_path):
    """Headroom is what makes the cache exact rather than merely time-bounded."""
    from resume_agent.tenancy.spend import SpendGate, _CachedDecision

    settings = _settings()
    context = _context(tmp_path, settings)
    decision = SpendDecision("railway-key", False, "anthropic", "m", "shared")

    with use_context(context):
        context.spend_decisions["m"] = _CachedDecision(
            time.monotonic(), decision, None, headroom=100.0, unit="weighted"
        )
        SpendGate().settle(weighted=40.0)
        assert "m" in context.spend_decisions

        SpendGate().settle(weighted=70.0)
        assert "m" not in context.spend_decisions
