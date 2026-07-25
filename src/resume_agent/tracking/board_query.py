"""SQL-backed selection for the three job boards.

The module owns the BoardFilter-to-SQL translation, stable ordering, paging,
and leave-one-out facet counts. Computed values remain exact: company-size
buckets are derived from the finite raw values present in the database, and
skill filters invert split/canonicalized raw JSON entries before SQL paging.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import String, and_, case, cast as sql_cast, false, func, or_, true
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, select

from resume_agent.taxonomy.company_size import snap as snap_company_size
from resume_agent.taxonomy.skills import canonical_skill, load_aliases, split_skills
from resume_agent.tenancy.paths import SKILL_ALIASES_PATH
from resume_agent.tracking.match_gap import normalize_skill
from resume_agent.tracking.tables import Job, JobStatus

BoardName = Literal["shortlist", "triage", "pipeline"]
SortKey = Literal["fit", "salary", "recency", "composite", "company", "stage"]
Preset = Literal["balanced", "pay_first", "freshest"]
Facets = dict[str, dict[str, int]]

SALARY_CEILING = 250_000
RECENCY_WINDOW_DAYS = 30
NEUTRAL = 50.0
PRESETS: dict[Preset, tuple[float, float, float]] = {
    "balanced": (0.50, 0.30, 0.20),
    "pay_first": (0.30, 0.55, 0.15),
    "freshest": (0.35, 0.20, 0.45),
}

TRIAGE_STATUSES = (
    JobStatus.raw.value,
    JobStatus.extracted.value,
    JobStatus.filtered.value,
    JobStatus.rejected.value,
)
SKILL_KEYS = ("must_have_skills", "nice_to_have_skills", "tech_stack")


def _json_text(*path: str) -> ColumnElement[str]:
    expression = cast(Any, Job.criteria_json)
    for key in path:
        expression = expression[key]
    return cast(ColumnElement[str], expression.as_string())


def _json_number(*path: str) -> ColumnElement[float]:
    expression = cast(Any, Job.criteria_json)
    for key in path:
        expression = expression[key]
    return cast(ColumnElement[float], expression.as_float())


@dataclass(frozen=True)
class BoardFilter:
    q: str | None = None
    reject_reason: str | None = None
    source: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    remote: tuple[str, ...] = ()
    sponsorship: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ()
    employment_type: tuple[str, ...] = ()
    industry: tuple[str, ...] = ()
    country: tuple[str, ...] = ()
    region: tuple[str, ...] = ()
    city: tuple[str, ...] = ()
    company_size: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    min_fit: int | None = None
    max_fit: int | None = None
    min_salary: int | None = None
    stale_days: int | None = None
    stale_min_days: int | None = None
    sort: SortKey = "fit"
    preset: Preset = "balanced"
    archived: bool = False


@dataclass(frozen=True)
class FacetSpec:
    key: str
    row_attr: str
    filter_attr: str
    sql: Callable[[], ColumnElement[Any]]
    skip_unset_rows: bool = False


FACET_SPECS: tuple[FacetSpec, ...] = (
    FacetSpec("source", "source", "source", lambda: cast(Any, Job.source)),
    FacetSpec("status", "status", "status", lambda: cast(Any, Job.status)),
    FacetSpec("remote", "remote_policy", "remote", lambda: _json_text("remote_policy")),
    FacetSpec(
        "sponsorship",
        "sponsorship_signal",
        "sponsorship",
        lambda: _json_text("sponsorship_signal"),
    ),
    FacetSpec("seniority", "seniority", "seniority", lambda: _json_text("seniority")),
    FacetSpec(
        "employmentType",
        "employment_type",
        "employment_type",
        lambda: _json_text("employment_type"),
    ),
    FacetSpec(
        "industry",
        "industry",
        "industry",
        lambda: _json_text("industry"),
        skip_unset_rows=True,
    ),
    FacetSpec(
        "country",
        "location_country",
        "country",
        lambda: _json_text("location_parts", "country"),
    ),
    FacetSpec(
        "region",
        "location_region",
        "region",
        lambda: _json_text("location_parts", "region"),
    ),
    FacetSpec(
        "city",
        "location_city",
        "city",
        lambda: _json_text("location_parts", "city"),
    ),
    FacetSpec(
        "companySize",
        "company_size",
        "company_size",
        lambda: _json_text("company_size"),
    ),
)

_VISIBLE_FACETS: dict[BoardName, frozenset[str]] = {
    "shortlist": frozenset(spec.key for spec in FACET_SPECS if spec.key != "status"),
    "pipeline": frozenset(spec.key for spec in FACET_SPECS),
    "triage": frozenset({"source", "status"}),
}


@dataclass(frozen=True)
class _DerivedFilterValues:
    company_sizes: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None


def _selected(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _base_clauses(board: BoardName, board_filter: BoardFilter) -> list[ColumnElement[bool]]:
    archived = cast(Any, Job.archived_at)
    status = cast(Any, Job.status)
    if board == "shortlist":
        return [
            status == JobStatus.shortlisted.value,
            archived.is_(None),
        ]
    if board == "pipeline":
        return [archived.is_(None)]
    if board_filter.archived:
        return [archived.is_not(None)]
    return [status.in_(TRIAGE_STATUSES), archived.is_(None)]


def _raw_skill_values(session: Session) -> set[str]:
    values: set[str] = set()
    for key in SKILL_KEYS:
        entries = func.json_each(
            cast(Any, Job.criteria_json),
            f"$.{key}",
        ).table_valued("key", "value", joins_implicitly=True)
        statement = (
            select(sql_cast(entries.c.value, String))
            .select_from(Job)
            .join(entries, true())
            .distinct()
        )
        values.update(str(value) for value in session.exec(statement).all() if value)
    return values


def _derive_filter_values(
    session: Session,
    board_filter: BoardFilter,
    aliases_path: str | Path,
) -> _DerivedFilterValues:
    company_sizes: tuple[str, ...] | None = None
    selected_sizes = set(_selected(board_filter.company_size))
    if selected_sizes:
        expression = _json_text("company_size")
        raw_values = session.exec(
            select(expression).where(expression.is_not(None)).distinct()
        ).all()
        company_sizes = tuple(
            str(raw)
            for raw in raw_values
            if raw and snap_company_size(str(raw)) in selected_sizes
        )

    skill_values: tuple[str, ...] | None = None
    selected_skills = {
        normalize_skill(value) for value in board_filter.skills if normalize_skill(value)
    }
    if selected_skills:
        aliases = load_aliases(aliases_path)
        skill_values = tuple(
            raw
            for raw in _raw_skill_values(session)
            if any(
                canonical_skill(atomic, aliases) in selected_skills
                for atomic in split_skills([raw])
            )
        )

    return _DerivedFilterValues(company_sizes=company_sizes, skills=skill_values)


def _skill_exists(raw_values: tuple[str, ...]) -> ColumnElement[bool]:
    if not raw_values:
        return false()
    clauses: list[ColumnElement[bool]] = []
    for key in SKILL_KEYS:
        entries = func.json_each(
            cast(Any, Job.criteria_json),
            f"$.{key}",
        ).table_valued("key", "value", joins_implicitly=True)
        clauses.append(
            select(1)
            .select_from(entries)
            .where(sql_cast(entries.c.value, String).in_(raw_values))
            .correlate(Job)
            .exists()
        )
    return or_(*clauses)


def _search_columns(board: BoardName) -> tuple[ColumnElement[Any], ...]:
    common = (
        cast(Any, Job.company),
        cast(Any, Job.title),
        cast(Any, Job.location),
        cast(Any, Job.source),
    )
    if board == "pipeline":
        return (*common, cast(Any, Job.status), cast(Any, Job.jd_text))
    if board == "triage":
        return (*common, cast(Any, Job.status))
    return common


def _salary_value(board: BoardName) -> ColumnElement[float | None]:
    if board == "triage":
        return cast(ColumnElement[float | None], func.nullif(0, 0))
    maximum = _json_number("salary_range", "maximum")
    minimum = _json_number("salary_range", "minimum")
    return cast(
        ColumnElement[float | None],
        func.coalesce(func.nullif(maximum, 0), func.nullif(minimum, 0)),
    )


def _filter_clauses(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    exclude: str | None,
    now: datetime,
    aliases_path: str | Path,
    derived: _DerivedFilterValues | None = None,
) -> list[ColumnElement[bool]]:
    clauses = _base_clauses(board, board_filter)

    query = (board_filter.q or "").strip()
    if query:
        clauses.append(
            or_(
                *(
                    func.coalesce(column, "").icontains(query, autoescape=True)
                    for column in _search_columns(board)
                )
            )
        )

    reject_reason = (board_filter.reject_reason or "").strip()
    if reject_reason:
        if board == "shortlist":
            clauses.append(false())
        else:
            clauses.append(
                cast(Any, Job.reject_reason).icontains(
                    reject_reason,
                    autoescape=True,
                )
            )

    fit_score = cast(Any, Job.fit_score)
    if board_filter.min_fit is not None:
        clauses.append(
            or_(fit_score.is_(None), fit_score >= board_filter.min_fit)
        )
    if board_filter.max_fit is not None:
        clauses.append(
            or_(fit_score.is_(None), fit_score <= board_filter.max_fit)
        )

    if board_filter.min_salary is not None and board != "triage":
        salary = _salary_value(board)
        currency = _json_text("salary_range", "currency")
        clauses.append(
            or_(
                func.upper(func.coalesce(currency, "USD")) != "USD",
                salary.is_(None),
                salary >= board_filter.min_salary,
            )
        )

    posted_at = cast(Any, Job.posted_at)
    if board_filter.stale_days is not None:
        cutoff = now - timedelta(days=board_filter.stale_days)
        clauses.extend((posted_at.is_not(None), posted_at >= cutoff))
    if board_filter.stale_min_days is not None:
        cutoff = now - timedelta(days=board_filter.stale_min_days)
        clauses.extend((posted_at.is_not(None), posted_at < cutoff))

    derived = derived or _derive_filter_values(session, board_filter, aliases_path)
    visible_facets = _VISIBLE_FACETS[board]
    for spec in FACET_SPECS:
        if spec.key == exclude:
            continue
        selected = _selected(getattr(board_filter, spec.filter_attr))
        if not selected:
            continue
        if spec.key not in visible_facets:
            if not spec.skip_unset_rows:
                clauses.append(false())
            continue
        expression = spec.sql()
        matches: Sequence[str] = selected
        if spec.key == "companySize":
            matches = derived.company_sizes or ()
        predicate = expression.in_(matches) if matches else false()
        if spec.skip_unset_rows:
            predicate = or_(expression.is_(None), predicate)
        clauses.append(predicate)

    selected_skills = _selected(board_filter.skills)
    if exclude != "skills" and selected_skills:
        if board == "triage":
            clauses.append(false())
        else:
            clauses.append(_skill_exists(derived.skills or ()))

    return clauses


def _composite_expression(
    board: BoardName,
    preset: Preset,
    now: datetime,
) -> ColumnElement[float]:
    w_fit, w_salary, w_recency = PRESETS[preset]
    fit = func.coalesce(cast(Any, Job.fit_score), NEUTRAL)
    salary = _salary_value(board)
    salary_normalized = case(
        (salary.is_(None), NEUTRAL),
        else_=func.min(salary, SALARY_CEILING) / SALARY_CEILING * 100.0,
    )
    posted_at = cast(Any, Job.posted_at)
    age_days = func.julianday(now) - func.julianday(posted_at)
    recency_normalized = case(
        (posted_at.is_(None), NEUTRAL),
        else_=func.min(
            100.0,
            func.max(
                0.0,
                100.0 - age_days / RECENCY_WINDOW_DAYS * 100.0,
            ),
        ),
    )
    return cast(
        ColumnElement[float],
        w_fit * fit + w_salary * salary_normalized + w_recency * recency_normalized,
    )


def _ordering(
    board: BoardName,
    board_filter: BoardFilter,
    now: datetime,
) -> tuple[ColumnElement[Any], ...]:
    job_id = cast(Any, Job.id)
    company = func.lower(func.coalesce(cast(Any, Job.company), ""))
    title = func.lower(func.coalesce(cast(Any, Job.title), ""))
    if board_filter.sort == "fit":
        return (cast(Any, Job.fit_score).desc().nullslast(), job_id)
    if board_filter.sort == "salary":
        return (func.coalesce(_salary_value(board), 0).desc(), job_id)
    if board_filter.sort == "recency":
        return (cast(Any, Job.posted_at).desc().nullslast(), job_id)
    if board_filter.sort == "company":
        return (company, title, job_id)
    if board_filter.sort == "stage":
        if board == "shortlist":
            return (company, job_id)
        return (cast(Any, Job.status), company, job_id)
    return (_composite_expression(board, board_filter.preset, now).desc(), job_id)


def board_statement(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    now: datetime | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
):
    """Return the filtered and stably ordered statement, before paging."""
    query_time = now or datetime.now(timezone.utc)
    derived = _derive_filter_values(session, board_filter, aliases_path)
    return select(Job).where(
        *_filter_clauses(
            session,
            board,
            board_filter,
            exclude=None,
            now=query_time,
            aliases_path=aliases_path,
            derived=derived,
        )
    ).order_by(*_ordering(board, board_filter, query_time))


def board_page(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    page: int,
    page_size: int,
    now: datetime | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> tuple[list[Job], int]:
    """Return one stable page of jobs plus the full filtered count."""
    page = max(1, page)
    page_size = max(1, page_size)
    statement = board_statement(
        session,
        board,
        board_filter,
        now=now,
        aliases_path=aliases_path,
    )
    id_statement = statement.with_only_columns(cast(Any, Job.id))
    count_statement = select(func.count()).select_from(
        id_statement.order_by(None).subquery()
    )
    total = session.exec(count_statement).one()
    page_ids = list(
        session.exec(
            id_statement.offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    if not page_ids:
        return [], total
    job_id = cast(Any, Job.id)
    jobs_by_id = {
        job.id: job
        for job in session.exec(select(Job).where(job_id.in_(page_ids))).all()
    }
    jobs = [jobs_by_id[value] for value in page_ids]
    return jobs, total


def _sorted_counts(counts: Counter[str]) -> dict[str, int]:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _skill_facet_counts(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    now: datetime,
    aliases_path: str | Path,
    derived: _DerivedFilterValues,
) -> dict[str, int]:
    if board == "triage":
        return {}
    aliases = load_aliases(aliases_path)
    tokens_by_job: dict[int, set[str]] = defaultdict(set)
    tokens_by_raw: dict[str, tuple[str, ...]] = {}
    clauses = _filter_clauses(
        session,
        board,
        board_filter,
        exclude="skills",
        now=now,
        aliases_path=aliases_path,
        derived=derived,
    )
    for key in SKILL_KEYS:
        entries = func.json_each(
            cast(Any, Job.criteria_json),
            f"$.{key}",
        ).table_valued("key", "value", joins_implicitly=True)
        statement = (
            select(cast(Any, Job.id), sql_cast(entries.c.value, String))
            .select_from(Job)
            .join(entries, true())
            .where(*clauses)
        )
        for job_id, raw in session.exec(statement).all():
            if not raw:
                continue
            raw_text = str(raw)
            tokens = tokens_by_raw.get(raw_text)
            if tokens is None:
                tokens = tuple(
                    token
                    for atomic in split_skills([raw_text])
                    if (token := canonical_skill(atomic, aliases))
                )
                tokens_by_raw[raw_text] = tokens
            tokens_by_job[job_id].update(tokens)
    counts: Counter[str] = Counter()
    for tokens in tokens_by_job.values():
        counts.update(tokens)
    return _sorted_counts(counts)


def _shared_facet_projection_allowed(board_filter: BoardFilter) -> bool:
    return not board_filter.skills and not any(
        _selected(getattr(board_filter, spec.filter_attr)) for spec in FACET_SPECS
    )


def _shared_facet_counts(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    now: datetime,
    aliases_path: str | Path,
    derived: _DerivedFilterValues,
) -> Facets:
    """Count facets from one narrow projection when leave-one-out sets coincide."""
    visible_specs = [
        spec for spec in FACET_SPECS if spec.key in _VISIBLE_FACETS[board]
    ]
    clauses = _filter_clauses(
        session,
        board,
        board_filter,
        exclude=None,
        now=now,
        aliases_path=aliases_path,
        derived=derived,
    )
    columns = [
        cast(Any, Job.id),
        cast(Any, Job.source),
        cast(Any, Job.status),
    ]
    if board != "triage":
        columns.append(cast(Any, Job.criteria_json))
    statement = select(*columns).where(*clauses)

    value_counts = {spec.key: Counter[str]() for spec in visible_specs}
    skill_counts: Counter[str] = Counter()
    aliases = load_aliases(aliases_path)
    tokens_by_raw: dict[str, tuple[str, ...]] = {}
    for row in session.exec(statement).all():
        source = row[1]
        status = row[2]
        criteria = row[3] or {} if board != "triage" else {}
        location = criteria.get("location_parts") or {}
        values = {
            "source": source,
            "status": status,
            "remote": criteria.get("remote_policy"),
            "sponsorship": criteria.get("sponsorship_signal"),
            "seniority": criteria.get("seniority"),
            "employmentType": criteria.get("employment_type"),
            "industry": criteria.get("industry"),
            "country": location.get("country"),
            "region": location.get("region"),
            "city": location.get("city"),
            "companySize": criteria.get("company_size"),
        }
        for spec in visible_specs:
            value = values[spec.key]
            if not value:
                continue
            token = str(value)
            if spec.key == "companySize":
                snapped = snap_company_size(token)
                if snapped is None:
                    continue
                token = snapped
            value_counts[spec.key][token] += 1

        if board != "triage":
            job_skills: set[str] = set()
            for key in SKILL_KEYS:
                raw_items = [str(item) for item in (criteria.get(key) or [])]
                for raw in raw_items:
                    tokens = tokens_by_raw.get(raw)
                    if tokens is None:
                        tokens = tuple(
                            token
                            for atomic in split_skills([raw])
                            if (token := canonical_skill(atomic, aliases))
                        )
                        tokens_by_raw[raw] = tokens
                    job_skills.update(tokens)
            skill_counts.update(job_skills)

    facets = {
        key: _sorted_counts(counts)
        for key, counts in value_counts.items()
        if counts
    }
    if skill_counts:
        facets["skills"] = _sorted_counts(skill_counts)
    return facets


def board_facet_counts(
    session: Session,
    board: BoardName,
    board_filter: BoardFilter,
    *,
    now: datetime | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> Facets:
    """Return leave-one-out counts without hydrating board row DTOs."""
    query_time = now or datetime.now(timezone.utc)
    derived = _derive_filter_values(session, board_filter, aliases_path)
    if _shared_facet_projection_allowed(board_filter):
        return _shared_facet_counts(
            session,
            board,
            board_filter,
            now=query_time,
            aliases_path=aliases_path,
            derived=derived,
        )
    facets: Facets = {}
    for spec in FACET_SPECS:
        if spec.key not in _VISIBLE_FACETS[board]:
            continue
        expression = spec.sql()
        clauses = _filter_clauses(
            session,
            board,
            board_filter,
            exclude=spec.key,
            now=query_time,
            aliases_path=aliases_path,
            derived=derived,
        )
        statement = (
            select(expression, func.count())
            .where(and_(*clauses), expression.is_not(None))
            .group_by(expression)
        )
        raw_counts: Counter[str] = Counter()
        for value, count in session.exec(statement).all():
            if not value:
                continue
            key = str(value)
            if spec.key == "companySize":
                snapped = snap_company_size(key)
                if snapped is None:
                    continue
                key = snapped
            raw_counts[key] += count
        if raw_counts:
            facets[spec.key] = _sorted_counts(raw_counts)

    skills = _skill_facet_counts(
        session,
        board,
        board_filter,
        now=query_time,
        aliases_path=aliases_path,
        derived=derived,
    )
    if skills:
        facets["skills"] = skills
    return facets
