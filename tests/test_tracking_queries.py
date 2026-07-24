from datetime import datetime, timezone

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.db import init_db, make_engine
from resume_agent.models.base import Source
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.repository import save_application, save_job, save_resume_version
from resume_agent.tracking.queries import job_detail_row, pipeline_rows, shortlist_rows, triage_rows
from resume_agent.tracking.tables import Application, ApplicationStatus, Job, JobStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _facts_with_python() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"lang": [Skill(name="Python", source=Source.resume)]},
    )


def test_shortlist_rows_only_shortlisted_with_fit_and_sponsorship():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                        status=JobStatus.shortlisted.value, fit_score=82,
                        fit_rationale="strong python match",
                        criteria_json={"sponsorship_signal": "offered"}))
        save_job(s, Job(source="manual", jd_text="b", company="Beta", title="Dev",
                        status=JobStatus.raw.value))  # excluded

        rows = shortlist_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.company == "Acme"
        assert row.fit_score == 82
        assert row.fit_rationale == "strong python match"
        assert row.sponsorship_signal == "offered"


def test_shortlist_row_flattens_metadata_and_tags_coverage():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                company="Acme",
                title="Eng",
                status=JobStatus.shortlisted.value,
                fit_score=80,
                posted_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                criteria_json={
                    "salary_range": {
                        "minimum": 150000,
                        "maximum": 190000,
                        "currency": "USD",
                    },
                    "remote_policy": "remote",
                    "seniority": "senior",
                    "employment_type": "full_time",
                    "industry": "Fintech",
                    "company_size": "scaleup",
                    "must_have_skills": ["Python", "Go"],
                    "nice_to_have_skills": ["Docker"],
                },
            ),
        )
        rows = shortlist_rows(s, facts=_facts_with_python())
        row = rows[0]
        assert row.salary_min == 150000
        assert row.salary_max == 190000
        assert row.salary_currency == "USD"
        assert row.remote_policy == "remote"
        assert row.seniority == "senior"
        assert row.employment_type == "full_time"
        assert row.industry == "Fintech"
        assert row.company_size == "scaleup"
        assert row.posted_at == datetime(2026, 6, 1)
        # Skill tags are keyed by canonical (normalized, lowercased) token.
        names = {t.name: t for t in row.skills}
        assert names["python"].covered is True
        assert names["python"].required is True
        assert names["go"].covered is False
        assert names["go"].required is True
        assert names["docker"].required is False


def test_job_detail_hides_internal_industry_retry_candidate():
    with _session() as session:
        job = save_job(
            session,
            Job(
                source="manual",
                jd_text="a",
                criteria_json={
                    "industry": None,
                    "_industry_candidate": "Financial Technology",
                },
            ),
        )

        row = job_detail_row(session, _require_id(job.id))

        assert row is not None
        assert row.criteria_json == {"industry": None}


def test_shortlist_row_surfaces_tech_stack_as_nonrequired_deduped():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                status=JobStatus.shortlisted.value,
                criteria_json={
                    "must_have_skills": ["Python"],
                    "tech_stack": ["Python", "Kafka"],  # Python dup -> stays required
                },
            ),
        )
        rows = shortlist_rows(s, facts=_facts_with_python())
        # Skill tags are keyed by canonical (normalized, lowercased) token.
        names = {t.name: t for t in rows[0].skills}
        # Python appears once, keeping its must-have (required) slot.
        assert [t.name for t in rows[0].skills].count("python") == 1
        assert names["python"].required is True
        assert names["python"].covered is True
        # Kafka surfaces from tech_stack as a non-required, filterable tag.
        assert names["kafka"].required is False
        assert names["kafka"].covered is False


def test_shortlist_row_without_facts_marks_all_uncovered():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": ["Python"]},
            ),
        )
        rows = shortlist_rows(s, facts=None)
        assert rows[0].skills[0].covered is False


def test_pipeline_rows_include_pdf_and_application_status():
    with _session() as s:
        job = save_job(s, Job(source="manual", jd_text="a", company="Acme", title="Eng",
                              status=JobStatus.rendered.value, fit_score=90))
        save_resume_version(s, ResumeVersion(job_id=_require_id(job.id), round=1, content_json={"x": 1}))
        save_resume_version(
            s,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=2,
                content_json={"contact": {"name": "Ada"}},
                critique_json=[{"reviewer": "fact-check", "passed": True}],
                pdf_path="output/acme.pdf",
            ),
        )
        save_application(s, Application(job_id=_require_id(job.id), status=ApplicationStatus.submitted.value))

        rows = pipeline_rows(s)
        assert len(rows) == 1
        row = rows[0]
        assert row.status == JobStatus.rendered.value
        assert row.pdf_path == "output/acme.pdf"
        assert row.jd_text == "a"
        assert row.critique_json == [{"reviewer": "fact-check", "passed": True}]
        assert row.application_status == ApplicationStatus.submitted.value
        assert row.fit_score == 90


