from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services.jobs_import import import_jobs_file

CSV = (
    "title,company,url,location,jd_text,posted_at\n"
    "Platform Engineer,Acme,https://a.test/1,Austin,Build systems,2026-07-01\n"
    "Missing JD,Beta,https://b.test/1,Remote,,\n"
)
JSON = b'[{"title":"Data Engineer","company":"Beta","url":"https://b.test/2","jd_text":"Build data systems"}]'


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_csv_import_adds_and_rejects_blank_jd():
    with get_session(_engine()) as session:
        report = import_jobs_file(session, "jobs.csv", CSV.encode("utf-8"))
    assert report.added == 1
    assert report.errors == [
        (
            2,
            "jd_text is required; use the URL-list import for postings you only have links for",
        )
    ]


def test_json_import_adds_and_deduplicates():
    with get_session(_engine()) as session:
        first = import_jobs_file(session, "jobs.json", JSON)
        second = import_jobs_file(session, "jobs.json", JSON)
    assert first.added == 1
    assert second.skipped == 1


def test_import_respects_active_job_limit_across_rows():
    rows = b'[{"jd_text":"first"},{"jd_text":"second"}]'
    with get_session(_engine()) as session:
        report = import_jobs_file(session, "jobs.json", rows, max_active_jobs=1)
    assert report.added == 1
    assert report.skipped == 1
