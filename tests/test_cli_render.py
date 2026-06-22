from pathlib import Path

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion

runner = CliRunner()


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _seed(db_url) -> int:
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = Job(source="manual", jd_text="jd", company="Acme", title="Eng",
                  status=JobStatus.tailored.value)
        s.add(job)
        s.commit()
        s.refresh(job)
        v = ResumeVersion(job_id=_require_id(job.id), round=1, content_json={"contact": {"name": "Ada"}})
        s.add(v)
        s.commit()
        s.refresh(v)
        return _require_id(v.id)


def test_render_command(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    version_id = _seed(db_url)

    def fake_render(session, vid, render_path=None):
        assert vid == version_id
        return Path("output/fake.pdf")

    monkeypatch.setattr(cli, "render_resume_version", fake_render)

    result = runner.invoke(cli.app, ["render", str(version_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "output/fake.pdf" in result.output.replace("\\", "/")
