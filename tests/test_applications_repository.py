from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.tracking.repository import (
    application_for_job,
    applications_by_status,
    best_resume_version,
    get_application,
    latest_resume_version,
    latest_rendered_resume_version,
    pick_best,
    save_application,
    save_resume_version,
    update_application_status,
)
from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_application_crud_and_lookup():
    with _session() as s:
        app = save_application(
            s, Application(job_id=1, status=ApplicationStatus.ready.value)
        )
        app_id = _require_id(app.id)
        loaded = get_application(s, app_id)
        assert loaded is not None
        assert loaded.job_id == 1
        by_job = application_for_job(s, 1)
        assert by_job is not None
        assert by_job.id == app.id
        assert application_for_job(s, 999) is None
        assert [
            a.id for a in applications_by_status(s, ApplicationStatus.ready.value)
        ] == [app.id]


def test_update_application_status_and_notes():
    with _session() as s:
        app = save_application(
            s, Application(job_id=1, status=ApplicationStatus.ready.value)
        )
        updated = update_application_status(
            s,
            _require_id(app.id),
            ApplicationStatus.submitted.value,
            notes="applied via portal",
        )
        assert updated is not None
        assert updated.status == ApplicationStatus.submitted.value
        assert updated.notes == "applied via portal"


def test_submitted_status_sets_submitted_at_once():
    with _session() as s:
        created = save_application(
            s, Application(job_id=1, status=ApplicationStatus.submitted.value)
        )
        assert created.submitted_at is not None

        ready = save_application(
            s, Application(job_id=2, status=ApplicationStatus.ready.value)
        )
        assert ready.submitted_at is None

        submitted = update_application_status(
            s, _require_id(ready.id), ApplicationStatus.submitted.value
        )
        assert submitted is not None
        assert submitted.submitted_at is not None

        first_submitted_at = submitted.submitted_at
        updated = update_application_status(
            s,
            _require_id(submitted.id),
            ApplicationStatus.submitted.value,
            notes="done",
        )
        assert updated is not None
        assert updated.submitted_at == first_submitted_at


def test_latest_resume_version_picks_highest_round():
    with _session() as s:
        save_resume_version(s, ResumeVersion(job_id=7, round=1, content_json={"a": 1}))
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        latest = latest_resume_version(s, 7)
        assert latest is not None
        assert latest.round == 2
        assert latest_resume_version(s, 999) is None


def test_latest_rendered_resume_version_picks_highest_round_with_pdf():
    with _session() as s:
        save_resume_version(
            s,
            ResumeVersion(job_id=7, round=1, content_json={"a": 1}, pdf_path="one.pdf"),
        )
        save_resume_version(s, ResumeVersion(job_id=7, round=2, content_json={"a": 2}))
        save_resume_version(
            s,
            ResumeVersion(
                job_id=7, round=3, content_json={"a": 3}, pdf_path="three.pdf"
            ),
        )
        latest = latest_rendered_resume_version(s, 7)
        assert latest is not None
        assert latest.round == 3
        assert latest.pdf_path == "three.pdf"


def _rv(
    round_num: int, score: int | None, passed: bool, version_id: int | None
) -> ResumeVersion:
    return ResumeVersion(
        id=version_id,
        job_id=7,
        round=round_num,
        review_score=score,
        fact_check_passed=passed,
    )


def test_pick_best_prefers_highest_scoring_gate_passing_round():
    best = pick_best([_rv(1, 90, True, 1), _rv(2, 82, True, 2)])
    assert best.version is not None and best.version.id == 1
    assert best.no_clean_round is False
    assert best.regressed is True


def test_pick_best_tie_breaks_by_latest_round_then_id():
    first = pick_best([_rv(1, 88, True, 1), _rv(2, 88, True, 2)]).version
    second = pick_best([_rv(2, 88, True, 1), _rv(2, 88, True, 2)]).version
    assert first is not None and first.id == 2
    assert second is not None and second.id == 2


def test_pick_best_ranks_missing_score_below_zero():
    best = pick_best([_rv(2, None, True, 2), _rv(1, 0, True, 1)])
    assert best.version is not None and best.version.id == 1


def test_pick_best_detects_regression_for_unpersisted_rows():
    best = pick_best([_rv(1, 90, True, None), _rv(2, 80, True, None)])
    assert best.version is not None and best.version.round == 1
    assert best.regressed is True


def test_pick_best_falls_back_to_latest_when_no_gate_passes():
    best = pick_best([_rv(1, 70, False, 1), _rv(2, 60, False, 2)])
    assert best.version is not None and best.version.id == 2
    assert best.no_clean_round is True
    assert best.regressed is False


def test_pick_best_empty():
    best = pick_best([])
    assert best.version is None
    assert best.no_clean_round is False
    assert best.regressed is False


def test_best_resume_version_reads_persisted_rows():
    with _session() as s:
        save_resume_version(
            s, ResumeVersion(job_id=7, round=1, review_score=90, fact_check_passed=True)
        )
        save_resume_version(
            s,
            ResumeVersion(job_id=7, round=2, review_score=80, fact_check_passed=False),
        )
        best = best_resume_version(s, 7)
        assert best.version is not None and best.version.round == 1
        assert best.no_clean_round is False and best.regressed is True
        assert best_resume_version(s, 999).version is None
