from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.ingest import ingest_jobs, ingest_jobs_with_outcomes
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _raw(source, n, company, title, jd):
    return RawJob(source, f"https://{source}/{n}", company, title, "Remote", jd)


def test_ingest_jobs_inserts_and_counts_per_source():
    raws = [
        _raw("greenhouse", 1, "Acme", "Backend Engineer", "JD A"),
        _raw("adzuna", 2, "Beta", "Platform Engineer", "JD B"),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1, "adzuna": 1}
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert {j.source for j in rows} == {"greenhouse", "adzuna"}


def test_ingest_jobs_skips_empty_jd():
    with _session() as s:
        assert ingest_jobs(s, [_raw("adzuna", 1, "Acme", "Eng", "   ")]) == {}


def test_ingest_threads_posted_at():
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with _session() as s:
        ingest_jobs(
            s,
            [
                RawJob(
                    source="greenhouse",
                    url="u1",
                    company="Acme",
                    title="Eng",
                    location="Remote",
                    jd_text="hello",
                    posted_at=when,
                )
            ],
        )
        jobs = jobs_by_status(s, JobStatus.raw.value)
        assert len(jobs) == 1
        assert jobs[0].posted_at == when.replace(tzinfo=None)


def test_ingest_jobs_dedupes_same_posting_across_sources():
    raws = [
        RawJob(
            "greenhouse",
            "https://gh/1",
            "Acme Corp",
            "Senior Backend Engineer",
            "Remote",
            "Full canonical JD",
        ),
        RawJob(
            "adzuna",
            "https://adz/9",
            "acme corp",
            "Backend Engineer",
            "Remote",
            "Truncated JD...",
        ),
        RawJob(
            "linkedin",
            "https://li/7",
            "Acme Corp",
            "Sr. Backend Engineer",
            "Remote",
            "LinkedIn JD",
        ),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1}
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "greenhouse"
        assert rows[0].jd_text == "Full canonical JD"


def test_cross_run_upgrade_not_counted_as_new_add():
    # Run 1: aggregator claims the job.
    with _session() as s:
        summary1 = ingest_jobs_with_outcomes(s, [RawJob("adzuna", "http://adz/1", "Acme Corp",
                                                        "Backend Engineer", "Remote", "thin jd")])
        assert summary1.added == {"adzuna": 1}
        assert summary1.upgraded == {}

        # Run 2 (same session/db): the canonical Workday copy upgrades, is NOT a new add.
        summary2 = ingest_jobs_with_outcomes(s, [RawJob("workday", "http://wd/1", "Acme Corp",
                                                        "Senior Backend Engineer", "Remote",
                                                        "full canonical jd")])
        assert summary2.added == {}
        assert summary2.upgraded == {"workday": 1}
        assert ingest_jobs(s, [RawJob("workday", "http://wd/1", "Acme Corp",
                                      "Senior Backend Engineer", "Remote", "full canonical jd")]) == {}

        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "workday"
        assert rows[0].url == "http://wd/1"
        assert rows[0].jd_text == "full canonical jd"


def test_ingest_batch_commits_once():
    raws = [
        RawJob(
            source="greenhouse", url=None, company="Acme", title=f"Engineer {i}",
            location=None, jd_text=f"jd {i}",
        )
        for i in range(3)
    ]
    with _session() as session:
        commits = []
        original_commit = session.commit

        def counting_commit():
            commits.append(1)
            original_commit()

        session.commit = counting_commit  # type: ignore[method-assign]
        counts = ingest_jobs_with_outcomes(session, raws)
        session.commit = original_commit  # type: ignore[method-assign]
        assert counts.added == {"greenhouse": 3}
        assert len(commits) == 1


def test_ingest_dedupes_within_uncommitted_batch():
    raw = RawJob(
        source="greenhouse", url=None, company="Acme", title="Engineer",
        location=None, jd_text="same jd",
    )
    with _session() as session:
        counts = ingest_jobs_with_outcomes(session, [raw, raw])
        assert counts.added == {"greenhouse": 1}
        assert counts.skipped == {"greenhouse": 1}
