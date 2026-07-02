from typer.testing import CliRunner

from resume_agent.models.profile import Contact, Project, ProfileFacts
from resume_agent.profile.build import BuildReport
from resume_agent import cli

runner = CliRunner()


def _write_sources(tmp_path):
    resume = tmp_path / "r.txt"
    resume.write_text("Ada", encoding="utf-8")
    sources = tmp_path / "profile_sources.yaml"
    sources.write_text(
        f"resume_path: {resume.as_posix()}\ngithub_username: ada\n",
        encoding="utf-8",
    )
    return sources


def _configure_build(monkeypatch, facts):
    monkeypatch.setattr(
        "resume_agent.profile.build.build_corpus_profile",
        lambda dir_, github_username, **kwargs: (facts, BuildReport()),
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type("S", (), {"cheap_model": "cheap", "mid_model": "mid"})(),
    )
    monkeypatch.setattr(cli, "resolve_api_key", lambda model: "sk-test")
    monkeypatch.setattr(
        "resume_agent.profile.merge.build_bullet_dedup_agent", lambda: object()
    )
    monkeypatch.setattr(
        "resume_agent.profile.inference.build_inference_agent", lambda: object()
    )


def test_profile_build_writes_facts(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"), projects=[Project(name="engine")])
    _configure_build(monkeypatch, facts)

    sources = _write_sources(tmp_path)
    profile_dir = tmp_path / "profile"
    out = profile_dir / "facts.json"

    result = runner.invoke(
        cli.app,
        [
            "profile",
            "build",
            "--sources",
            str(sources),
            "--dir",
            str(profile_dir),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.with_name("matrix.json").exists()
    assert "engine" in out.read_text(encoding="utf-8")


def test_profile_build_refuses_to_overwrite_without_refresh(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    _configure_build(monkeypatch, facts)

    sources = _write_sources(tmp_path)
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    out = profile_dir / "facts.json"
    out.write_text("{}", encoding="utf-8")  # pre-existing (simulating manual edits)

    result = runner.invoke(
        cli.app,
        ["profile", "build", "--sources", str(sources), "--dir", str(profile_dir), "--out", str(out)],
    )

    assert result.exit_code == 1
    assert out.read_text(encoding="utf-8") == "{}"  # not clobbered


def test_profile_build_refresh_overwrites(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    _configure_build(monkeypatch, facts)

    sources = _write_sources(tmp_path)
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    out = profile_dir / "facts.json"
    out.write_text("{}", encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["profile", "build", "--sources", str(sources), "--dir", str(profile_dir), "--out", str(out), "--refresh"],
    )

    assert result.exit_code == 0, result.output
    assert "Ada" in out.read_text(encoding="utf-8")


def test_profile_add_sources_and_remove(tmp_path):
    doc = tmp_path / "resume.txt"
    doc.write_text("Ada", encoding="utf-8")
    profile_dir = tmp_path / "profile"
    added = runner.invoke(
        cli.app,
        ["profile", "add", str(doc), "--primary", "--dir", str(profile_dir)],
    )
    assert added.exit_code == 0, added.output
    listing = runner.invoke(
        cli.app, ["profile", "sources", "--dir", str(profile_dir)]
    )
    assert "resume.txt" in listing.output
    assert "primary" in listing.output
    assert "fragment:missing" in listing.output

    removed = runner.invoke(
        cli.app,
        ["profile", "remove", "resume.txt", "--dir", str(profile_dir)],
    )
    assert removed.exit_code == 0
    listing = runner.invoke(
        cli.app, ["profile", "sources", "--dir", str(profile_dir)]
    )
    assert "resume.txt" not in listing.output


def test_profile_build_rejects_cross_directory_output(tmp_path, monkeypatch):
    _configure_build(monkeypatch, ProfileFacts(contact=Contact(name="Ada")))
    result = runner.invoke(
        cli.app,
        [
            "profile",
            "build",
            "--dir",
            str(tmp_path / "profile"),
            "--out",
            str(tmp_path / "other" / "facts.json"),
        ],
    )
    assert result.exit_code == 1
    assert "--out must be <dir>/facts.json" in result.output


def test_profile_build_prints_report(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    report = BuildReport(
        doc_status={"resume-abc": "extracted"},
        conflicts=["date conflict"],
        inferred_added=["Mentorship"],
        warnings=["inference warning"],
    )
    _configure_build(monkeypatch, facts)
    monkeypatch.setattr(
        "resume_agent.profile.build.build_corpus_profile",
        lambda dir_, github_username, **kwargs: (facts, report),
    )
    profile_dir = tmp_path / "profile"
    doc = tmp_path / "resume.txt"
    doc.write_text("Ada", encoding="utf-8")
    runner.invoke(
        cli.app, ["profile", "add", str(doc), "--dir", str(profile_dir)]
    )
    result = runner.invoke(
        cli.app,
        ["profile", "build", "--dir", str(profile_dir), "--out", str(profile_dir / "facts.json")],
    )
    assert result.exit_code == 0, result.output
    assert "CONFLICT: date conflict" in result.output
    assert "inferred: Mentorship" in result.output
    assert "WARNING: inference warning" in result.output
