"""Deleting unneeded resume versions and cover letters.

The rules under test, in one place because they are easy to break separately:
orphan (never cascade), refuse the applied artifact, unlink the PDF, and leave
the job's own progress gate exactly as strict as it was.
"""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from resume_agent.services import board
from resume_agent.tracking.repository import (
    get_cover_letter,
    get_resume_version,
    has_progress,
    save_application,
    save_cover_letter,
    save_job,
    save_resume_version,
)
from resume_agent.tracking.tables import (
    Application,
    CoverLetter,
    Job,
    JobStatus,
    ResumeVersion,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _job(session: Session, status: str = JobStatus.tailored.value) -> int:
    return _require_id(save_job(session, Job(source="m", jd_text="jd", status=status)).id)


def _version(session: Session, job_id: int, **kwargs) -> int:
    return _require_id(
        save_resume_version(session, ResumeVersion(job_id=job_id, **kwargs)).id
    )


def _letter(session: Session, job_id: int, **kwargs) -> int:
    return _require_id(save_cover_letter(session, CoverLetter(job_id=job_id, **kwargs)).id)


# --- orphaning -----------------------------------------------------------


def test_deleting_a_version_orphans_its_dependents_instead_of_cascading():
    with _session() as s:
        job_id = _job(s)
        parent = _version(s, job_id, round=1)
        child = _version(s, job_id, round=2, parent_version_id=parent)
        letter = _letter(s, job_id, resume_version_id=parent)

        result = board.delete_resume_versions(s, [parent])

        assert result.deleted == 1
        assert get_resume_version(s, parent) is None
        # The revision descended from it and the cover letter drafted from it
        # both survive; only their pointer is cleared.
        surviving_child = get_resume_version(s, child)
        assert surviving_child is not None
        assert surviving_child.parent_version_id is None
        surviving_letter = get_cover_letter(s, letter)
        assert surviving_letter is not None
        assert surviving_letter.resume_version_id is None


def test_deleting_a_cover_letter_orphans_its_revisions():
    with _session() as s:
        job_id = _job(s)
        parent = _letter(s, job_id)
        child = _letter(s, job_id, parent_id=parent)

        assert board.delete_cover_letters(s, [parent]).deleted == 1

        surviving = get_cover_letter(s, child)
        assert surviving is not None
        assert surviving.parent_id is None


# --- the applied guard ---------------------------------------------------


def test_applied_version_is_refused_and_nothing_in_the_batch_is_deleted():
    with _session() as s:
        job_id = _job(s)
        applied = _version(s, job_id, round=1)
        spare = _version(s, job_id, round=2)
        save_application(s, Application(job_id=job_id, resume_version_id=applied))

        result = board.delete_resume_versions(s, [spare, applied])

        assert result.deleted == 0
        assert result.blocked_ids == (applied,)
        # All-or-nothing: the deletable sibling is still there too.
        assert get_resume_version(s, spare) is not None
        assert get_resume_version(s, applied) is not None


def test_applied_cover_letter_is_refused():
    with _session() as s:
        job_id = _job(s)
        applied = _letter(s, job_id)
        save_application(s, Application(job_id=job_id, cover_letter_id=applied))

        result = board.delete_cover_letters(s, [applied])

        assert result.deleted == 0
        assert result.blocked_ids == (applied,)
        assert get_cover_letter(s, applied) is not None


def test_deselecting_clears_the_pointer_and_unblocks_the_delete():
    with _session() as s:
        job_id = _job(s)
        version_id = _version(s, job_id)
        save_application(s, Application(job_id=job_id, resume_version_id=version_id))

        assert board.delete_resume_versions(s, [version_id]).blocked_ids == (version_id,)

        application = board.deselect_resume_version(s, job_id)
        assert application is not None
        assert application.resume_version_id is None

        assert board.delete_resume_versions(s, [version_id]).deleted == 1


def test_deselect_cover_letter_clears_only_its_own_pointer():
    with _session() as s:
        job_id = _job(s)
        version_id = _version(s, job_id)
        letter_id = _letter(s, job_id)
        save_application(
            s,
            Application(
                job_id=job_id, resume_version_id=version_id, cover_letter_id=letter_id
            ),
        )

        application = board.deselect_cover_letter(s, job_id)

        assert application is not None
        assert application.cover_letter_id is None
        assert application.resume_version_id == version_id


def test_the_primitive_clears_the_application_pointer_even_though_the_gate_blocks_it():
    """`delete_artifact_rows` is unguarded, so it must not be able to leave an
    application citing a version that no longer exists — whichever caller
    reaches it. The service refuses this case, so nothing else covers it."""
    from resume_agent.tracking.repository import delete_artifact_rows

    with _session() as s:
        job_id = _job(s)
        version_id = _version(s, job_id)
        letter_id = _letter(s, job_id)
        save_application(
            s,
            Application(
                job_id=job_id, resume_version_id=version_id, cover_letter_id=letter_id
            ),
        )

        version = get_resume_version(s, version_id)
        letter = get_cover_letter(s, letter_id)
        assert version is not None and letter is not None
        delete_artifact_rows(s, versions=[version], cover_letters=[letter])

        application = s.exec(
            select(Application).where(Application.job_id == job_id)
        ).first()
        assert application is not None
        assert application.resume_version_id is None
        assert application.cover_letter_id is None


def test_every_id_unknown_reports_them_all():
    with _session() as s:
        result = board.delete_resume_versions(s, [9998, 9999])

        assert result.deleted == 0
        assert result.missing_ids == (9998, 9999)


def test_an_empty_request_is_a_no_op():
    with _session() as s:
        assert board.delete_resume_versions(s, []) == board.ArtifactDeleteResult(0)


# --- unknown ids ---------------------------------------------------------


def test_unknown_id_fails_the_whole_batch():
    with _session() as s:
        job_id = _job(s)
        real = _version(s, job_id)

        result = board.delete_resume_versions(s, [real, 9999])

        assert result.deleted == 0
        assert result.missing_ids == (9999,)
        assert get_resume_version(s, real) is not None


def test_repeated_ids_are_deleted_once():
    with _session() as s:
        job_id = _job(s)
        version_id = _version(s, job_id)

        assert board.delete_resume_versions(s, [version_id, version_id]).deleted == 1


# --- the PDF on disk -----------------------------------------------------


def test_deleting_a_version_unlinks_its_rendered_pdf(tmp_path: Path):
    with _session() as s:
        job_id = _job(s)
        pdf = tmp_path / "resume-v1-tailor.pdf"
        pdf.write_bytes(b"%PDF-1.7")
        version_id = _version(s, job_id, pdf_path=str(pdf))

        assert board.delete_resume_versions(s, [version_id]).deleted == 1
        assert not pdf.exists()


def test_a_missing_pdf_does_not_block_the_row_delete(tmp_path: Path):
    """A row whose recorded file is already gone must still be deletable.

    Otherwise an unusable ``pdf_path`` would strand the row permanently --
    the exact opposite of what this feature exists to provide.
    """
    with _session() as s:
        job_id = _job(s)
        version_id = _version(s, job_id, pdf_path=str(tmp_path / "never-rendered.pdf"))

        assert board.delete_resume_versions(s, [version_id]).deleted == 1
        assert get_resume_version(s, version_id) is None


# --- the invariant this feature must not weaken --------------------------


def test_deleting_every_version_does_not_make_a_progressed_job_deletable():
    """Status is a high-water mark, so emptying the child tables is not a back
    door around the job-delete gate."""
    with _session() as s:
        job_id = _job(s, status=JobStatus.rendered.value)
        version_id = _version(s, job_id)
        letter_id = _letter(s, job_id)

        assert board.delete_resume_versions(s, [version_id]).deleted == 1
        assert board.delete_cover_letters(s, [letter_id]).deleted == 1

        assert s.exec(select(ResumeVersion).where(ResumeVersion.job_id == job_id)).first() is None
        assert has_progress(s, job_id) is True
        assert board.delete(s, job_id) is False
