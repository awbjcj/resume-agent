from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services import board
from resume_agent.services.pagination import paginate
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_paginate_slices_and_counts():
    page = paginate(list(range(0, 25)), page=2, page_size=10)
    assert page.data == list(range(10, 20))
    assert page.total_items == 25
    assert page.total_pages == 3
    assert page.page == 2


def test_paginate_clamps_page_below_one():
    page = paginate([1, 2, 3], page=0, page_size=10)
    assert page.page == 1
    assert page.data == [1, 2, 3]


def _job(session, **kw):
    job = Job(source="manual", jd_text="x", **kw)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_list_pipeline_filters_by_status_and_min_fit():
    with _session() as session:
        _job(session, status=JobStatus.tailored.value, fit_score=90, company="Acme")
        _job(session, status=JobStatus.raw.value, fit_score=10, company="Beta")
        page = board.list_pipeline(session, status="tailored", min_fit=50)
    assert page.total_items == 1
    assert page.data[0].company == "Acme"


def test_board_min_filters_only_drop_known_failing_values():
    with _session() as session:
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Known pass",
            criteria_json={"salary_range": {"maximum": 180000, "currency": "USD"}},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Low salary",
            criteria_json={"salary_range": {"maximum": 100000, "currency": "USD"}},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=20,
            company="Low fit",
            criteria_json={"salary_range": {"maximum": 180000, "currency": "USD"}},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=None,
            company="Unknown fit salary",
            criteria_json={},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Non USD salary",
            criteria_json={"salary_range": {"maximum": 100000, "currency": "EUR"}},
        )
        result = board.list_board(
            session,
            "shortlist",
            board_filter=board.BoardFilter(min_fit=50, min_salary=150000),
        )

    assert {row.company for row in result.page.data} == {
        "Known pass",
        "Unknown fit salary",
        "Non USD salary",
    }


def test_board_industry_filter_uses_exact_canonical_name():
    with _session() as session:
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=70,
            company="Fintech role",
            criteria_json={"industry": "Fintech"},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=80,
            company="Driving role",
            criteria_json={"industry": "Autonomous Driving"},
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Unknown industry role",
            criteria_json={"industry": None},
        )
        result = board.list_board(
            session,
            "shortlist",
            board_filter=board.BoardFilter(industry=("Fintech",)),
        )

    assert [row.company for row in result.page.data] == [
        "Unknown industry role",
        "Fintech role",
    ]
    assert result.facets["industry"] == {"Fintech": 1}


def test_set_stage_changes_status():
    with _session() as session:
        job = _job(session, status=JobStatus.shortlisted.value)
        assert job.id is not None
        updated = board.set_stage(session, job.id, JobStatus.approved.value)
    assert updated is not None
    assert updated.status == JobStatus.approved.value


def test_delete_refuses_job_with_progress():
    with _session() as session:
        job = _job(session, status=JobStatus.rendered.value)  # rendered == has_progress
        assert job.id is not None
        assert board.delete(session, job.id) is False
