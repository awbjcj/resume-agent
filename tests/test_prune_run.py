from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.prune_config import PruneConfig
from resume_agent.tracking.repository import (
    get_job,
    prune_preview,
    prune_run,
    save_application,
    save_job,
)
from resume_agent.tracking.tables import Application, Job, JobStatus

NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_prune_run_archives_junk_expires_old_and_skips_progress():
    cfg = PruneConfig()
    with _session() as s:
        rejected = save_job(
            s, Job(source="m", jd_text="a", status=JobStatus.rejected.value)
        )
        protected = save_job(
            s, Job(source="m", jd_text="b", status=JobStatus.rejected.value)
        )
        # ADR-0013: protection comes from real investment, not a bare row —
        # an empty `ready` application no longer shields a job from pruning.
        save_application(
            s, Application(job_id=_require_id(protected.id), status="submitted")
        )
        old_archived = save_job(
            s,
            Job(
                source="m",
                jd_text="c",
                status=JobStatus.raw.value,
                archived_at=NOW - timedelta(days=45),
            ),
        )

        preview = prune_preview(s, cfg, now=NOW)
        assert preview.archived == 1 and preview.expired == 1 and preview.skipped == 1
        assert preview.rejected == 1 and preview.low_fit == 0 and preview.stale == 0
        # Preview must not mutate.
        rejected_before = get_job(s, _require_id(rejected.id))
        assert rejected_before is not None
        assert rejected_before.archived_at is None

        report = prune_run(s, cfg, now=NOW)
        assert report.archived == 1 and report.expired == 1 and report.skipped == 1
        assert report.rejected == 1 and report.low_fit == 0 and report.stale == 0
        rejected_after = get_job(s, _require_id(rejected.id))
        assert rejected_after is not None
        assert rejected_after.archived_at is not None
        assert get_job(s, _require_id(old_archived.id)) is None  # expired
        protected_after = get_job(s, _require_id(protected.id))
        assert protected_after is not None  # progress kept
        assert protected_after.archived_at is None


def test_prune_archives_share_one_commit_and_timestamp():
    from sqlmodel import select

    cfg = PruneConfig(enable_low_fit=False, enable_stale=False)
    with _session() as session:
        for i in range(3):
            session.add(
                Job(
                    source="greenhouse",
                    company=f"Junk{i}",
                    title="Engineer",
                    jd_text=f"jd {i}",
                    status=JobStatus.rejected.value,
                )
            )
        session.commit()

        commits = []
        original_commit = session.commit

        def counting_commit():
            commits.append(1)
            original_commit()

        session.commit = counting_commit  # type: ignore[method-assign]
        try:
            prune_run(session, cfg)
        finally:
            session.commit = original_commit  # type: ignore[method-assign]

        assert len(commits) <= 2
        stamps = {
            job.archived_at
            for job in session.exec(select(Job)).all()
            if job.archived_at
        }
        assert len(stamps) <= 1
