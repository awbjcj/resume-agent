from sqlmodel import select

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.services.company_fix import fix_company_names
from resume_agent.tracking.dedup import compute_dedup_key
from resume_agent.tracking.tables import Job, JobStatus

CONFIG = ConnectorsConfig.model_validate(
    {
        "greenhouse": {
            "boards": [{"token": "acmecorp", "company": "Acme Corp"}]
        }
    }
)


def _job(company, url, **overrides):
    values = dict(
        source="greenhouse",
        url=url,
        company=company,
        title="Platform Engineer",
        location="Austin",
        jd_text="Build systems",
        status=JobStatus.raw.value,
        dedup_key=compute_dedup_key(company, "Platform Engineer"),
    )
    values.update(overrides)
    return Job(**values)


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_fix_company_names_renames_literal_case_insensitively():
    with get_session(_engine()) as session:
        session.add(_job("AcmeCorp", "https://x.test/1"))
        session.commit()
        report = fix_company_names(session, CONFIG)
        row = session.exec(select(Job)).one()
    assert report.renamed == {"acmecorp": 1}
    assert row.company == "Acme Corp"
    assert row.dedup_key == compute_dedup_key("Acme Corp", row.title)


def test_fix_company_names_reports_collision_without_merging():
    with get_session(_engine()) as session:
        session.add(_job("acmecorp", "https://x.test/1"))
        session.add(
            _job(
                "Acme Corp",
                "https://x.test/2",
                jd_text="Other posting",
            )
        )
        session.commit()
        report = fix_company_names(session, CONFIG)
        rows = session.exec(select(Job)).all()
    assert len(report.conflicts) == 1
    assert any(row.company == "acmecorp" for row in rows)


def test_fix_company_names_dry_run_does_not_write():
    with get_session(_engine()) as session:
        session.add(_job("acmecorp", "https://x.test/1"))
        session.commit()
        report = fix_company_names(session, CONFIG, dry_run=True)
        row = session.exec(select(Job)).one()
    assert report.renamed == {"acmecorp": 1}
    assert row.company == "acmecorp"
