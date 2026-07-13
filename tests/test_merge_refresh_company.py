from sqlmodel import select

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import IngestOutcome, save_or_upgrade
from resume_agent.discovery.merge import IncomingJob, RefreshCompany, Skip, decide
from resume_agent.tracking.dedup import compute_dedup_key
from resume_agent.tracking.tables import Job, JobStatus


def _existing(company="acmecorp", **overrides):
    values = dict(
        source="greenhouse",
        url="https://x.test/1",
        company=company,
        title="Platform Engineer",
        location="Austin",
        jd_text="Build systems",
        status=JobStatus.raw.value,
        dedup_key=compute_dedup_key(company, "Platform Engineer"),
    )
    values.update(overrides)
    return Job(**values)


def _incoming(**overrides):
    values = dict(
        source="greenhouse",
        url="https://x.test/1",
        company="Acme Corp",
        stale_company="acmecorp",
        title="Platform Engineer",
        location="Austin",
        jd_text="Build systems",
    )
    values.update(overrides)
    return IncomingJob.clean(**values)


def test_decide_refreshes_company_when_stale_matches():
    action = decide(_existing(), _incoming())
    assert isinstance(action, RefreshCompany)
    assert action.company == "Acme Corp"


def test_decide_skips_without_stale_company():
    assert isinstance(decide(_existing(), _incoming(stale_company=None)), Skip)


def test_save_refreshes_company_and_key_atomically():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(_existing())
        session.commit()
        job, outcome = save_or_upgrade(
            session,
            source="greenhouse",
            url="https://x.test/1",
            company="Acme Corp",
            stale_company="acmecorp",
            title="Platform Engineer",
            location="Austin",
            jd_text="Build systems",
        )
    assert outcome is IngestOutcome.upgraded
    assert job is not None and job.company == "Acme Corp"
    assert job.dedup_key == compute_dedup_key("Acme Corp", "Platform Engineer")


def test_save_skips_rename_that_collides_with_live_row():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(_existing())
        session.add(
            _existing(
                company="Acme Corp",
                url="https://x.test/2",
                jd_text="Other text",
            )
        )
        session.commit()
        _, outcome = save_or_upgrade(
            session,
            source="greenhouse",
            url="https://x.test/1",
            company="Acme Corp",
            stale_company="acmecorp",
            title="Platform Engineer",
            location="Austin, TX",
            jd_text="Build systems",
        )
        stale = session.exec(select(Job).where(Job.company == "acmecorp")).all()
    assert outcome is IngestOutcome.skipped
    assert len(stale) == 1
