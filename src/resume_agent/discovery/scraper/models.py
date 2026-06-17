from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScrapedCard:
    """A single search-result card; ``url`` + JD text drive ingestion."""

    job_id: str | None
    title: str | None
    company: str | None
    location: str | None
    url: str | None
    posted_at: datetime | None = None


@dataclass
class DetailMeta:
    """Title/company/location from a LinkedIn job-detail page's top card."""

    title: str | None
    company: str | None
    location: str | None
