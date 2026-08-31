from dataclasses import dataclass, field
from typing import Any, cast

from sqlmodel import Session, select

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen
from resume_tailor_harness.discovery.source_tier import source_rank
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.tables import Job


def _normalized_location(location: str | None) -> str:
    return (location or "").strip().casefold()


def _normalized_url(url: str | None) -> str | None:
    normalized = (url or "").strip()
    return normalized or None


@dataclass(frozen=True)
class KnownJob:
    source: str


@dataclass
class KnownJobsIndex:
    by_url: dict[str, KnownJob] = field(default_factory=dict)
    by_key_location: dict[tuple[str, str], KnownJob] = field(default_factory=dict)

    @staticmethod
    def _add_best(index: dict, key, known: KnownJob) -> None:
        current = index.get(key)
        if current is None or source_rank(known.source) < source_rank(current.source):
            index[key] = known

    def add(self, job: Job) -> None:
        self.add_fields(job.source, job.url, job.dedup_key, job.location)

    def add_fields(
        self,
        source: str,
        url: str | None,
        dedup_key: str | None,
        location: str | None,
    ) -> None:
        known = KnownJob(source)
        url = _normalized_url(url)
        if url is not None:
            self._add_best(self.by_url, url, known)
        if dedup_key:
            key = (dedup_key, _normalized_location(location))
            self._add_best(self.by_key_location, key, known)

    def match(self, row: RawJob) -> KnownJob | None:
        url = _normalized_url(row.url)
        if url is not None:
            known = self.by_url.get(url)
            if known is not None:
                return known
        dedup_key = compute_dedup_key(row.company, row.title)
        if dedup_key is None:
            return None
        return self.by_key_location.get((dedup_key, _normalized_location(row.location)))


def build_known_index(session: Session) -> KnownJobsIndex:
    archived_at = cast(Any, Job.archived_at)
    index = KnownJobsIndex()
    statement = select(Job.source, Job.url, Job.dedup_key, Job.location).where(
        archived_at.is_(None)
    )
    for source, url, dedup_key, location in session.exec(statement).all():
        index.add_fields(source, url, dedup_key, location)
    return index


def make_skip_seen(index: KnownJobsIndex) -> SkipSeen:
    def skip_seen(row: RawJob) -> bool:
        known = index.match(row)
        return known is not None and source_rank(row.source) >= source_rank(
            known.source
        )

    return skip_seen
