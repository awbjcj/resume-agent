from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.known_jobs import build_known_index, make_skip_seen
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus, utcnow


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _persist(
    session,
    source,
    url=None,
    company="Acme",
    title="Backend Engineer",
    location="Remote",
    *,
    archived=False,
):
    save_job(
        session,
        Job(
            source=source,
            url=url,
            company=company,
            title=title,
            location=location,
            jd_text="jd",
            dedup_key=compute_dedup_key(company, title),
            status=JobStatus.raw.value,
            archived_at=utcnow() if archived else None,
        ),
    )


def _raw(source, url=None, company="Acme", title="Backend Engineer", location="Remote"):
    return RawJob(source, url, company, title, location, jd_text="")


def test_skip_seen_matches_url_or_dedup_key_with_same_location():
    with _session() as session:
        _persist(session, "greenhouse", " https://gh/1 ")
        skip = make_skip_seen(build_known_index(session))

        assert skip(_raw("greenhouse", "https://gh/1")) is True
        assert skip(_raw("lever", None)) is True


def test_skip_seen_does_not_collapse_different_locations():
    with _session() as session:
        _persist(session, "workday", None, "GM", "Software Engineer", "Austin, TX")
        skip = make_skip_seen(build_known_index(session))

        assert (
            skip(_raw("workday", None, "GM", "Software Engineer", "Detroit, MI"))
            is False
        )


def test_skip_seen_never_blocks_a_higher_tier_upgrade():
    with _session() as session:
        _persist(session, "adzuna", "https://x/1")
        skip = make_skip_seen(build_known_index(session))

        assert skip(_raw("greenhouse", "https://x/1")) is False


def test_skip_seen_uses_best_source_when_multiple_rows_share_an_identity():
    with _session() as session:
        _persist(session, "greenhouse", "https://direct/1")
        _persist(session, "adzuna", "https://aggregate/1")
        skip = make_skip_seen(build_known_index(session))

        assert skip(_raw("lever", None)) is True


def test_archived_rows_are_not_known():
    with _session() as session:
        _persist(session, "greenhouse", "https://gh/1", archived=True)
        skip = make_skip_seen(build_known_index(session))

        assert skip(_raw("greenhouse", "https://gh/1")) is False
