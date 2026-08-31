"""Career Lab REST contract and run-backed lifecycle."""

import time
from typing import Literal

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.career_skills.models import AgentFamily, AgentRunMeta
from resume_tailor_harness.career_skills.registry import CareerSkillRegistry
from resume_tailor_harness.career_lab.models import CareerLabArtifactMeta
from resume_tailor_harness.services import career_lab as service


class _Response:
    def __init__(self, content):
        self.content = content


class _Persona:
    def __init__(self):
        skill = CareerSkillRegistry.from_paths("skills", "skills-lock.json").require(
            "salary-negotiation-prep",
            family=AgentFamily.CAREER_LAB,
            use="career_lab",
        )
        self.run_meta = AgentRunMeta(
            agent_family=AgentFamily.CAREER_LAB,
            prompt_policy_version="career-lab-persona-v1",
            model_id="test",
            skill_ref=skill.ref,
        )

    def run(self, _prompt):
        return _Response("Draft negotiation points.")


class _Formatter:
    def run(self, _prompt):
        return _Response(
            CareerLabArtifactMeta(
                artifact_type="negotiation_plan",
                title="Negotiation plan",
                summary="Ask for a clear tradeoff between base and equity.",
            )
        )


class _Router:
    run_meta = AgentRunMeta(
        agent_family=AgentFamily.CAREER_LAB,
        prompt_policy_version="career-lab-router-v2",
        model_id="test",
    )

    def run(self, _prompt):
        from resume_tailor_harness.career_lab.models import CareerLabRoute

        return _Response(
            CareerLabRoute(
                needs_selection=True,
                reason="The intended outcome is unclear.",
            )
        )


def _client(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    )


def _wait(client, run_id):
    for _ in range(200):
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        if run["state"] in {"done", "error", "cancelled"}:
            return run
        time.sleep(0.02)
    raise AssertionError("run never finished")


def test_skill_capability_contract(tmp_path):
    client = _client(tmp_path)
    with client:
        response = client.get("/api/career-lab/skills")
        assert response.status_code == 200
        names = {row["name"] for row in response.json()["skills"]}
        assert len(names) == 12
        assert "salary-negotiation-prep" in names
        assert all("directory" not in row for row in response.json()["skills"])