def test_pipeline_row_surfaces_best_gate_passing_round():
    with _session() as session:
        job = save_job(
            session, Job(source="url", status=JobStatus.tailored.value)
        )
        job_id = _require_id(job.id)
        save_resume_version(
            session,
            ResumeVersion(
                job_id=job_id,
                round=1,
                review_score=90,
                fact_check_passed=True,
                critique_json=[{"reviewer": "ats-keyword", "score": 90, "passed": True}],
            ),
        )
        save_resume_version(
            session,
            ResumeVersion(
                job_id=job_id,
                round=2,
                review_score=70,
                fact_check_passed=False,
                critique_json=[{"reviewer": "fact-check", "score": 0, "passed": False}],
            ),
        )

        row = next(r for r in pipeline_rows(session) if r.job_id == job_id)

        assert row.critique_json == [
            {"reviewer": "ats-keyword", "score": 90, "passed": True}
        ]
        assert row.regressed is True
        assert row.needs_attention is False


def test_pipeline_row_flags_no_clean_round():
    with _session() as session:
        job = save_job(
            session, Job(source="url", status=JobStatus.tailored.value)
        )
        save_resume_version(
            session,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=1,
                review_score=50,
                fact_check_passed=False,
                critique_json=[],
            ),
        )

        row = next(r for r in pipeline_rows(session) if r.job_id == job.id)

        assert row.needs_attention is True


def test_job_detail_marks_best_version_and_attention():
    with _session() as session:
        job = save_job(
            session, Job(source="url", status=JobStatus.tailored.value)
        )
        v1 = save_resume_version(
            session,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=1,
                review_score=92,
                fact_check_passed=True,
                content_json={},
            ),
        )
        save_resume_version(
            session,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=2,
                review_score=70,
                fact_check_passed=False,
                content_json={},
            ),
        )

        row = job_detail_row(session, _require_id(job.id))

        assert row is not None
        assert row.best_resume_version_id == v1.id
        assert row.regressed is True
        assert row.needs_attention is False
        assert len(row.resume_versions) == 2


def test_job_detail_no_versions_has_no_best():
    with _session() as session:
        job = save_job(
            session, Job(source="url", status=JobStatus.shortlisted.value)
        )

        row = job_detail_row(session, _require_id(job.id))

        assert row is not None
        assert row.best_resume_version_id is None
        assert row.needs_attention is False
        assert row.regressed is False


def test_pipeline_rows_clean_legacy_source_chrome_tokens():
    with _session() as s:
        save_job(
            s,
            Job(
                source="google",
                jd_text=(
                    "Google \\_corporate\\_fare\\_ Google \\_place\\_ San Francisco, CA "
                    "\\_laptop\\_windows\\_ Remote eligible \\*\\*Mid\\*\\*"
                ),
                company="Google",
                title="Forward Deployed Engineer",
                status=JobStatus.approved.value,
            ),
        )

        row = pipeline_rows(s)[0]

        assert "\\_corporate" not in row.jd_text
        assert "\\_place" not in row.jd_text
        assert "\\_laptop" not in row.jd_text
        assert "\\*\\*" not in row.jd_text
        assert row.jd_text == "Google Google San Francisco, CA Remote eligible Mid"


def test_pipeline_rows_distinguish_no_version_from_empty_critiques():
    # The board must tell "never tailored" (no ResumeVersion) apart from
    # "tailored, reviewers raised nothing": None vs []. Collapsing both to []
    # made every untailored card read as an empty critique list.
    with _session() as s:
        untailored = save_job(s, Job(source="manual", jd_text="a", company="A", title="E",
                                     status=JobStatus.shortlisted.value))
        reviewed_clean = save_job(s, Job(source="manual", jd_text="b", company="B", title="E",
                                         status=JobStatus.tailored.value))
        save_resume_version(
            s, ResumeVersion(job_id=_require_id(reviewed_clean.id), round=1, content_json={"x": 1})
        )

        by_id = {row.job_id: row for row in pipeline_rows(s)}
        assert by_id[_require_id(untailored.id)].critique_json is None
        assert by_id[_require_id(reviewed_clean.id)].critique_json == []


