import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.services import board as legacy_board
from resume_agent.tracking import queries
from resume_agent.tracking.board_query import (
    BoardFilter,
    board_facet_counts,
    board_page,
)
from resume_agent.tracking.tables import Job


NOW = datetime.now(timezone.utc)


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
                jd_text=("Literal_percent Python systems" if index % 2 else "Rust systems"),
                status=statuses[index % len(statuses)],
                fit_score=40 + index,
                reject_reason=(
                    "salary below minimum" if index % 7 == 0 else "sponsorship unavailable"
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


def _legacy_ids(session, board, board_filter, facts_path):
    rows = legacy_board._raw_board_rows(
        session,
        board,
        board_filter,
        facts_path=str(facts_path),
    )
    filtered = legacy_board._apply_board_filter(rows, board_filter)
    ordered = legacy_board._sort_rows(
        filtered,
        board_filter.sort,
        preset=board_filter.preset,
        now=NOW,
    )
    return [row.job_id for row in ordered]


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
def test_pipeline_statement_matches_legacy_filter_and_order(board_session, board_filter):
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
    raw = legacy_board._raw_board_rows(
        session,
        "pipeline",
        board_filter,
        facts_path=str(facts_path),
    )

    actual = board_facet_counts(
        session,
        "pipeline",
        board_filter,
        now=NOW,
        aliases_path=aliases_path,
    )

    assert actual == legacy_board.board_facets(raw, board_filter)


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
    assert first_ids == sorted(first_ids)
    assert second_ids == sorted(second_ids)
    assert set(first_ids).isdisjoint(second_ids)
    assert total == second_total
