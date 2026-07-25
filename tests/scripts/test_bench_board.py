from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Job
from scripts.bench_board import bench, seed


def _engine(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'bench.db').as_posix()}")
    init_db(engine)
    return engine


def test_seed_uses_pipeline_statuses_and_production_criteria_shape(tmp_path):
    engine = _engine(tmp_path)
    try:
        with Session(engine) as session:
            seed(session, 12)
            jobs = session.exec(select(Job)).all()

        assert {job.status for job in jobs} == {
            "shortlisted",
            "raw",
            "approved",
            "tailored",
            "rendered",
            "rejected",
        }
        criteria = jobs[0].criteria_json or {}
        assert set(criteria["salary_range"]) >= {"minimum", "maximum", "currency"}
        assert set(criteria) >= {
            "must_have_skills",
            "nice_to_have_skills",
            "tech_stack",
            "remote_policy",
        }
        assert len(jobs[0].jd_text.encode("utf-8")) >= 5_500
    finally:
        engine.dispose()


def test_bench_reports_requested_page_and_payload_bytes(tmp_path):
    engine = _engine(tmp_path)
    try:
        with Session(engine) as session:
            seed(session, 60)

        result = bench(engine, "pipeline", repeat=1, page=2)

        assert result.board == "pipeline"
        assert result.page == 2
        assert result.total_bytes > result.jd_text_bytes > 0
        assert result.facets_bytes > 0
    finally:
        engine.dispose()
