"""Pure filtering, sorting, and composite ranking over ShortlistRows."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from resume_agent.tracking.match_gap import normalize_skill
from resume_agent.tracking.queries import ShortlistRow, SkillTag

SALARY_CEILING = 250_000
RECENCY_WINDOW_DAYS = 30
NEUTRAL = 50.0

PRESETS: dict[str, tuple[float, float, float]] = {
    "balanced": (0.50, 0.30, 0.20),
    "pay_first": (0.30, 0.55, 0.15),
    "freshest": (0.35, 0.20, 0.45),
}


@dataclass
class FilterState:
    salary_min: int | None = None
    remote: set[str] = field(default_factory=set)
    sponsorship: set[str] = field(default_factory=set)
    seniority: set[str] = field(default_factory=set)
    employment_type: set[str] = field(default_factory=set)
    industry: set[str] = field(default_factory=set)
    fit_min: int | None = None
    skills: set[str] = field(default_factory=set)
    sort: str = "fit"
    preset: str = "balanced"


def _passes(row: ShortlistRow, state: FilterState) -> bool:
    if state.salary_min is not None and row.salary_max is not None:
        if row.salary_max < state.salary_min:
            return False
    if state.fit_min is not None and row.fit_score is not None:
        if row.fit_score < state.fit_min:
            return False
    for selected, value in (
        (state.remote, row.remote_policy),
        (state.sponsorship, row.sponsorship_signal),
        (state.seniority, row.seniority),
        (state.employment_type, row.employment_type),
        (state.industry, row.industry),
    ):
        if selected and value is not None and value not in selected:
            return False
    if state.skills:
        row_tokens = {normalize_skill(t.name) for t in row.skills}
        if not row_tokens & state.skills:
            return False
    return True


def apply_filters(rows: list[ShortlistRow], state: FilterState) -> list[ShortlistRow]:
    return [row for row in rows if _passes(row, state)]


def _salary_value(row: ShortlistRow) -> int | None:
    return row.salary_max if row.salary_max is not None else row.salary_min


def _age_days(row: ShortlistRow, now: datetime) -> float | None:
    if row.posted_at is None:
        return None
    posted = row.posted_at
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    else:
        posted = posted.astimezone(timezone.utc)
    return (now - posted).total_seconds() / 86400.0


def composite_score(row: ShortlistRow, preset: str, now: datetime) -> float:
    w_fit, w_salary, w_recency = PRESETS.get(preset, PRESETS["balanced"])

    fit_n = float(row.fit_score) if row.fit_score is not None else NEUTRAL

    salary = _salary_value(row)
    salary_n = (
        min(salary, SALARY_CEILING) / SALARY_CEILING * 100
        if salary is not None
        else NEUTRAL
    )

    age = _age_days(row, now)
    recency_n = (
        max(0.0, 100.0 - (age / RECENCY_WINDOW_DAYS * 100.0))
        if age is not None
        else NEUTRAL
    )

    return round(w_fit * fit_n + w_salary * salary_n + w_recency * recency_n, 4)


def sort_rows(
    rows: list[ShortlistRow],
    state: FilterState,
    now: datetime | None = None,
) -> list[ShortlistRow]:
    now = now or datetime.now(timezone.utc)
    if state.sort == "salary":
        return sorted(
            rows,
            key=lambda row: (_salary_value(row) is not None, _salary_value(row) or 0),
            reverse=True,
        )
    if state.sort == "recency":
        return sorted(
            rows,
            key=lambda row: (
                row.posted_at is not None,
                _age_days(row, now) is not None,
                -(_age_days(row, now) or 0.0),
            ),
            reverse=True,
        )
    if state.sort == "composite":
        return sorted(rows, key=lambda row: composite_score(row, state.preset, now), reverse=True)
    return sorted(
        rows,
        key=lambda row: (row.fit_score is not None, row.fit_score or 0),
        reverse=True,
    )


def available_skill_cloud(rows: list[ShortlistRow]) -> list[SkillTag]:
    merged: dict[str, SkillTag] = {}
    for row in rows:
        for tag in row.skills:
            token = normalize_skill(tag.name)
            if not token:
                continue
            existing = merged.get(token)
            if existing is None:
                merged[token] = SkillTag(
                    name=tag.name,
                    covered=tag.covered,
                    required=tag.required,
                )
            else:
                existing.covered = existing.covered or tag.covered
                existing.required = existing.required or tag.required
    return sorted(merged.values(), key=lambda tag: (not tag.covered, tag.name.lower()))
