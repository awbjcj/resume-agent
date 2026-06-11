from typer.testing import CliRunner

from resume_agent.models.profile import Contact, Project, ProfileFacts
from resume_agent import cli

runner = CliRunner()


def _write_sources(tmp_path):
    sources = tmp_path / "profile_sources.yaml"
    sources.write_text("resume_path: r.txt\ngithub_username: ada\n", encoding="utf-8")
    return sources


def test_profile_build_writes_facts(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"), projects=[Project(name="engine")])
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: (facts, "raw text"))

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"

    result = runner.invoke(cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "engine" in out.read_text(encoding="utf-8")


def test_profile_build_refuses_to_overwrite_without_refresh(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: (facts, "raw text"))

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"
    out.write_text("{}", encoding="utf-8")  # pre-existing (simulating manual edits)

    result = runner.invoke(cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out)])

    assert result.exit_code == 1
    assert out.read_text(encoding="utf-8") == "{}"  # not clobbered


def test_profile_build_refresh_overwrites(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: (facts, "raw text"))

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"
    out.write_text("{}", encoding="utf-8")

    result = runner.invoke(
        cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out), "--refresh"]
    )

    assert result.exit_code == 0, result.output
    assert "Ada" in out.read_text(encoding="utf-8")