def test_archived_jobs_excluded_from_shortlist_and_pipeline():
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        keep = save_job(s, Job(source="m", jd_text="a", company="Keep", title="E",
                               status=JobStatus.shortlisted.value, fit_score=70))
        hide = save_job(s, Job(source="m", jd_text="b", company="Hide", title="E",
                               status=JobStatus.shortlisted.value, fit_score=90))
        archive_job(s, _require_id(hide.id))

        assert [r.company for r in shortlist_rows(s)] == ["Keep"]
        assert [r.company for r in pipeline_rows(s)] == ["Keep"]
        _ = keep


def test_archived_jobs_excluded_from_application_job_pairs():
    from resume_agent.tracking.queries import application_job_pairs
    from resume_agent.tracking.repository import archive_job, save_application
    from resume_agent.tracking.tables import Application, ApplicationStatus

    with _session() as s:
        keep = save_job(s, Job(source="m", jd_text="a", company="Keep", title="E",
                               status=JobStatus.rendered.value))
        hide = save_job(s, Job(source="m", jd_text="b", company="Hide", title="E",
                               status=JobStatus.rendered.value))
        save_application(s, Application(job_id=_require_id(keep.id),
                                        status=ApplicationStatus.submitted.value))
        save_application(s, Application(job_id=_require_id(hide.id),
                                        status=ApplicationStatus.submitted.value))
        archive_job(s, _require_id(hide.id))

        assert [job.company for _, job in application_job_pairs(s)] == ["Keep"]


def test_pipeline_rows_include_lean_metadata_fields():
    with _session() as s:
        save_job(
            s,
            Job(
                source="manual",
                jd_text="a",
                company="Acme",
                title="Eng",
                status=JobStatus.filtered.value,
                criteria_json={
                    "salary_range": {
                        "minimum": 140000,
                        "maximum": 180000,
                        "currency": "USD",
                    },
                    "remote_policy": "hybrid",
                    "seniority": "staff",
                    "sponsorship_signal": "offered",
                    "employment_type": "full_time",
                    "industry": "Fintech",
                    "company_size": "enterprise",
                    "location_parts": {
                        "country": "US",
                        "region": "NY",
                        "city": "New York",
                    },
                    "must_have_skills": ["Python"],
                },
                reject_reason="outside salary band",
                reject_category="filtered",
            ),
        )

        row = pipeline_rows(s)[0]
        assert row.salary_min == 140000
        assert row.salary_max == 180000
        assert row.salary_currency == "USD"
        assert row.remote_policy == "hybrid"
        assert row.seniority == "staff"
        assert row.sponsorship_signal == "offered"
        assert row.employment_type == "full_time"
        assert row.industry == "Fintech"
        assert row.company_size == "enterprise"
        assert row.location_country == "US"
        assert row.location_region == "NY"
        assert row.location_city == "New York"
        assert [skill.name for skill in row.skills] == ["python"]
        assert row.reject_reason == "outside salary band"
        assert row.reject_category == "filtered"


def test_triage_rows_are_pre_shortlist_and_unarchived():
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        save_job(s, Job(source="m", jd_text="a", company="Raw", title="E",
                        status=JobStatus.raw.value, fit_score=30))
        save_job(s, Job(source="m", jd_text="b", company="Rej", title="E",
                        status=JobStatus.rejected.value))
        save_job(s, Job(source="m", jd_text="c", company="Short", title="E",
                        status=JobStatus.shortlisted.value))  # excluded: has own page
        hidden = save_job(s, Job(source="m", jd_text="d", company="Hidden", title="E",
                                 status=JobStatus.raw.value))
        archive_job(s, _require_id(hidden.id))

        companies = {r.company for r in triage_rows(s)}
        assert companies == {"Raw", "Rej"}


def test_triage_and_detail_rows_surface_reject_reason():
    with _session() as s:
        rejected = save_job(
            s,
            Job(
                source="m", jd_text="a", company="Rej", title="E",
                status=JobStatus.rejected.value,
                reject_reason="off-target role: not a backend posting",
                reject_category="relevance",
            ),
        )
        save_job(s, Job(source="m", jd_text="b", company="Raw", title="E",
                        status=JobStatus.raw.value))

        by_company = {r.company: r for r in triage_rows(s)}
        assert by_company["Rej"].reject_reason == "off-target role: not a backend posting"
        assert by_company["Raw"].reject_reason is None

        detail = job_detail_row(s, _require_id(rejected.id))
        assert detail is not None
        assert detail.reject_reason == "off-target role: not a backend posting"


