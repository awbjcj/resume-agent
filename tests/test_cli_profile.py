from typer.testing import CliRunner

from resume_tailor_harness.models.profile import (
    Bullet,
    Contact,
    Experience,
    Project,
    ProfileFacts,
)
from resume_tailor_harness.profile.build import BuildReport
from resume_tailor_harness.profile.store import save_facts
from resume_tailor_harness import cli

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
        "resume_tailor_harness.profile.build.build_corpus_profile",
        lambda dir_, github_username, **kwargs: (facts, BuildReport()),
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type("S", (), {"cheap_model": "cheap", "mid_model": "mid"})(),
    )
    monkeypatch.setattr(cli, "resolve_api_key", lambda model: "sk-test")
    monkeypatch.setattr(
        "resume_tailor_harness.profile.merge.build_bullet_dedup_agent", lambda: object()
    )
    monkeypatch.setattr(
        "resume_tailor_harness.profile.inference.build_inference_agent", lambda: object()
    )
    monkeypatch.setattr(
        "resume_tailor_harness.profile.synthesis.build_synthesis_agent", lambda: object()
    )
    monkeypatch.setattr(
        "resume_tailor_harness.profile.synthesis.build_entailment_agent", lambda: object()
    )
    monkeypatch.setattr(
        "resume_tailor_harness.profile.project_extractor.build_project_extractor_agent",
        lambda: object(),
    )
    monkeypatch.setattr(
        "resume_tailor_harness.taxonomy.groups.build_group_classifier_agent", lambda: object()
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
        [
            "profile",
            "build",
            "--sources",
            str(sources),
            "--dir",
            str(profile_dir),
            "--out",
            str(out),
            "--refresh",
        ],
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
    listing = runner.invoke(cli.app, ["profile", "sources", "--dir", str(profile_dir)])
    assert "resume.txt" in listing.output
    assert "primary" in listing.output
    assert "fragment:missing" in listing.output

    removed = runner.invoke(
        cli.app,
        ["profile", "remove", "resume.txt", "--dir", str(profile_dir)],
    )
    assert removed.exit_code == 0
    listing = runner.invoke(cli.app, ["profile", "sources", "--dir", str(profile_dir)])
    assert "resume.txt" not in listing.output


def test_profile_add_mode_flag_and_sources_listing(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("Shipped things", encoding="utf-8")
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    profile_dir = tmp_path / "profile"

    assert (
        runner.invoke(
            cli.app, ["profile", "add", str(resume), "--dir", str(profile_dir)]
        ).exit_code
        == 0
    )
    result = runner.invoke(
        cli.app,
        ["profile", "add", str(doc), "--dir", str(profile_dir), "--mode", "synthesis"],
    )
    assert result.exit_code == 0, result.output
    assert "synthesis" in result.output

    listing = runner.invoke(cli.app, ["profile", "sources", "--dir", str(profile_dir)])
    assert "mode:synthesis" in listing.output


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
        "resume_tailor_harness.profile.build.build_corpus_profile",
        lambda dir_, github_username, **kwargs: (facts, report),
    )
    profile_dir = tmp_path / "profile"
    doc = tmp_path / "resume.txt"
    doc.write_text("Ada", encoding="utf-8")
    runner.invoke(cli.app, ["profile", "add", str(doc), "--dir", str(profile_dir)])
    result = runner.invoke(
        cli.app,
        [
            "profile",
            "build",
            "--dir",
            str(profile_dir),
            "--out",
            str(profile_dir / "facts.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "CONFLICT: date conflict" in result.output
    assert "inferred: Mentorship" in result.output
    assert "WARNING: inference warning" in result.output


def test_profile_build_delegates_to_the_service(tmp_path, monkeypatch):
    calls = {}

    def fake_run(
        reporter,
        *,
        profile_dir,
        github_username,
        facts_out,
        github_allow,
        github_deny,
        github_limit,
    ):
        calls["reporter"] = reporter
        calls["github_username"] = github_username
        calls["facts_out"] = str(facts_out)
        calls["github_options"] = (github_allow, github_deny, github_limit)
        return {
            "experiences": 0,
            "projects": 0,
            "matrixRows": 0,
            "docStatus": {},
            "conflicts": [],
            "anchorDecisions": [],
            "verificationDrops": [],
            "inferred": [],
            "warnings": [],
        }

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type("S", (), {"cheap_model": "cheap", "mid_model": "mid"})(),
    )
    monkeypatch.setattr(cli, "resolve_api_key", lambda model: "sk-test")
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_build.run_corpus_build", fake_run
    )

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
    assert calls["reporter"] is None
    assert calls["github_username"] == "ada"
    assert calls["facts_out"] == str(out)
    assert calls["github_options"] == ((), (), 20)


def test_profile_add_note_url_and_sync_github_commands(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    assert (
        runner.invoke(
            cli.app, ["profile", "add", str(resume), "--dir", str(profile_dir)]
        ).exit_code
        == 0
    )

    note = runner.invoke(
        cli.app,
        [
            "profile",
            "add-note",
            "On-call",
            "Led the rotation.",
            "--dir",
            str(profile_dir),
        ],
    )
    assert note.exit_code == 0, note.output
    assert "note--on-call.md" in note.output

    monkeypatch.setattr(
        "resume_tailor_harness.profile.intake.add_url_source",
        lambda directory, url: __import__(
            "resume_tailor_harness.profile.intake", fromlist=["add_note_source"]
        ).add_note_source(directory, "fetched", f"content of {url}"),
    )
    added_url = runner.invoke(
        cli.app,
        ["profile", "add-url", "https://example.com", "--dir", str(profile_dir)],
    )
    assert added_url.exit_code == 0, added_url.output

    from resume_tailor_harness.profile.github_harvest import HarvestReport

    monkeypatch.setattr(
        "resume_tailor_harness.profile.github_harvest.sync_github_sources",
        lambda *_args, **_kwargs: HarvestReport(written=["github--repo.md"]),
    )
    missing = runner.invoke(
        cli.app,
        [
            "profile",
            "sync-github",
            "--sources",
            str(tmp_path / "missing.yaml"),
            "--dir",
            str(profile_dir),
        ],
    )
    assert missing.exit_code == 1
    synced = runner.invoke(
        cli.app,
        [
            "profile",
            "sync-github",
            "--username",
            "ada",
            "--sources",
            str(tmp_path / "missing.yaml"),
            "--dir",
            str(profile_dir),
        ],
    )
    assert synced.exit_code == 0, synced.output
    assert "written:1" in synced.output


def test_profile_depth_reports_supply_and_aspect_gaps(tmp_path):
    facts_path = tmp_path / "profile" / "facts.json"
    save_facts(
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="e1",
                    company="Acme",
                    title="Engineer",
                    bullets=[Bullet(id="b1", text="Built it", aspect="technical")],
                )
            ],
        ),
        facts_path,
    )

    result = runner.invoke(cli.app, ["profile", "depth", "--facts", str(facts_path)])

    assert result.exit_code == 0, result.output
    assert "GAP Acme — Engineer (experience): 1/10 bullets" in result.output
    assert "missing aspects:" in result.output
    assert "Run `profile coach`" in result.output
