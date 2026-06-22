from pathlib import Path

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services import rendering, tailoring
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_tailor_loads_config_and_calls_tailor_jobs(monkeypatch):
    captured = {}

    def fake_tailor_jobs(session, targets, facts, config, tailor, reviewers, reviser, reporter=None):
        captured["targets"] = [j.id for j in targets]
        return {targets[0].id: ["v1"]}

    monkeypatch.setattr(tailoring, "tailor_jobs", fake_tailor_jobs)
    monkeypatch.setattr(
        tailoring, "load_review_config",
        lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring, "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(tailor="t", reviser="r", reviewers={}),  # type: ignore[arg-type]
    )
    with _session() as session:
        job = Job(source="manual", jd_text="x", status=JobStatus.approved.value)
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        result = tailoring.tailor(session, job_ids=[job.id])
    assert captured["targets"] == [job.id]
    assert result


def test_render_resume_version_returns_path(monkeypatch, tmp_path):
    def fake_render_version(session, version_id, config, render_fn=None):
        return tmp_path / "out.pdf"

    monkeypatch.setattr(rendering, "render_version", fake_render_version)
    monkeypatch.setattr(rendering, "_load_config", lambda p: object())
    with _session() as session:
        job = Job(source="manual", jd_text="x")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        v = ResumeVersion(job_id=job.id, round=0)
        session.add(v)
        session.commit()
        session.refresh(v)
        assert v.id is not None
        path = rendering.render_resume_version(session, v.id)
    assert path is not None
    assert Path(path).name == "out.pdf"
