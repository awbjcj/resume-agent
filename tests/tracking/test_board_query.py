import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from sqlmodel import Session, select

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking import queries
from resume_tailor_harness.tracking.board_query import (
    FACET_SPECS,
    NEUTRAL,
    PRESETS,
    RECENCY_WINDOW_DAYS,
    SALARY_CEILING,
    BoardFilter,
    Preset,
    board_facet_counts,
    board_page,
)
from resume_tailor_harness.tracking.tables import Job


NOW = datetime.now(timezone.utc)
_PUNCT = re.compile(r"[^a-z0-9+#. ]+")
_WS = re.compile(r"\s+")


def _seed(session: Session) -> None:
    statuses = ("raw", "extracted", "filtered", "rejected", "shortlisted", "approved")
    sources = ("greenhouse", "lever", "manual")
    remote = ("remote", "hybrid", "onsite")
    industries = ("Fintech", "Health", None)
    sizes = ("seed stage", "250 employees", "Fortune 500")
    for index in range(48):
        salary = 80_000 + index * 4_000
        criteria = {
            "salary_range": {
                "minimum": salary - 10_000,
                "maximum": salary,
                "currency": "EUR" if index % 11 == 0 else "USD",
            },
            "remote_policy": remote[index % len(remote)],
            "sponsorship_signal": ("offered", "silent", "denied")[index % 3],
            "seniority": ("junior", "mid", "senior")[index % 3],
            "employment_type": ("full_time", "contract")[index % 2],
            "industry": industries[index % len(industries)],
            "company_size": sizes[index % len(sizes)],
            "location_parts": {
                "country": ("US", "CA")[index % 2],
                "region": ("MA", "ON")[index % 2],
                "city": ("Boston", "Toronto")[index % 2],
            },
            "must_have_skills": [
                ("Python and SQL", "K8s", "Rust")[index % 3],
            ],
            "nice_to_have_skills": ["Docker"],
            "tech_stack": ["React" if index % 2 else "Python3"],
        }
        session.add(
            Job(
                source=sources[index % len(sources)],
                company=f"Company {index:02d}",
                title=f"Engineer {47 - index:02d}",
                location=("Boston_US", "Toronto%CA")[index % 2],
                jd_text=(
                    "Literal_percent Python systems" if index % 2 else "Rust systems"
                ),
                status=statuses[index % len(statuses)],
                fit_score=40 + index,
                reject_reason=(
                    "salary below minimum"
                    if index % 7 == 0
                    else "sponsorship unavailable"
                ),
                posted_at=NOW - timedelta(days=index, hours=6),
                archived_at=NOW if index % 17 == 0 else None,
                criteria_json=criteria,
            )
        )
    session.commit()


