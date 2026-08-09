from pathlib import Path

import pytest
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.services import reset as reset_module
from resume_agent.services.reset import (
    ResetPaths,
    ResetScope,
    reset_workspace,
    scope_paths,
)
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    Notification,
    ResumeVersion,
    SkillSuggestion,
)


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as current:
        yield current


@pytest.fixture()
def paths(tmp_path: Path) -> ResetPaths:
    root = tmp_path / "workspace"
    built = ResetPaths.legacy(
        data_dir=root,
        output_dir=root / "output",
        runs_dir=root / "runs",
    )
    for directory in (
        built.output_dir,
        built.runs_dir,
        built.progress_dir,
        built.profile_dir / "fragments",
        built.profile_dir / "documents",
        built.scraper_recipes_dir,
        built.workday_facets_dir,
        built.taxonomy_file.parent,
    ):
        directory.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    (root / "secrets.env").write_text("ANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    return built


def _seed_pipeline(session: Session) -> None:
    job = Job(source="manual", company="Acme", title="Engineer", dedup_key="a|e")
    session.add(job)
    session.commit()
    assert job.id is not None

    version = ResumeVersion(job_id=job.id)
    session.add(version)
    session.commit()
    assert version.id is not None

    letter = CoverLetter(job_id=job.id, resume_version_id=version.id)
    session.add(letter)
    session.commit()
    assert letter.id is not None

    application = Application(
        job_id=job.id,
        resume_version_id=version.id,
        cover_letter_id=letter.id,
    )
    session.add(application)
    session.commit()
    assert application.id is not None

    session.add(
        Notification(
            application_id=application.id,
            kind="status",
            proposed_status="interview",
            evidence="e",
            message_id="m1",
        )
    )
    session.add(SkillSuggestion(kind="cluster", key="python"))
    session.commit()


def _seed_files(paths: ResetPaths) -> None:
    (paths.output_dir / "acme").mkdir()
    (paths.output_dir / "acme" / "resume.pdf").write_bytes(b"%PDF")
    (paths.runs_dir / "run.json").write_text("{}", encoding="utf-8")
    (paths.progress_dir / "pull.json").write_text("{}", encoding="utf-8")
    paths.connector_runs_file.write_text("{}", encoding="utf-8")
    (paths.profile_dir / "facts.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "matrix.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "sources.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "cluster_map.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "overrides.yaml").write_text("ban: []\n", encoding="utf-8")
    (paths.profile_dir / "future-note.txt").write_text("keep", encoding="utf-8")
    (paths.profile_dir / "fragments" / "resume.json").write_text("{}", encoding="utf-8")
    (paths.profile_dir / "documents" / "manifest.json").write_text(
        "[]", encoding="utf-8"
    )
    paths.taxonomy_file.write_text("{}", encoding="utf-8")
    (paths.taxonomy_file.parent / "taxonomy_state.json").write_text(
        "{}", encoding="utf-8"
    )
    (paths.taxonomy_file.parent / "skill_embeddings.json").write_text(
        "{}", encoding="utf-8"
    )
    (paths.taxonomy_file.parent / "generations").mkdir()
    (paths.taxonomy_file.parent / "generations" / "old.json").write_text(
        "{}", encoding="utf-8"
    )
    (paths.scraper_recipes_dir / "recipe.json").write_text("{}", encoding="utf-8")
    (paths.workday_facets_dir / "acme-ext.json").write_text("{}", encoding="utf-8")


def test_jobs_scope_truncates_pipeline_and_clears_exact_targets(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)

    report = reset_workspace(session, paths, ResetScope.jobs)

    assert report.rows_deleted == {
        "notifications": 1,
        "applications": 1,
        "cover_letters": 1,
        "resume_versions": 1,
        "skill_suggestions": 1,
        "jobs": 1,
    }
    assert report.areas_cleared == [
        "output",
        "runs",
        "progress",
        "connector_runs",
    ]
    assert report.failures == {}
    assert session.exec(select(Job)).first() is None
    assert list(paths.output_dir.iterdir()) == []
    assert list(paths.runs_dir.iterdir()) == []
    assert not paths.connector_runs_file.exists()
    assert (paths.profile_dir / "facts.json").exists()
    assert paths.taxonomy_file.exists()


def test_profile_scope_clears_current_corpus_layout_only(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)

    report = reset_workspace(session, paths, ResetScope.profile)

    assert report.rows_deleted == {"skill_suggestions": 1}
    assert report.areas_cleared == ["profile", "taxonomy"]
    assert session.exec(select(Job)).first() is not None
    assert session.exec(select(Application)).first() is not None
    assert session.exec(select(Notification)).first() is not None
    for name in ("facts.json", "matrix.json", "cluster_map.json"):
        assert not (paths.profile_dir / name).exists()
    assert (paths.profile_dir / "sources.json").exists()
    assert (paths.profile_dir / "overrides.yaml").exists()
    assert (paths.profile_dir / "future-note.txt").read_text(encoding="utf-8") == "keep"
    assert not (paths.profile_dir / "sources").exists()
    assert paths.connector_runs_file.exists()
    assert not paths.taxonomy_file.exists()
    assert not (paths.taxonomy_file.parent / "taxonomy_state.json").exists()
    assert not (paths.taxonomy_file.parent / "skill_embeddings.json").exists()
    generations = paths.taxonomy_file.parent / "generations"
    assert generations.is_dir() and list(generations.iterdir()) == []
    fragments = paths.profile_dir / "fragments"
    assert fragments.is_dir() and list(fragments.iterdir()) == []
    assert (paths.profile_dir / "documents" / "manifest.json").read_text(
        encoding="utf-8"
    ) == "[]"
    assert (paths.output_dir / "acme" / "resume.pdf").exists()


def test_all_scope_preserves_config_secrets_and_overrides(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)

    report = reset_workspace(session, paths, ResetScope.all)

    assert sum(report.rows_deleted.values()) == 6
    assert report.areas_cleared == [
        "output",
        "runs",
        "progress",
        "connector_runs",
        "profile",
        "taxonomy",
        "scraper_recipes",
        "workday_facets",
    ]
    root = paths.profile_dir.parent
    assert (root / "config" / "search.yaml").read_text(
        encoding="utf-8"
    ) == "titles: []\n"
    assert (root / "secrets.env").exists()
    assert (paths.profile_dir / "overrides.yaml").exists()
    assert (paths.profile_dir / "sources.json").exists()
    assert (paths.profile_dir / "documents" / "manifest.json").exists()
    assert list(paths.scraper_recipes_dir.iterdir()) == []
    assert list(paths.workday_facets_dir.iterdir()) == []


def test_second_run_is_idempotent(session, paths):
    _seed_pipeline(session)
    _seed_files(paths)
    reset_workspace(session, paths, ResetScope.all)

    report = reset_workspace(session, paths, ResetScope.all)

    assert sum(report.rows_deleted.values()) == 0
    assert report.failures == {}


def test_file_failure_is_reported_and_failed_area_is_not_cleared(
    session, paths, monkeypatch
):
    _seed_pipeline(session)
    _seed_files(paths)

    def explode(_path):
        raise OSError("locked by another process")

    monkeypatch.setattr(reset_module.shutil, "rmtree", explode)
    report = reset_workspace(session, paths, ResetScope.jobs)

    assert str(paths.output_dir / "acme") in report.failures
    assert "output" not in report.areas_cleared
    assert session.exec(select(Job)).first() is None


def test_missing_directory_recreation_failure_is_reported(session, paths, monkeypatch):
    _seed_pipeline(session)
    paths.runs_dir.rmdir()
    original_mkdir = Path.mkdir

    def fail_runs_mkdir(self, *args, **kwargs):
        if self == paths.runs_dir:
            raise OSError("read only")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_runs_mkdir)
    report = reset_workspace(session, paths, ResetScope.jobs)

    assert report.failures[str(paths.runs_dir)] == "read only"
    assert "runs" not in report.areas_cleared


