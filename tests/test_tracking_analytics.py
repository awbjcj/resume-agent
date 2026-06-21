from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.analytics import fit_band_stats, source_stats
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, ApplicationStatus, Job


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(session, source, fit, status):
    job = save_job(session, Job(source=source, company="C", title="T", fit_score=fit, status="rendered"))
    assert job.id is not None
    save_application(session, Application(job_id=job.id, status=status))


def test_source_stats_counts_and_rates():
    with _session() as session:
        _seed(session, "greenhouse", 85, ApplicationStatus.interview.value)
        _seed(session, "greenhouse", 70, ApplicationStatus.submitted.value)
        _seed(session, "adzuna", 90, ApplicationStatus.rejected.value)
        _seed(session, "adzuna", 60, ApplicationStatus.ready.value)

        stats = {cohort.label: cohort for cohort in source_stats(session)}
        assert stats["greenhouse"].applications == 2
        assert stats["greenhouse"].interviews == 1
        assert stats["greenhouse"].interview_rate == 50
        assert stats["adzuna"].applications == 1
        assert stats["adzuna"].responses == 1
        assert stats["adzuna"].offers == 0


def test_fit_band_stats_groups_by_band():
    with _session() as session:
        _seed(session, "greenhouse", 85, ApplicationStatus.offer.value)
        _seed(session, "adzuna", 90, ApplicationStatus.interview.value)
        _seed(session, "remoteok", 70, ApplicationStatus.submitted.value)

        bands = {cohort.label: cohort for cohort in fit_band_stats(session)}
        assert bands["80-100"].applications == 2
        assert bands["80-100"].offers == 1
        assert bands["80-100"].offer_rate == 50
        assert bands["60-79"].applications == 1


def test_analytics_excludes_archived_jobs():
    from resume_agent.tracking.repository import archive_job

    with _session() as session:
        _seed(session, "greenhouse", 85, ApplicationStatus.submitted.value)
        hidden = save_job(session, Job(source="adzuna", company="C", title="T",
                                       fit_score=90, status="rendered"))
        assert hidden.id is not None
        save_application(session, Application(job_id=hidden.id,
                                             status=ApplicationStatus.interview.value))
        archive_job(session, hidden.id)

        assert [stat.label for stat in source_stats(session)] == ["greenhouse"]
        bands = {stat.label: stat for stat in fit_band_stats(session)}
        assert bands["80-100"].applications == 1


def test_empty_history_returns_empty():
    with _session() as session:
        assert source_stats(session) == []
        assert fit_band_stats(session) == []