@pytest.fixture
def board_session(tmp_path, monkeypatch):
    aliases_path = tmp_path / "aliases.json"
    aliases_path.write_text(
        json.dumps({"k8s": "kubernetes", "python3": "python"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(queries, "SKILL_ALIASES_PATH", aliases_path)
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session)
        yield session, aliases_path, tmp_path / "missing-facts.json"
    engine.dispose()


def _legacy_rows(session, board, board_filter, facts_path):
    if board == "shortlist":
        return queries.shortlist_rows(session)
    if board == "pipeline":
        return queries.pipeline_rows(session)
    if board_filter.archived:
        return queries.archived_rows(session)
    return queries.triage_rows(session)


def _normalize(value: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", value.lower())).strip()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _salary(row: Any) -> float:
    return getattr(row, "salary_max", None) or getattr(row, "salary_min", None) or 0


def _passes(row: Any, board_filter: BoardFilter, exclude: str | None = None) -> bool:
    text = " ".join(
        str(value)
        for value in (
            getattr(row, "company", None),
            getattr(row, "title", None),
            getattr(row, "location", None),
            getattr(row, "source", None),
            getattr(row, "status", None),
            getattr(row, "jd_preview", None),
        )
        if value
    ).lower()
    if board_filter.q and board_filter.q.strip().lower() not in text:
        return False
    reason = getattr(row, "reject_reason", None)
    if board_filter.reject_reason and (
        reason is None
        or board_filter.reject_reason.strip().lower() not in reason.lower()
    ):
        return False
    score = getattr(row, "fit_score", None)
    if (
        board_filter.min_fit is not None
        and score is not None
        and score < board_filter.min_fit
    ):
        return False
    if (
        board_filter.max_fit is not None
        and score is not None
        and score > board_filter.max_fit
    ):
        return False
    if board_filter.min_salary is not None:
        salary = _salary(row) or None
        currency = (getattr(row, "salary_currency", None) or "USD").upper()
        if (
            currency == "USD"
            and salary is not None
            and salary < board_filter.min_salary
        ):
            return False
    posted_at = getattr(row, "posted_at", None)
    if board_filter.stale_days is not None:
        if posted_at is None or _aware(posted_at) < NOW - timedelta(
            days=board_filter.stale_days
        ):
            return False
    if board_filter.stale_min_days is not None:
        if posted_at is None or _aware(posted_at) >= NOW - timedelta(
            days=board_filter.stale_min_days
        ):
            return False
    for spec in FACET_SPECS:
        if spec.key == exclude:
            continue
        selected = {value for value in getattr(board_filter, spec.filter_attr) if value}
        value = getattr(row, spec.row_attr, None)
        if spec.skip_unset_rows and value is None:
            continue
        if selected and value not in selected:
            return False
    if exclude != "skills":
        selected = {_normalize(value) for value in board_filter.skills if value}
        row_skills = {
            _normalize(tag.name) for tag in getattr(row, "skills", []) if tag.name
        }
        if selected and not row_skills & selected:
            return False
    return True


def _composite(row: Any, preset: Preset) -> float:
    w_fit, w_salary, w_recency = PRESETS[preset]
    fit = float(row.fit_score) if row.fit_score is not None else NEUTRAL
    salary = _salary(row) or None
    salary_score = (
        min(salary, SALARY_CEILING) / SALARY_CEILING * 100
        if salary is not None
        else NEUTRAL
    )
    if row.posted_at is None:
        recency = NEUTRAL
    else:
        age = (NOW - _aware(row.posted_at)).total_seconds() / 86400
        recency = min(100.0, max(0.0, 100.0 - age / RECENCY_WINDOW_DAYS * 100))
    return w_fit * fit + w_salary * salary_score + w_recency * recency


def _legacy_ids(session, board, board_filter, facts_path):
    rows = [
        row
        for row in _legacy_rows(session, board, board_filter, facts_path)
        if _passes(row, board_filter)
    ]
    if board_filter.sort == "fit":
        ordered = sorted(
            rows,
            key=lambda row: (row.fit_score is not None, row.fit_score or -1),
            reverse=True,
        )
    elif board_filter.sort == "salary":
        ordered = sorted(rows, key=_salary, reverse=True)
    elif board_filter.sort == "recency":
        floor = datetime.min.replace(tzinfo=timezone.utc)
        ordered = sorted(
            rows,
            key=lambda row: _aware(row.posted_at) if row.posted_at else floor,
            reverse=True,
        )
    elif board_filter.sort == "company":
        ordered = sorted(
            rows,
            key=lambda row: (
                (row.company or "").lower(),
                (row.title or "").lower(),
            ),
        )
    elif board_filter.sort == "composite":
        ordered = sorted(
            rows,
            key=lambda row: _composite(row, board_filter.preset),
            reverse=True,
        )
    else:
        ordered = rows
    return [row.job_id for row in ordered]


def _legacy_facets(rows: list[Any], board_filter: BoardFilter):
    facets = {}
    for spec in FACET_SPECS:
        counts = Counter(
            getattr(row, spec.row_attr)
            for row in rows
            if _passes(row, board_filter, exclude=spec.key)
            and getattr(row, spec.row_attr, None)
        )
        if counts:
            facets[spec.key] = dict(
                sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            )
    skill_counts: Counter[str] = Counter()
    for row in rows:
        if not _passes(row, board_filter, exclude="skills"):
            continue
        skill_counts.update(
            {_normalize(tag.name) for tag in getattr(row, "skills", []) if tag.name}
        )
    if skill_counts:
        facets["skills"] = dict(
            sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))
        )
    return facets


@pytest.mark.parametrize(
    "board_filter",
    [
        BoardFilter(),
        BoardFilter(q="PYTHON"),
        BoardFilter(q="%"),
        BoardFilter(q="_"),
        BoardFilter(reject_reason="SPONSORSHIP"),
        BoardFilter(source=("lever",)),
        BoardFilter(status=("approved",)),
        BoardFilter(remote=("hybrid",)),
        BoardFilter(sponsorship=("offered",)),
        BoardFilter(seniority=("senior",)),
        BoardFilter(employment_type=("contract",)),
        BoardFilter(industry=("Fintech",)),
        BoardFilter(country=("US",), region=("MA",), city=("Boston",)),
        BoardFilter(company_size=("startup",)),
        BoardFilter(skills=("python",)),
        BoardFilter(skills=("kubernetes",)),
        BoardFilter(min_fit=55, max_fit=70),
        BoardFilter(min_salary=160_000),
        BoardFilter(stale_days=10),
        BoardFilter(stale_min_days=20),
        BoardFilter(sort="salary"),
        BoardFilter(sort="recency"),
        BoardFilter(sort="company"),
        BoardFilter(sort="composite", preset="balanced"),
        BoardFilter(sort="composite", preset="pay_first"),
        BoardFilter(sort="composite", preset="freshest"),
    ],
)
def test_pipeline_statement_matches_legacy_filter_and_order(
    board_session, board_filter
):
    session, aliases_path, facts_path = board_session

    jobs, total = board_page(
        session,
        "pipeline",
        board_filter,
        page=1,
        page_size=200,
        now=NOW,
        aliases_path=aliases_path,
    )

    expected = _legacy_ids(session, "pipeline", board_filter, facts_path)
    assert [job.id for job in jobs] == expected
    assert total == len(expected)


@pytest.mark.parametrize(
    ("board", "board_filter"),
    [
        ("shortlist", BoardFilter(sort="fit")),
        ("shortlist", BoardFilter(source=("greenhouse",), sort="company")),
        ("shortlist", BoardFilter(q="shortlisted")),
        ("shortlist", BoardFilter(q="python")),
        ("triage", BoardFilter(sort="recency")),
        ("triage", BoardFilter(archived=True, sort="recency")),
        ("triage", BoardFilter(status=("rejected",), min_fit=40, sort="fit")),
        ("triage", BoardFilter(q="raw")),
        ("triage", BoardFilter(q="python")),
    ],
)
def test_board_base_selection_matches_legacy_path(
    board_session,
    board,
    board_filter,
):
    session, aliases_path, facts_path = board_session

    jobs, total = board_page(
        session,
        board,
        board_filter,
        page=1,
        page_size=200,
        now=NOW,
        aliases_path=aliases_path,
    )

    expected = _legacy_ids(session, board, board_filter, facts_path)
    assert [job.id for job in jobs] == expected
    assert total == len(expected)


def test_legacy_stage_sort_remains_deterministic(board_session):
    session, aliases_path, _ = board_session

    jobs, _ = board_page(
        session,
        "pipeline",
        BoardFilter(sort="stage"),
        page=1,
        page_size=200,
        now=NOW,
        aliases_path=aliases_path,
    )

    keys = [(job.status, (job.company or "").lower(), job.id) for job in jobs]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    "board_filter",
    [
        BoardFilter(),
        BoardFilter(source=("lever",), industry=("Fintech",)),
        BoardFilter(skills=("python",)),
        BoardFilter(company_size=("startup",), remote=("remote",)),
    ],
)
def test_facets_match_legacy_leave_one_out_counts(board_session, board_filter):
    session, aliases_path, facts_path = board_session
    raw = _legacy_rows(session, "pipeline", board_filter, facts_path)

    actual = board_facet_counts(
        session,
        "pipeline",
        board_filter,
        now=NOW,
        aliases_path=aliases_path,
    )

    assert actual == _legacy_facets(raw, board_filter)


def test_page_order_has_no_duplicates_across_ties(board_session):
    session, aliases_path, _ = board_session
    for job in session.exec(select(Job)).all():
        job.fit_score = 50
        session.add(job)
    session.commit()

    first, total = board_page(
        session,
        "pipeline",
        BoardFilter(sort="fit"),
        page=1,
        page_size=10,
        now=NOW,
        aliases_path=aliases_path,
    )
    second, second_total = board_page(
        session,
        "pipeline",
        BoardFilter(sort="fit"),
        page=2,
        page_size=10,
        now=NOW,
        aliases_path=aliases_path,
    )

    first_ids = [job.id for job in first]
    second_ids = [job.id for job in second]
    assert first_ids == sorted(cast(list[int], first_ids))
    assert second_ids == sorted(cast(list[int], second_ids))
    assert set(first_ids).isdisjoint(second_ids)
    assert total == second_total
