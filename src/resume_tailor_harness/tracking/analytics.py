from dataclasses import dataclass
from typing import Any, Callable, cast

from sqlmodel import Session, select

from resume_tailor_harness.tracking.tables import Application, ApplicationStatus, Job

_RESPONSE = {
    ApplicationStatus.interview.value,
    ApplicationStatus.offer.value,
    ApplicationStatus.rejected.value,
}
_INTERVIEW = {ApplicationStatus.interview.value, ApplicationStatus.offer.value}


def _rate(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


@dataclass
class CohortStat:
    """Conversion counts for one slice. Rates are derived."""

    label: str
    applications: int
    responses: int
    interviews: int
    offers: int

    @property
    def response_rate(self) -> int:
        return _rate(self.responses, self.applications)

    @property
    def interview_rate(self) -> int:
        return _rate(self.interviews, self.applications)

    @property
    def offer_rate(self) -> int:
        return _rate(self.offers, self.applications)


def _band(score: int | None) -> str:
    if score is None:
        return "unscored"
    if score >= 80:
        return "80-100"
    if score >= 60:
        return "60-79"
    return "0-59"


def _rows(session: Session) -> list[tuple[str, int | None, str]]:
    archived_col = cast(Any, Job.archived_at)
    statement = (
        select(Application.status, Job.fit_score, Job.source)
        .join(Job, Application.job_id == Job.id)  # type: ignore[arg-type]
        .where(
            Application.status != ApplicationStatus.ready.value, archived_col.is_(None)
        )
    )
    return list(session.exec(statement).all())


def _cohorts(
    rows: list[tuple[str, int | None, str]],
    key: Callable[[str, int | None, str], str],
) -> list[CohortStat]:
    buckets: dict[str, list[int]] = {}
    for status, fit, source in rows:
        counts = buckets.setdefault(key(status, fit, source), [0, 0, 0, 0])
        counts[0] += 1
        if status in _RESPONSE:
            counts[1] += 1
        if status in _INTERVIEW:
            counts[2] += 1
        if status == ApplicationStatus.offer.value:
            counts[3] += 1
    stats = [CohortStat(label, *counts) for label, counts in buckets.items()]
    return sorted(stats, key=lambda c: (-c.applications, c.label))


def source_stats(session: Session) -> list[CohortStat]:
    """Conversion stats grouped by job source."""
    return _cohorts(_rows(session), key=lambda status, fit, source: source or "unknown")


def fit_band_stats(session: Session) -> list[CohortStat]:
    """Conversion stats grouped by fit-score band."""
    return _cohorts(_rows(session), key=lambda status, fit, source: _band(fit))
