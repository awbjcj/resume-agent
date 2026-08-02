"""Career Lab REST contract and run-backed lifecycle."""

import time

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.career_skills.models import AgentFamily, AgentRunMeta
from resume_agent.career_skills.registry import CareerSkillRegistry
from resume_agent.career_lab.models import CareerLabArtifactMeta
from resume_agent.services import career_lab as service


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
    run_meta = None

    def run(self, _prompt):
        from resume_agent.career_lab.models import CareerLabRoute

        return _Response(CareerLabRoute(needs_selection=True, reason="choose one"))


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
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda _model: "key")
    monkeypatch.setattr(service, "build_persona_agent", lambda _skill: _Persona())
    monkeypatch.setattr(service, "build_formatter_agent", lambda: _Formatter())
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
        assert detail.json()["turns"][1]["skillRef"]["name"] == "salary-negotiation-prep"

        message = client.post(
            f"/api/career-lab/sessions/{session_id}/messages",
            json={"message": "Make it concise.", "skill": "salary-negotiation-prep"},
        )
        assert message.status_code == 202
        assert _wait(client, message.json()["runId"])["state"] == "done"

        ended = client.post(f"/api/career-lab/sessions/{session_id}/end")
        assert ended.status_code == 202
        assert _wait(client, ended.json()["runId"])["state"] == "done"
        assert client.get(f"/api/career-lab/sessions/{session_id}").json()["status"] == "ended"

        archived = client.post(f"/api/career-lab/sessions/{session_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["archivedAt"]
        assert client.get("/api/career-lab/sessions").json()["sessions"] == []
        assert client.delete(f"/api/career-lab/sessions/{session_id}").status_code == 204


def test_ambiguous_route_returns_selection_without_persisting(monkeypatch, tmp_path):
    monkeypatch.setattr("resume_agent.llm_runner.resolve_api_key", lambda _model: "key")
    monkeypatch.setattr(service, "build_router_agent", lambda: _Router())
    client = _client(tmp_path)
    with client:
        response = client.post(
            "/api/career-lab/sessions",
            json={"message": "Help me with my career"},
        )
        assert response.status_code == 202
        result = _wait(client, response.json()["runId"])
        assert result["state"] == "done"
        assert result["result"]["needsSelection"] is True
        listing = client.get("/api/career-lab/sessions").json()
        assert listing["sessions"] == []
