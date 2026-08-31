"""Exact, offline perf baselines for the three units that scaled wrongly.

These are not benchmarks. Nothing here samples a clock or touches a network, so
every number is reproducible and a regression is a red test rather than a line
on a bill. The rule the architecture plan sets: a performance change must tighten
one of these assertions, or it is not a performance change.

Each test names the finding it pins:

* spend metering was per *call* rather than per *phase* (F3/F4/F5/F14)
* HTTP setup was per *request* rather than per *host* (F6)
* a run-constant document was re-sent per *job* rather than per *run* (F9)
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from resume_tailor_harness.config import Settings
from resume_tailor_harness.discovery.fit import (
    bind_profile,
    build_fit_agent,
    compose_fit_input,
)
from resume_tailor_harness.llm_runner import AgentRunner, resolve_api_key
from resume_tailor_harness.models.profile import Contact, ProfileFacts, Skill
from resume_tailor_harness.tenancy.context import UserContext, use_context
from resume_tailor_harness.tenancy.costs import seed_llm_rates
from resume_tailor_harness.tenancy.system_db import User, init_system_db, make_system_engine
from resume_tailor_harness.tenancy.workspace import WorkspacePaths
from scripts.perf_harness import (
    count_connections,
    count_prompt_tokens,
    count_queries,
)

CALLS = 10
JOBS = 20
REQUESTS = 12

# Post-change ceilings. The comment records the measured "before" so a reviewer
# can see the delta without digging through git history.
#
# The two spend numbers are separate on purpose. Policy derivation is what
# SpendGate owns and is cacheable to nearly nothing; settlement is the billing
# write — a UsageEvent, its line items, and the quota charge — which cannot be
# cached away without trading durability for speed, and is not in this plan's
# scope. Collapsing them into one number would let a settlement regression hide
# behind the gate's win.
MAX_GATE_STATEMENTS_PER_CALL = 1.0  # was 13.0
MAX_STATEMENTS_PER_CALL = 11.0  # was 22.2; floor is the billing write
MIN_REQUESTS_PER_CLIENT = float(REQUESTS)  # was 1.0 (a client per request)


class _Metrics(SimpleNamespace):
    pass


class _FakeAgent:
    """An agno-shaped agent whose token metrics track prompt length.

    Input tokens are derived from the prompt so the token counter measures the
    real reduction when a run-constant section moves out of the per-job message,
    instead of asserting on a hand-written constant.
    """

    def __init__(self, model_id: str = "claude-sonnet-5", provider: str = "Anthropic"):
        self.model = SimpleNamespace(
            id=model_id, provider=provider, api_key=None, client=None, async_client=None
        )
        self.prompts: list[str] = []

    def run(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        self.prompts.append(prompt)
        return SimpleNamespace(
            content="ok",
            metrics=_Metrics(
                input_tokens=len(prompt) // 4,
                output_tokens=10,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        )

    async def arun(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        return self.run(prompt)


def _tenant(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    seed_llm_rates(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
            )
        )
        session.commit()
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=engine,
        own_key_providers=frozenset(),
        platform_provider_keys={"anthropic": "sk-platform"},
    )
    return engine, context


def test_spend_policy_is_derived_once_per_phase_not_per_call(tmp_path):
    """Key selection and budget are a property of a phase, not of a call."""
    engine, context = _tenant(tmp_path)

    with use_context(context), count_queries(engine) as counts:
        for _ in range(CALLS):
            # The non-raising half of the gate; it shares the derivation with
            # the enforcing half, so counting either counts both.
            resolve_api_key("claude-sonnet-5")

    assert counts.per_unit(CALLS) <= MAX_GATE_STATEMENTS_PER_CALL, str(counts)
    # A read-only budget check must never take SQLite's exclusive write lock:
    # under a concurrent fan-out that serialises every sibling behind it.
    assert counts.exclusive_transactions == 0, str(counts)


def test_spend_path_statements_per_llm_call(tmp_path):
    """End to end, including the billing write that cannot be cached away."""
    engine, context = _tenant(tmp_path)
    runner = AgentRunner(_FakeAgent(), settings=context.settings)

    with use_context(context), count_queries(engine) as counts:
        for _ in range(CALLS):
            runner.run("score this job")

    assert counts.per_unit(CALLS) <= MAX_STATEMENTS_PER_CALL, str(counts)
    # One exclusive transaction per call is the quota charge itself. More than
    # that means a read has started taking the write lock again.
    assert counts.exclusive_transactions <= CALLS, str(counts)


def test_board_requests_share_one_connection_per_host(monkeypatch):
    """A board pull opens a pool per host, not a TCP+TLS handshake per request."""
    from resume_tailor_harness.discovery.connectors.http import BoardSession

    def _handle(_self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": []}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _handle)

    with count_connections() as counts:
        with BoardSession() as session:
            for index in range(REQUESTS):
                session.get(f"https://boards-api.greenhouse.io/v1/boards/t{index}")

    assert counts.requests == REQUESTS, str(counts)
    assert counts.requests_per_client >= MIN_REQUESTS_PER_CLIENT, str(counts)
    assert counts.distinct_hosts == 1, str(counts)


def _profile() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada Lovelace"),
        summary="Backend engineer " * 40,
        skills={
            "hard": [Skill(name=f"skill-{index}") for index in range(60)],
        },
    )


def test_fit_prompt_sends_the_run_constant_profile_once_per_run():
    """The profile is run-constant, so it belongs in the cacheable prefix."""
    profile = _profile()
    agent = build_fit_agent()
    blob = profile.model_dump_json()

    # What run_score does: bind once at the start of the phase...
    bound = bind_profile(agent, profile)
    assert bound is True
    assert blob in agent.agent.description

    # ...and then compose per-job messages that carry only what varies.
    prompts = [
        compose_fit_input(
            f"job description {index}",
            None,
            location="Remote (US)",
        )
        for index in range(JOBS)
    ]

    assert sum(blob in prompt for prompt in prompts) == 0


def test_binding_twice_does_not_duplicate_the_profile():
    """A rebound agent must not accumulate copies of the same document."""
    profile = _profile()
    agent = build_fit_agent()

    bind_profile(agent, profile)
    bind_profile(agent, profile)

    assert agent.agent.description.count("CANDIDATE PROFILE (JSON):") == 1


def test_a_stub_agent_keeps_the_profile_in_the_message():
    """The optimisation must never change what the model is told."""
    profile = _profile()

    assert bind_profile(_FakeAgent(), profile) is False
    assert profile.model_dump_json() in compose_fit_input("jd", profile)


@pytest.mark.parametrize("jobs", [JOBS])
def test_discovery_input_tokens_scale_with_the_job_not_the_profile(tmp_path, jobs):
    """Per-job input tokens must not carry the whole profile ``jobs`` times."""
    _engine, context = _tenant(tmp_path)
    profile = _profile()
    agent = _FakeAgent()
    runner = AgentRunner(agent, settings=context.settings)

    with use_context(context), count_prompt_tokens() as tokens:
        for index in range(jobs):
            runner.run(
                compose_fit_input(f"job description {index}", None, location="Remote")
            )

    profile_tokens = len(profile.model_dump_json()) // 4
    assert tokens.calls == jobs
    # The whole run must cost less than even two copies of the profile.
    assert tokens.input_tokens < profile_tokens * 2, str(tokens)
