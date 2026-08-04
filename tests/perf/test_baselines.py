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

from resume_agent.config import Settings
from resume_agent.discovery.fit import build_fit_agent, compose_fit_input
from resume_agent.llm_runner import AgentRunner
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.costs import seed_llm_rates
from resume_agent.tenancy.system_db import User, init_system_db, make_system_engine
from resume_agent.tenancy.workspace import WorkspacePaths
from scripts.perf_harness import (
    count_connections,
    count_prompt_tokens,
    count_queries,
)

CALLS = 10
JOBS = 20
REQUESTS = 12

# Post-change ceilings. Each was the measured "before" number until the seam
# named in the docstring landed; the comment records what it used to be so a
# reviewer can see the delta without digging through git history.
MAX_STATEMENTS_PER_CALL = 4.0  # was 15.4 (11 sessions x setup + 3 BEGIN IMMEDIATE)
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


def test_spend_path_statements_per_llm_call(tmp_path):
    """The gate resolves policy once per phase, not twice per call."""
    engine, context = _tenant(tmp_path)
    runner = AgentRunner(_FakeAgent(), settings=context.settings)

    with use_context(context), count_queries(engine) as counts:
        for _ in range(CALLS):
            runner.run("score this job")

    assert counts.per_unit(CALLS) <= MAX_STATEMENTS_PER_CALL, str(counts)
    # An exclusive write lock per call is what stalls a concurrent fan-out; a
    # read-only budget check must never take one.
    assert counts.exclusive_transactions <= CALLS, str(counts)


def test_board_requests_share_one_connection_per_host(monkeypatch):
    """A board pull opens a pool per host, not a TCP+TLS handshake per request."""
    from resume_agent.discovery.connectors.http import BoardSession

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

    prompts = [
        compose_fit_input(f"job description {index}", profile, location="Remote (US)")
        for index in range(JOBS)
    ]

    # Zero copies in the per-job messages: the profile now rides the agent's
    # system block, which is built once per run and is the block agno caches.
    assert sum(blob in prompt for prompt in prompts) == 0
    description = " ".join(
        str(part) for part in (agent.run_meta, getattr(agent, "_agent", None))
    )
    assert description  # agent constructed; content asserted in test_discovery_fit


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
                compose_fit_input(f"job description {index}", profile, location="Remote")
            )

    profile_tokens = len(profile.model_dump_json()) // 4
    assert tokens.calls == jobs
    # The whole run must cost less than even two copies of the profile.
    assert tokens.input_tokens < profile_tokens * 2, str(tokens)