def test_archived_rows_lists_all_archived_any_status():
    from resume_agent.tracking.queries import archived_rows
    from resume_agent.tracking.repository import archive_job

    with _session() as s:
        a = save_job(s, Job(source="m", jd_text="a", company="A", title="E",
                            status=JobStatus.shortlisted.value))
        b = save_job(s, Job(source="m", jd_text="b", company="B", title="E",
                            status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="c", company="C", title="E",
                        status=JobStatus.raw.value))  # not archived
        archive_job(s, _require_id(a.id))
        archive_job(s, _require_id(b.id))

        assert {r.company for r in archived_rows(s)} == {"A", "B"}


def test_shortlist_row_exposes_industry_location_and_canonical_skills(tmp_path):
    aliases = tmp_path / "aliases.json"
    aliases.write_text('{"k8s": "kubernetes"}', "utf-8")
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        save_job(
            s,
            Job(
                source="x", jd_text="jd", title="Eng", company="C",
                status=JobStatus.shortlisted.value, location="Austin, TX, USA",
                criteria_json={
                    "industry": "Autonomous Driving",
                    "company_size": "Series A",
                    "must_have_skills": ["Python, C++ or C", "k8s"],
                    "location_parts": {
                        "city": "Austin", "region": "TX", "country": "US",
                        "is_us": True, "raw": "Austin, TX, USA",
                    },
                },
            ),
        )
        rows = shortlist_rows(s, facts=facts, aliases_path=aliases)
        row = rows[0]
        assert row.industry == "Autonomous Driving"
        assert row.location_country == "US"
        assert row.location_region == "TX"
        assert row.location_city == "Austin"
        assert row.is_us is True
        assert row.company_size == "startup"
        names = {t.name for t in row.skills}
        assert {"python", "c++", "c", "kubernetes"} <= names  # split + canonicalized


def test_shortlist_row_preserves_canonical_industry():
    with _session() as s:
        save_job(
            s,
            Job(
                source="x",
                jd_text="jd",
                status=JobStatus.shortlisted.value,
                criteria_json={"industry": "Fintech"},
            ),
        )

        row = shortlist_rows(s)[0]

        assert row.industry == "Fintech"


def _seeded_engine(job_count: int):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for i in range(job_count):
            job = Job(
                source="greenhouse",
                company=f"Co{i}",
                title=f"Role {i}",
                jd_text=f"jd {i}",
                status=JobStatus.tailored.value if i % 2 else JobStatus.raw.value,
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            if i % 2:
                assert job.id is not None
                session.add(ResumeVersion(job_id=job.id, round=1, fact_check_passed=True))
                session.add(Application(job_id=job.id, status="ready"))
                session.commit()
    return engine


def _select_count(engine, fn) -> int:
    counts = {"n": 0}

    def _tally(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counts["n"] += 1

    event.listen(engine, "before_cursor_execute", _tally)
    try:
        with Session(engine) as session:
            fn(session)
    finally:
        event.remove(engine, "before_cursor_execute", _tally)
    return counts["n"]


def test_pipeline_rows_query_count_is_constant():
    small = _select_count(_seeded_engine(2), pipeline_rows)
    large = _select_count(_seeded_engine(12), pipeline_rows)
    assert small == large  # no per-job queries


def test_triage_rows_query_count_is_constant():
    small = _select_count(_seeded_engine(2), triage_rows)
    large = _select_count(_seeded_engine(12), triage_rows)
    assert small == large


def test_shortlist_and_triage_rows_never_touch_jd_text():
    """Pins the invariant that lets jd_text stay deferred on list queries.

    ShortlistItem and TriageItem never ship jd_text on the wire; if a future
    row field starts reading job.jd_text, the defer() in these queries would
    silently issue one lazy SELECT per row (N+1). Fail here first.
    """
    import inspect

    import resume_agent.tracking.queries as queries_module

    for fn in (queries_module._shortlist_row, queries_module._triage_row):
        assert "jd_text" not in inspect.getsource(fn), (
            f"{fn.__name__} reads jd_text; remove defer() from its query "
            "before shipping this change"
        )
