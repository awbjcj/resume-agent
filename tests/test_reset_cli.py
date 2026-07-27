from pathlib import Path

from sqlmodel import Session, select
from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Job

runner = CliRunner()


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


def _seed(db_url: str) -> None:
    engine = make_engine(db_url)
    init_db(engine)
    with Session(engine) as session:
        session.add(Job(source="manual", company="Acme", title="Engineer"))
        session.commit()


def _job_count(db_url: str) -> int:
    with Session(make_engine(db_url)) as session:
        return len(session.exec(select(Job)).all())


def test_reset_rejects_unknown_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["reset", "--scope", "bogus", "--yes"])

    assert result.exit_code != 0
    assert "scope must be jobs, profile, or all" in result.output


def test_reset_aborts_on_wrong_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = _db_url(tmp_path)
    _seed(db_url)

    result = runner.invoke(
        app,
        ["reset", "--scope", "jobs", "--db-url", db_url],
        input="nope\n",
    )

    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert _job_count(db_url) == 1


def test_reset_preview_lists_rows_and_every_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = _db_url(tmp_path)
    _seed(db_url)

    result = runner.invoke(
        app,
        ["reset", "--scope", "profile", "--db-url", db_url],
        input="profile\n",
    )

    assert result.exit_code == 0, result.output
    assert "skill_suggestions: 0 rows" in result.output
    assert str(tmp_path / "data" / "profile" / "documents") not in result.output
    assert str(tmp_path / "data" / "profile" / "sources.json") not in result.output
    assert str(tmp_path / "data" / "profile" / "facts.json") in result.output
    assert str(tmp_path / "data" / "taxonomy" / "skill_groups.json") in result.output


def test_reset_with_yes_skips_prompt_and_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_url = _db_url(tmp_path)
    _seed(db_url)
    output = tmp_path / "output"
    output.mkdir()
    (output / "resume.pdf").write_bytes(b"%PDF")

    result = runner.invoke(
        app,
        ["reset", "--scope", "jobs", "--yes", "--db-url", db_url],
    )

    assert result.exit_code == 0, result.output
    assert "Deleted 1 rows" in result.output
    assert "Cleared: output, runs, progress, connector_runs" in result.output
    assert "Type jobs to confirm" not in result.output
    assert list(output.iterdir()) == []
    assert _job_count(db_url) == 0
