from resume_tailor_harness.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.queries import pipeline_rows, shortlist_rows, triage_rows
from resume_tailor_harness.tracking.tables import Job, JobStatus


def test_board_rows_and_schemas_expose_posting_url():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(
            Job(
                source="greenhouse",
                jd_text="We build things.",
                url="https://boards.greenhouse.io/acme/jobs/1",
                company="Acme",
                title="Platform Engineer",
                status=JobStatus.raw.value,
            )
        )
        session.commit()
        triage_url = triage_rows(session)[0].url
        pipeline_url = pipeline_rows(session)[0].url
        assert triage_url is not None and triage_url.endswith("/jobs/1")
        assert pipeline_url is not None and pipeline_url.endswith("/jobs/1")
        # A raw job is not shortlisted, but the DTO contract is still covered below.
        assert shortlist_rows(session) == []

    for schema in (ShortlistItem, TriageItem, PipelineItem):
        assert "url" in schema.model_fields
