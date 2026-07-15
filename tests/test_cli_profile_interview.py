from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.profile.corpus import add_source


def _setup(monkeypatch, tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Acme experience", encoding="utf-8")
    add_source(profile_dir, resume, primary=True, mode="literal")
    round_result = {
        "roundId": "r1",
        "questions": [
            {
                "id": "q1",
                "gap": "Acme impact",
                "whyItMatters": "",
                "questionText": "What measurable impact?",
                "relatedRef": "",
            }
        ],
        "researchActions": [],
    }
    submitted = {}
    built = []
    monkeypatch.setattr(cli, "resolve_api_key", lambda model: "key")
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"cheap_model": "cheap", "mid_model": "mid", "db_url": "sqlite://"},
        )(),
    )
    monkeypatch.setattr(cli, "_engine", lambda db_url: object())
    monkeypatch.setattr(
        "resume_agent.services.profile_interview.run_interview_round",
        lambda reporter, **kwargs: round_result,
    )

    def submit(profile_dir, round_id, answers):
        submitted["args"] = (round_id, answers)
        return ["doc-1"]

    monkeypatch.setattr(
        "resume_agent.services.profile_interview.submit_interview_answers", submit
    )
    monkeypatch.setattr(
        "resume_agent.services.profile_build.run_corpus_build",
        lambda reporter, **kwargs: built.append(kwargs) or {"experiences": 1},
    )
    return profile_dir, submitted, built


def test_profile_interview_saves_and_builds_by_default(monkeypatch, tmp_path):
    profile_dir, submitted, built = _setup(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        cli.app,
        ["profile", "interview", "--facts", str(profile_dir / "facts.json")],
        input="Cut deploy time 40%\n",
    )

    assert result.exit_code == 0, result.output
    assert "What measurable impact?" in result.output
    assert submitted["args"] == ("r1", [("q1", "Cut deploy time 40%")])
    assert built and "Rebuilt profile" in result.output


def test_profile_interview_no_build_batches_answers(monkeypatch, tmp_path):
    profile_dir, _submitted, built = _setup(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        cli.app,
        [
            "profile",
            "interview",
            "--facts",
            str(profile_dir / "facts.json"),
            "--no-build",
        ],
        input="Evidence\n",
    )

    assert result.exit_code == 0, result.output
    assert not built
    assert "saved without rebuilding" in result.output.lower()
