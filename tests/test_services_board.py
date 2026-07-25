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


def test_pipeline_sponsorship_and_type_filters_match_shortlist_facets():
    with _session() as session:
        _job(
            session,
            status=JobStatus.approved.value,
            company="Keep",
            criteria_json={
                "sponsorship_signal": "offered",
                "employment_type": "full_time",
            },
        )
        _job(
            session,
            status=JobStatus.approved.value,
            company="Wrong type",
            criteria_json={
                "sponsorship_signal": "offered",
                "employment_type": "contract",
            },
        )
        _job(
            session,
            status=JobStatus.approved.value,
            company="No sponsor",
            criteria_json={
                "sponsorship_signal": "denied",
                "employment_type": "full_time",
            },
        )
        result = board.list_board(
            session,
            "pipeline",
            board_filter=board.BoardFilter(
                sponsorship=("offered",),
                employment_type=("full_time",),
            ),
        )

    assert [row.company for row in result.page.data] == ["Keep"]
    assert result.facets is not None
    assert result.facets["sponsorship"] == {"denied": 1, "offered": 1}
    assert result.facets["employmentType"] == {"contract": 1, "full_time": 1}


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
    # Leave-one-out: the industry facet ignores its own selection, so the
    # unselected "Autonomous Driving" stays counted and selectable.
    assert result.facets is not None
    assert result.facets["industry"] == {"Autonomous Driving": 1, "Fintech": 1}


def test_facets_are_leave_one_out_so_siblings_stay_selectable():
    """Selecting one source keeps the other sources counted in the source facet
    (own selection excluded), while a different facet still narrows to the
    selected-source subset."""
    with _session() as session:
        gh = _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=70,
            criteria_json={"industry": "Fintech"},
        )
        lv = _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=80,
            criteria_json={"industry": "Healthcare"},
        )
        gh.source, lv.source = "greenhouse", "lever"
        session.add_all([gh, lv])
        session.commit()
        result = board.list_board(
            session,
            "shortlist",
            board_filter=board.BoardFilter(source=("greenhouse",)),
        )

    # Only greenhouse rows are in the page...
    assert {row.source for row in result.page.data} == {"greenhouse"}
    assert result.facets is not None
    # ...but the source facet still offers lever (its own selection excluded)...
    assert result.facets["source"] == {"greenhouse": 1, "lever": 1}
    # ...while the industry facet reflects the greenhouse-only subset.
    assert result.facets["industry"] == {"Fintech": 1}


def test_set_stage_changes_status():
    with _session() as session:
        job = _job(session, status=JobStatus.shortlisted.value)
        assert job.id is not None
        updated = board.set_stage(session, job.id, JobStatus.approved.value)
    assert updated is not None
    assert updated.status == JobStatus.approved.value


def test_set_stage_out_of_rejection_overrides_discovery_gates():
    with _session() as session:
        job = _job(session, status=JobStatus.rejected.value)
        job.reject_category = "filtered"
        session.add(job)
        session.commit()
        assert job.id is not None

        updated = board.set_stage(session, job.id, JobStatus.shortlisted.value)

    assert updated is not None
    assert updated.status == JobStatus.shortlisted.value
    assert updated.gate_override is True


def test_set_stage_out_of_rejection_clears_the_stale_reject_reason():
    with _session() as session:
        job = _job(session, status=JobStatus.rejected.value)
        job.reject_reason = "salary below minimum"
        job.reject_category = "filtered"
        session.add(job)
        session.commit()
        assert job.id is not None

        updated = board.set_stage(session, job.id, JobStatus.shortlisted.value)

    assert updated is not None
    assert updated.gate_override is True
    assert updated.reject_reason is None
    assert updated.reject_category is None


def test_set_stage_out_of_filtered_does_not_override_discovery_gates():
    with _session() as session:
        job = _job(session, status=JobStatus.filtered.value)
        assert job.id is not None

        updated = board.set_stage(session, job.id, JobStatus.shortlisted.value)

    assert updated is not None
    assert updated.status == JobStatus.shortlisted.value
    assert updated.gate_override is False


def test_set_stage_back_to_rejection_clears_discovery_gate_override():
    with _session() as session:
        job = _job(session, status=JobStatus.shortlisted.value)
        job.gate_override = True
        session.add(job)
        session.commit()
        assert job.id is not None

        updated = board.set_stage(session, job.id, JobStatus.rejected.value)

    assert updated is not None
    assert updated.gate_override is False


def test_delete_refuses_job_with_progress():
    with _session() as session:
        job = _job(session, status=JobStatus.rendered.value)  # rendered == has_progress
        assert job.id is not None
        assert board.delete(session, job.id) is False


def test_bulk_apply_commits_once():
    with _session() as session:
        ids = [
            _job(
                session,
                company=f"Co{i}",
                title="Engineer",
                status=JobStatus.shortlisted.value,
            ).id
            for i in range(3)
        ]
        assert all(job_id is not None for job_id in ids)

        commits = []
        original_commit = session.commit

        def counting_commit():
            commits.append(1)
            original_commit()

        session.commit = counting_commit  # type: ignore[method-assign]
        try:
            result = board.bulk_apply(
                session,
                board="shortlist",
                action="approve",
                scope="ids",
                board_filter=board.BoardFilter(),
                ids=[job_id for job_id in ids if job_id is not None],
                dry_run=False,
            )
        finally:
            session.commit = original_commit  # type: ignore[method-assign]

        assert result.affected == 3
        assert len(commits) == 1


