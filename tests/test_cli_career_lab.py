"""The Career Lab CLI remains a thin typed adapter over its service."""

from types import SimpleNamespace

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.career_lab.models import CareerLabContextRefs


def test_career_lab_command_passes_typed_context_and_skill(monkeypatch, tmp_path):
    captured = SimpleNamespace()

    class _Settings:
        stream_enabled = False

    class _Reporter:
        def begin(self, *_args, **_kwargs):
            pass

        def step(self, *_args, **_kwargs):
            pass

        def checkpoint(self):
            pass

    monkeypatch.setattr(cli, "get_settings", lambda: _Settings())
    monkeypatch.setattr(cli, "missing_model_keys", lambda _settings: [])
    monkeypatch.setattr(cli, "_engine", lambda _db_url: object())
    monkeypatch.setattr(cli, "_tenant_cli_path", lambda _path: tmp_path / "data")
    monkeypatch.setattr(
        "resume_agent.career_skills.registry.CareerSkillRegistry.from_settings",
        lambda _settings: SimpleNamespace(
            require=lambda name, **_kwargs: SimpleNamespace(
                ref=SimpleNamespace(name=name)
            )
        ),
    )

    def start(reporter, **kwargs):
        captured.goal = kwargs["goal"]
        captured.skill = kwargs["skill"]
        captured.context = kwargs["context_refs"]
        captured.root = kwargs["root"]
        return {
            "sessionId": "s1",
            "status": "active",
            "turns": [{"role": "assistant", "text": "draft"}],
        }

    monkeypatch.setattr("resume_agent.services.career_lab.run_start_turn", start)
    monkeypatch.setattr(
        "resume_agent.services.career_lab.run_end_turn",
        lambda reporter, **_kwargs: {"status": "ended"},
    )
    monkeypatch.setattr(
        "resume_agent.career_lab.store.active_session_for_job",
        lambda _root, _job_id: None,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "career-lab",
            "Negotiate offer",
            "--skill",
            "salary-negotiation-prep",
            "--offer-application-id",
            "7",
        ],
        input="Draft my counter\nend\n",
    )
    assert result.exit_code == 0, result.output
    assert captured.goal == "Negotiate offer"
    assert captured.skill == "salary-negotiation-prep"
    assert isinstance(captured.context, CareerLabContextRefs)
    assert captured.context.offer_application_ids == [7]


def test_career_lab_command_resumes_the_thread_for_the_given_job(monkeypatch, tmp_path):
    """`--job-id` must resume that job's thread, not whichever one is open.

    Active Career Lab threads are per job, so "resume whatever is active" could
    adopt another job's transcript and append this job's context to it.
    """
    captured = SimpleNamespace()

    class _Settings:
        stream_enabled = False

    monkeypatch.setattr(cli, "get_settings", lambda: _Settings())
    monkeypatch.setattr(cli, "missing_model_keys", lambda _settings: [])
    monkeypatch.setattr(cli, "_engine", lambda _db_url: object())
    monkeypatch.setattr(cli, "_tenant_cli_path", lambda _path: tmp_path / "data")

    def active_for_job(root, job_id):
        captured.asked_job_id = job_id
        return {"session_id": "job-seven-thread"}

    monkeypatch.setattr(
        "resume_agent.career_lab.store.active_session_for_job", active_for_job
    )
    monkeypatch.setattr(
        "resume_agent.services.career_lab.session_view",
        lambda _root, session_id: {
            "sessionId": session_id,
            "status": "active",
            "turns": [],
        },
    )
    monkeypatch.setattr(
        "resume_agent.services.career_lab.run_end_turn",
        lambda reporter, **_kwargs: {"status": "ended"},
    )

    result = CliRunner().invoke(cli.app, ["career-lab", "--job-id", "7"], input="end\n")

    assert result.exit_code == 0, result.output
    assert captured.asked_job_id == 7
    assert "Resuming your active Career Lab session." in result.output


def test_career_lab_command_keeps_prompting_after_a_clarification(
    monkeypatch, tmp_path
):
    captured = SimpleNamespace(messages=[])

    class _Settings:
        stream_enabled = False

    monkeypatch.setattr(cli, "get_settings", lambda: _Settings())
    monkeypatch.setattr(cli, "missing_model_keys", lambda _settings: [])
    monkeypatch.setattr(cli, "_engine", lambda _db_url: object())
    monkeypatch.setattr(cli, "_tenant_cli_path", lambda _path: tmp_path / "data")
    monkeypatch.setattr(
        "resume_agent.career_lab.store.active_session_for_job",
        lambda _root, _job_id: None,
    )

    def start(_reporter, **_kwargs):
        return {
            "sessionId": "s1",
            "status": "active",
            "turns": [
                {
                    "role": "assistant",
                    "text": "What outcome should the research support?",
                }
            ],
        }

    def message(_reporter, **kwargs):
        captured.messages.append(kwargs["message"])
        return {
            "sessionId": "s1",
            "status": "active",
            "turns": [{"role": "assistant", "text": "Here is your draft."}],
        }

    monkeypatch.setattr("resume_agent.services.career_lab.run_start_turn", start)
    monkeypatch.setattr("resume_agent.services.career_lab.run_message_turn", message)
    monkeypatch.setattr(
        "resume_agent.services.career_lab.run_end_turn",
        lambda _reporter, **_kwargs: {"status": "ended", "turns": []},
    )

    result = CliRunner().invoke(
        cli.app,
        ["career-lab"],
        input="Research Acme\nPrepare me to negotiate\nend\n",
    )

    assert result.exit_code == 0, result.output
    assert "What outcome should the research support?" in result.output
    assert captured.messages == ["Prepare me to negotiate"]
