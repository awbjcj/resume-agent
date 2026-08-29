"""The agent-run trace records what a run did, and never what it thought."""

from __future__ import annotations

from types import SimpleNamespace

from resume_agent.agent_trace import (
    agent_trace,
    current_trace,
    read_trace,
    record_agent_run,
)
from resume_agent.career_skills.models import AgentFamily, AgentRunMeta
from resume_agent.config import Settings
from resume_agent.llm_runner import AgentRunner


class _Agent:
    def __init__(self, *, fail: int = 0) -> None:
        self.model = SimpleNamespace(
            id="claude-sonnet-5", provider="anthropic", api_key=None
        )
        self.fail = fail
        self.calls = 0

    def run(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        self.calls += 1
        if self.calls <= self.fail:
            raise ValueError("permanent failure")
        return SimpleNamespace(
            content="ok",
            metrics=SimpleNamespace(
                input_tokens=1200,
                output_tokens=340,
                cache_read_tokens=1000,
                cache_write_tokens=0,
                reasoning_tokens=17,
            ),
            tools=[{"name": "h1b_get_company_stats"}],
        )

    async def arun(self, prompt: str, **_kwargs: object) -> SimpleNamespace:
        return self.run(prompt)


def _runner(agent: _Agent) -> AgentRunner:
    return AgentRunner(
        agent,
        run_meta=AgentRunMeta(
            agent_family=AgentFamily.JOB_ANALYSIS,
            prompt_policy_version="job-fit-v1",
            model_id="claude-sonnet-5",
            skill_ref=None,
        ),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
    )


def test_a_successful_call_records_identity_counts_and_status(tmp_path):
    path = tmp_path / "r1.agents.ndjson"

    with agent_trace(path):
        _runner(_Agent()).run("score this job")

    rows = read_trace(path)
    assert len(rows) == 1
    row = rows[0]
    assert row["family"] == AgentFamily.JOB_ANALYSIS.value
    assert row["model"] == "claude-sonnet-5"
    assert row["status"] == "ok"
    assert row["retries"] == 0
    assert row["toolCalls"] == 1
    assert row["inputTokens"] == 1200
    assert row["cacheReadTokens"] == 1000
    assert row["reasoningTokens"] == 17


def test_the_trace_carries_no_prompt_or_completion_text(tmp_path):
    """Operational events only — the same rule _map_stream_event enforces."""
    path = tmp_path / "r1.agents.ndjson"

    with agent_trace(path):
        _runner(_Agent()).run("a very distinctive prompt string")

    raw = path.read_text(encoding="utf-8")
    assert "a very distinctive prompt string" not in raw
    # No field carries model output. ``status`` happens to be the string "ok",
    # which is a state, not a completion.
    row = read_trace(path)[0]
    assert not {"content", "text", "prompt", "reasoning"} & set(row)


def test_a_failed_call_is_recorded_with_its_error(tmp_path):
    path = tmp_path / "r1.agents.ndjson"

    with agent_trace(path):
        try:
            _runner(_Agent(fail=1)).run("score this job")
        except ValueError:
            pass

    rows = read_trace(path)
    assert rows[0]["status"] == "error"
    assert "permanent failure" in rows[0]["error"]


def test_no_active_run_writes_nothing(tmp_path):
    """A CLI call outside a run has nowhere to trace to, and must not care."""
    assert current_trace() is None

    _runner(_Agent()).run("score this job")

    assert list(tmp_path.iterdir()) == []


def test_a_broken_trace_target_never_fails_the_run(tmp_path):
    """A trace is not the work."""
    # A directory where the file should be: opening it for append raises.
    path = tmp_path / "blocked.agents.ndjson"
    path.mkdir()

    with agent_trace(path):
        response = _runner(_Agent()).run("score this job")

    assert response.content == "ok"


def test_a_malformed_row_is_skipped_rather_than_raised(tmp_path):
    path = tmp_path / "r1.agents.ndjson"
    with agent_trace(path):
        record_agent_run(_runner(_Agent()), SimpleNamespace(metrics=None))
    path.write_text(path.read_text(encoding="utf-8") + "not json\n", encoding="utf-8")

    assert len(read_trace(path)) == 1


def test_the_run_manager_gives_each_run_its_own_trace(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from resume_agent.api.runs.manager import RunManager

    executor = ThreadPoolExecutor(max_workers=1)
    manager = RunManager(root=tmp_path, executor=executor)
    seen: list[object] = []

    def work(_reporter):
        seen.append(current_trace())
        return {"ok": True}

    run_id = manager.submit("pull", work)
    executor.shutdown(wait=True)
    manager.shutdown()

    assert seen == [manager.trace_path(run_id)]
    assert manager.trace_path(run_id).name.endswith(".agents.ndjson")