def test_bulk_stage_change_out_of_rejection_overrides_discovery_gates():
    with _session() as session:
        job = _job(session, status=JobStatus.rejected.value)
        assert job.id is not None

        result = board.bulk_apply(
            session,
            board="triage",
            action="setStatus",
            scope="ids",
            board_filter=board.BoardFilter(),
            ids=[job.id],
            status=JobStatus.shortlisted.value,
            dry_run=False,
        )
        session.refresh(job)

        assert result.affected == 1
        assert job.status == JobStatus.shortlisted.value
        assert job.gate_override is True


def test_bulk_apply_query_count_is_constant():
    from sqlalchemy import event

    with _session() as session:

        def _seed(n):
            ids = []
            for i in range(n):
                job = _job(
                    session,
                    company=f"Batch{n}Co{i}",
                    title="Engineer",
                    status=JobStatus.shortlisted.value,
                )
                assert job.id is not None
                ids.append(job.id)
            return ids

        def _selects(ids):
            counts = {"n": 0}

            def _tally(conn, cursor, statement, parameters, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    counts["n"] += 1

            engine = session.get_bind()
            event.listen(engine, "before_cursor_execute", _tally)
            try:
                board.bulk_apply(
                    session,
                    board="shortlist",
                    action="approve",
                    scope="ids",
                    board_filter=board.BoardFilter(),
                    ids=ids,
                    dry_run=True,
                )
            finally:
                event.remove(engine, "before_cursor_execute", _tally)
            return counts["n"]

        small = _selects(_seed(2))
        large = _selects(_seed(10))
        assert small == large


def test_list_board_derives_filter_values_once_per_request():
    """The page read and the facet counts share one derivation pass.

    Resolving a ``skills`` or ``companySize`` filter means scanning the whole
    table for the raw values behind the canonical token, so a request that did
    it separately for the page and for the facets paid twice for one answer.
    """
    from sqlalchemy import event

    with _session() as session:
        _job(
            session,
            status=JobStatus.shortlisted.value,
            company="Acme",
            criteria_json={
                "must_have_skills": ["Python"],
                "company_size": "seed stage",
            },
        )

        scans: list[str] = []

        def _tally(conn, cursor, statement, parameters, context, executemany):
            if "DISTINCT" in statement.upper():
                scans.append(statement.upper())

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _tally)
        try:
            result = board.list_board(
                session,
                "shortlist",
                board_filter=board.BoardFilter(
                    skills=("python",),
                    company_size=("startup",),  # what "seed stage" snaps to
                ),
                page=1,
            )
        finally:
            event.remove(engine, "before_cursor_execute", _tally)

    # The JSON path is a bound parameter, so match on the extraction function:
    # skills fan out over json_each, company_size is a plain json_extract.
    skill_scans = [s for s in scans if "JSON_EACH" in s]
    size_scans = [s for s in scans if "JSON_EXTRACT" in s and "JSON_EACH" not in s]
    # One pass over the three skill keys, one over company_size -- not two of each.
    assert len(skill_scans) == 3, skill_scans
    assert len(size_scans) == 1, size_scans
    # The shared derivation must not change what the request returns.
    assert [row.company for row in result.page.data] == ["Acme"]
    assert result.facets is not None


def test_stale_days_filter_keeps_only_recently_posted_jobs():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    with _session() as session:
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Fresh",
            posted_at=now - timedelta(days=1),
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Stale",
            posted_at=now - timedelta(days=30),
        )
        result = board.list_board(
            session,
            "shortlist",
            board_filter=board.BoardFilter(stale_days=7),
        )

    assert [row.company for row in result.page.data] == ["Fresh"]


def test_stale_min_days_filter_keeps_only_older_jobs():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    with _session() as session:
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Fresh",
            posted_at=now - timedelta(days=1),
        )
        _job(
            session,
            status=JobStatus.shortlisted.value,
            fit_score=90,
            company="Stale",
            posted_at=now - timedelta(days=30),
        )
        result = board.list_board(
            session,
            "shortlist",
            board_filter=board.BoardFilter(stale_min_days=7),
        )

    assert [row.company for row in result.page.data] == ["Stale"]


def test_reject_reason_filter_is_case_insensitive_and_excludes_missing_reasons():
    with _session() as session:
        _job(
            session,
            status=JobStatus.rejected.value,
            company="Sponsorship rejection",
            reject_reason="Sponsorship not available",
        )
        _job(
            session,
            status=JobStatus.rejected.value,
            company="Salary rejection",
            reject_reason="salary below minimum",
        )
        _job(
            session,
            status=JobStatus.raw.value,
            company="No rejection reason",
        )
        result = board.list_board(
            session,
            "triage",
            board_filter=board.BoardFilter(reject_reason="SPONSORSHIP"),
        )

    assert [row.company for row in result.page.data] == ["Sponsorship rejection"]


def test_facet_specs_match_board_filter_fields():
    import dataclasses

    filter_fields = {f.name for f in dataclasses.fields(board.BoardFilter)}
    keys = [spec.key for spec in board.FACET_SPECS]
    assert len(set(keys)) == len(keys)
    for spec in board.FACET_SPECS:
        assert spec.filter_attr in filter_fields, spec.key
