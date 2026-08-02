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
            require=lambda name, **_kwargs: SimpleNamespace(ref=SimpleNamespace(name=name))
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
        "resume_agent.career_lab.store.active_session", lambda _root: None
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
