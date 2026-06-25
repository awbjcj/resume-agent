from sqlmodel import select

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.prune import prune
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_prune_dry_run_counts_without_writing(tmp_path):
    cfg = tmp_path / "prune.yaml"
    cfg.write_text("fit_threshold: 40\nstale_days: 30\nretention_days: 90\n", encoding="utf-8")
    with _session() as session:
        session.add(Job(source="manual", jd_text="x", status=JobStatus.rejected.value))
        session.commit()
        report = prune(session, dry_run=True, config_path=str(cfg))
        remaining = session.exec(select(Job)).all()
    assert report.archived >= 1
    assert all(j.archived_at is None for j in remaining)


def test_prune_override_beats_config(tmp_path):
    cfg = tmp_path / "prune.yaml"
    cfg.write_text("fit_threshold: 40\nstale_days: 30\nretention_days: 90\n", encoding="utf-8")
    with _session() as session:
        session.add(
            Job(source="manual", jd_text="x", status=JobStatus.shortlisted.value, fit_score=50)
        )
        session.commit()
        low = prune(session, dry_run=True, fit_threshold=60, config_path=str(cfg))
        base = prune(session, dry_run=True, config_path=str(cfg))
    assert low.low_fit == 1
    assert base.low_fit == 0