def test_directory_root_symlink_is_unlinked_not_traversed(session, paths):
    outside = paths.output_dir.parent / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    paths.output_dir.rmdir()
    try:
        paths.output_dir.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    report = reset_workspace(session, paths, ResetScope.jobs)

    assert report.failures == {}
    assert marker.read_text(encoding="utf-8") == "keep"
    assert paths.output_dir.is_dir()
    assert not paths.output_dir.is_symlink()
    assert list(paths.output_dir.iterdir()) == []


def test_db_commit_failure_rolls_back_before_file_phase(session, paths, monkeypatch):
    _seed_pipeline(session)
    _seed_files(paths)
    rolled_back = False
    original_rollback = session.rollback

    def fail_commit():
        raise RuntimeError("commit failed")

    def track_rollback():
        nonlocal rolled_back
        rolled_back = True
        original_rollback()

    monkeypatch.setattr(session, "commit", fail_commit)
    monkeypatch.setattr(session, "rollback", track_rollback)

    with pytest.raises(RuntimeError, match="commit failed"):
        reset_workspace(session, paths, ResetScope.jobs)

    assert rolled_back is True
    assert session.exec(select(Job)).first() is not None
    assert (paths.output_dir / "acme" / "resume.pdf").exists()


def test_scope_paths_lists_every_destructive_target(paths):
    assert scope_paths(paths, ResetScope.profile) == (
        paths.profile_dir / "fragments",
        paths.profile_dir / "facts.json",
        paths.profile_dir / "matrix.json",
        paths.profile_dir / "cluster_map.json",
        paths.taxonomy_file,
        paths.taxonomy_file.parent / "taxonomy_state.json",
        paths.taxonomy_file.parent / "skill_embeddings.json",
        paths.taxonomy_file.parent / "generations",
    )
