"""The source-priority merge decision, as a pure function over (existing, incoming).

`save_or_upgrade` in ingest.py does the DB-bound parts (clean, find the match,
mutate, commit). The *policy* — canonical-beats-aggregator, freeze a tailored
posting's text, merge optionals without erasing — lives here as a pure `decide`
that returns a typed `MergeAction`. The applier just carries it out, so each
invariant is a value-comparable assertion needing no Session.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from resume_agent.discovery.connectors.text import is_materially_richer
from resume_agent.discovery.source_tier import source_rank
from resume_agent.tracking.dedup import compute_dedup_key
from resume_agent.tracking.tables import Job, JobStatus


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@dataclass(frozen=True)
class IncomingJob:
    """A job offered to ingest, normalized: strings trimmed, blanks collapsed to None."""

    source: str
    jd_text: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    posted_at: datetime | None = None

    @classmethod
    def clean(
        cls,
        *,
        source: str,
        jd_text: str,
        url: str | None = None,
        company: str | None = None,
        title: str | None = None,
        location: str | None = None,
        posted_at: datetime | None = None,
    ) -> "IncomingJob":
        return cls(
            source=source,
            jd_text=jd_text.strip(),
            url=_clean(url),
            company=_clean(company),
            title=_clean(title),
            location=_clean(location),
            posted_at=posted_at,
        )

    @property
    def dedup_key(self) -> str | None:
        return compute_dedup_key(self.company, self.title)


@dataclass(frozen=True)
class Insert:
    """Create a new raw Job from the incoming fields."""


@dataclass(frozen=True)
class Skip:
    """Leave the existing row untouched (same/lower tier, or a frozen posting)."""


@dataclass(frozen=True)
class UpgradeUrlOnly:
    """Past-raw upgrade: take the higher-tier url + source, freeze everything else."""

    url: str
    source: str


@dataclass(frozen=True)
class Rebase:
    """Raw re-base: apply these field writes to the existing row (merge without erase)."""

    updates: dict[str, Any]


@dataclass(frozen=True)
class RefreshText:
    """Same-source detail refresh: replace a thin JD with a materially richer copy."""

    updates: dict[str, Any]


MergeAction = Insert | Skip | UpgradeUrlOnly | Rebase | RefreshText


_TEXT_REFRESH_FROZEN = {JobStatus.tailored.value, JobStatus.rendered.value}


def decide(existing: Job | None, incoming: IncomingJob) -> MergeAction:
    """Decide what to do with `incoming` given the row `find_existing` matched (or None)."""
    if existing is None:
        return Insert()

    # Same source, both carry a url, urls differ -> a distinct posting (e.g. the same
    # role in two locations on one board). The url lookup already failed to match it.
    if (
        incoming.url
        and existing.url
        and incoming.url != existing.url
        and incoming.source == existing.source
    ):
        return Insert()

    if (
        incoming.source == existing.source
        and incoming.url
        and existing.url
        and incoming.url == existing.url
        and existing.status not in _TEXT_REFRESH_FROZEN
        and is_materially_richer(incoming.jd_text, existing.jd_text)
    ):
        updates: dict[str, Any] = {"jd_text": incoming.jd_text}
        if incoming.company:
            updates["company"] = incoming.company
        if incoming.title:
            updates["title"] = incoming.title
        if incoming.location:
            updates["location"] = incoming.location
        if incoming.posted_at is not None:
            updates["posted_at"] = incoming.posted_at
        return RefreshText(updates=updates)

    if source_rank(incoming.source) >= source_rank(existing.source):
        return Skip()

    # Higher-tier source from here.
    if existing.status != JobStatus.raw.value:
        # A resume may already be tailored to the old text, so freeze jd_text and only
        # upgrade the apply url. Nothing worth upgrading when the incoming has no url.
        if not incoming.url:
            return Skip()
        return UpgradeUrlOnly(url=incoming.url, source=incoming.source)

    # Raw + higher tier: re-base the text, merging optionals without erasing what we know.
    updates: dict[str, Any] = {"source": incoming.source, "jd_text": incoming.jd_text}
    if incoming.url:
        updates["url"] = incoming.url
    if incoming.company:
        updates["company"] = incoming.company
    if incoming.title:
        updates["title"] = incoming.title
    if incoming.location:
        updates["location"] = incoming.location
    if incoming.posted_at is not None:
        updates["posted_at"] = incoming.posted_at
    company = incoming.company or existing.company
    title = incoming.title or existing.title
    updates["dedup_key"] = compute_dedup_key(company, title)
    return Rebase(updates=updates)