def test_start_message_end_and_archive_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.resolve_api_key",
        lambda _model, **_kwargs: "key",
    )
    monkeypatch.setattr(
        service, "build_persona_agent", lambda _skill, **_kwargs: _Persona()
    )
    monkeypatch.setattr(
        service, "build_formatter_agent", lambda **_kwargs: _Formatter()
    )
    client = _client(tmp_path)
    with client:
        started = client.post(
            "/api/career-lab/sessions",
            json={
                "goal": "Prepare negotiation points",
                "message": "Compare base and equity.",
                "skill": "salary-negotiation-prep",
            },
        )
        assert started.status_code == 202, started.text
        assert started.json()["kind"] == "career-lab-turn"
        result = _wait(client, started.json()["runId"])
        assert result["state"] == "done", result
        session_id = result["result"]["sessionId"]

        conflict = client.post(
            "/api/career-lab/sessions", json={"message": "another draft"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SESSION_ACTIVE"

        detail = client.get(f"/api/career-lab/sessions/{session_id}")
        assert detail.status_code == 200
        assert (
            detail.json()["turns"][1]["skillRef"]["name"] == "salary-negotiation-prep"
        )

        renamed = client.patch(
            f"/api/career-lab/sessions/{session_id}",
            json={"title": "Equity trade-offs"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Equity trade-offs"
        assert renamed.json()["goal"] == "Prepare negotiation points"
        assert (
            client.get("/api/career-lab/sessions").json()["sessions"][0]["title"]
            == "Equity trade-offs"
        )

        message = client.post(
            f"/api/career-lab/sessions/{session_id}/messages",
            json={"message": "Make it concise.", "skill": "salary-negotiation-prep"},
        )
        assert message.status_code == 202
        assert _wait(client, message.json()["runId"])["state"] == "done"

        ended = client.post(f"/api/career-lab/sessions/{session_id}/end")
        assert ended.status_code == 202
        assert _wait(client, ended.json()["runId"])["state"] == "done"
        assert (
            client.get(f"/api/career-lab/sessions/{session_id}").json()["status"]
            == "ended"
        )

        archived = client.post(f"/api/career-lab/sessions/{session_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["archivedAt"]
        assert client.get("/api/career-lab/sessions").json()["sessions"] == []
        assert (
            client.delete(f"/api/career-lab/sessions/{session_id}").status_code == 204
        )


def test_start_uses_keys_from_the_effective_app_settings(monkeypatch, tmp_path):
    from resume_tailor_harness.config import Settings

    env = tmp_path / "app.env"
    env.write_text(
        "MID_MODEL=openai:app-mid\n"
        "CHEAP_MODEL=openai:app-cheap\n"
        "OPENAI_API_KEY=app-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "resume_tailor_harness.config.env_settings",
        lambda: Settings(_env_file=None),  # type: ignore[call-arg]
    )
    monkeypatch.setattr(
        service, "build_persona_agent", lambda _skill, **_kwargs: _Persona()
    )
    monkeypatch.setattr(
        service, "build_formatter_agent", lambda **_kwargs: _Formatter()
    )
    client = TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    )

    with client:
        response = client.post(
            "/api/career-lab/sessions",
            json={
                "goal": "Prepare negotiation points",
                "message": "Compare base and equity.",
                "skill": "salary-negotiation-prep",
            },
        )

    assert response.status_code == 202, response.text


def _seed_job(app, company: str) -> int:
    from resume_tailor_harness.db import get_session
    from resume_tailor_harness.tracking.tables import Job

    with get_session(app.state.engine) as session:
        job = Job(
            source="manual", jd_text="Build things.", company=company, title="Eng"
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        return job.id


def _start_for_job(client, job_id: int | None):
    body: dict = {
        "message": "What should I ask about?",
        "skill": "salary-negotiation-prep",
    }
    if job_id is not None:
        body["context"] = {"jobId": job_id}
    return client.post("/api/career-lab/sessions", json=body)


def test_sessions_anchor_to_a_job_and_scope_the_active_conflict(monkeypatch, tmp_path):
    """Two jobs may each hold an open thread; one job may not hold two."""
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.resolve_api_key",
        lambda _model, **_kwargs: "key",
    )
    monkeypatch.setattr(
        service, "build_persona_agent", lambda _skill, **_kwargs: _Persona()
    )
    monkeypatch.setattr(
        service, "build_formatter_agent", lambda **_kwargs: _Formatter()
    )
    client = _client(tmp_path)
    with client:
        first = _seed_job(client.app, "Acme")
        second = _seed_job(client.app, "Globex")

        started = _start_for_job(client, first)
        assert started.status_code == 202, started.text
        # The run names its job: a start has no session id yet, so this is the
        # only thing that tells the Career Lab page the run is not its own.
        assert started.json()["meta"]["jobId"] == first
        first_session = _wait(client, started.json()["runId"])["result"]
        assert first_session["jobId"] == first

        # A different job is a different bucket, so this must be accepted.
        other = _start_for_job(client, second)
        assert other.status_code == 202, other.text
        assert _wait(client, other.json()["runId"])["result"]["jobId"] == second

        # The same job already has an open thread.
        conflict = _start_for_job(client, first)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "SESSION_ACTIVE"
        assert (
            conflict.json()["error"]["details"]["sessionId"]
            == (first_session["sessionId"])
        )

        # An un-anchored thread is its own bucket and stays available.
        unanchored = _start_for_job(client, None)
        assert unanchored.status_code == 202, unanchored.text
        assert _wait(client, unanchored.json()["runId"])["result"]["jobId"] is None

        listing = client.get("/api/career-lab/sessions", params={"jobId": first})
        assert listing.status_code == 200
        rows = listing.json()["sessions"]
        assert [row["sessionId"] for row in rows] == [first_session["sessionId"]]
        assert rows[0]["jobId"] == first
        assert listing.json()["pagination"]["totalItems"] == 1
        # Unfiltered still sees all three.
        assert len(client.get("/api/career-lab/sessions").json()["sessions"]) == 3


def test_deleting_a_job_removes_its_career_lab_threads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.resolve_api_key",
        lambda _model, **_kwargs: "key",
    )
    monkeypatch.setattr(
        service, "build_persona_agent", lambda _skill, **_kwargs: _Persona()
    )
    monkeypatch.setattr(
        service, "build_formatter_agent", lambda **_kwargs: _Formatter()
    )
    client = _client(tmp_path)
    with client:
        job_id = _seed_job(client.app, "Acme")
        started = _start_for_job(client, job_id)
        assert started.status_code == 202, started.text
        session_id = _wait(client, started.json()["runId"])["result"]["sessionId"]

        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        assert client.get(f"/api/career-lab/sessions/{session_id}").status_code == 404
        assert client.get("/api/career-lab/sessions").json()["sessions"] == []


def _write_session(
    root,
    session_id,
    *,
    started_at,
    status: Literal["active", "ended"] = "active",
    job_id=None,
):
    from resume_tailor_harness.career_lab.models import CareerLabSession
    from resume_tailor_harness.career_lab.store import store

    root.mkdir(parents=True, exist_ok=True)
    store.write(
        root,
        CareerLabSession(
            session_id=session_id,
            started_at=started_at,
            status=status,
            ended_at=None if status == "active" else started_at,
            job_id=job_id,
        ).model_dump(mode="json"),
    )


def test_listing_exposes_all_active_threads_outside_pagination(tmp_path):
    client = _client(tmp_path)
    with client:
        root = tmp_path / "data" / "career-lab"
        _write_session(
            root,
            "open-old",
            started_at="2026-08-01T00:00:00+00:00",
            job_id=7,
        )
        _write_session(
            root,
            "open-new",
            started_at="2026-08-10T00:00:00+00:00",
            job_id=9,
        )
        _write_session(
            root,
            "open-unanchored",
            started_at="2026-07-01T00:00:00+00:00",
        )
        _write_session(
            root, "ended-new", started_at="2026-08-09T00:00:00+00:00", status="ended"
        )
        _write_session(
            root, "ended-mid", started_at="2026-08-05T00:00:00+00:00", status="ended"
        )

        listing = client.get("/api/career-lab/sessions", params={"pageSize": 1}).json()

        assert [row["sessionId"] for row in listing["sessions"]] == ["open-new"]
        assert [row["sessionId"] for row in listing["activeSessions"]] == [
            "open-new",
            "open-old",
            "open-unanchored",
        ]


def test_listing_labels_anchored_threads_with_the_job(tmp_path):
    client = _client(tmp_path)
    with client:
        job_id = _seed_job(client.app, "Globex")
        root = tmp_path / "data" / "career-lab"
        _write_session(
            root, "anchored", started_at="2026-08-09T00:00:00+00:00", job_id=job_id
        )
        _write_session(root, "loose", started_at="2026-08-01T00:00:00+00:00")

        rows = {
            row["sessionId"]: row
            for row in client.get("/api/career-lab/sessions").json()["sessions"]
        }
        assert rows["anchored"]["jobCompany"] == "Globex"
        assert rows["anchored"]["jobTitle"] == "Eng"
        # An un-anchored thread has no job to name.
        assert rows["loose"]["jobCompany"] is None
        assert rows["loose"]["jobTitle"] is None


def test_listing_tolerates_a_thread_whose_job_is_gone(tmp_path):
    """A stale anchor must not blank the page or 500 — it just has no label."""
    client = _client(tmp_path)
    with client:
        root = tmp_path / "data" / "career-lab"
        _write_session(
            root, "orphan", started_at="2026-08-09T00:00:00+00:00", job_id=4242
        )

        rows = client.get("/api/career-lab/sessions").json()["sessions"]
        assert [row["sessionId"] for row in rows] == ["orphan"]
        assert rows[0]["jobId"] == 4242
        assert rows[0]["jobCompany"] is None


def test_job_delete_survives_a_corrupt_career_lab_session_file(tmp_path):
    """The cascade runs after the job row is committed, so it must not 500.

    A single unreadable file used to fail the whole scan, turning every future
    job delete into a 500 for a job that had in fact already been removed.
    """
    client = _client(tmp_path)
    with client:
        job_id = _seed_job(client.app, "Acme")
        career_lab_dir = tmp_path / "data" / "career-lab"
        career_lab_dir.mkdir(parents=True, exist_ok=True)
        (career_lab_dir / "session-bad.json").write_text("{not json", encoding="utf-8")

        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        assert client.get("/api/career-lab/sessions").json()["sessions"] == []


def test_ambiguous_route_starts_a_session_with_a_clarifying_question(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.resolve_api_key",
        lambda _model, **_kwargs: "key",
    )
    monkeypatch.setattr(service, "build_router_agent", lambda **_kwargs: _Router())
    client = _client(tmp_path)
    with client:
        response = client.post(
            "/api/career-lab/sessions",
            json={"message": "Help me with my career"},
        )
        assert response.status_code == 202
        result = _wait(client, response.json()["runId"])
        assert result["state"] == "done"
        assert result["result"]["sessionId"]
        assert [turn["role"] for turn in result["result"]["turns"]] == [
            "user",
            "assistant",
        ]
        clarification = result["result"]["turns"][-1]
        assert clarification["text"].endswith("a career decision?")
        assert clarification["skillRef"] is None
        assert clarification["agentMeta"]["prompt_policy_version"] == (
            "career-lab-router-v2"
        )
        listing = client.get("/api/career-lab/sessions").json()
        assert listing["sessions"][0]["sessionId"] == result["result"]["sessionId"]
