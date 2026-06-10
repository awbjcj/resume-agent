from dataclasses import dataclass


@dataclass
class ScrapedCard:
    """A single search-result card; ``url`` + JD text drive ingestion."""

    job_id: str | None
    title: str | None
    company: str | None
    location: str | None
    url: str | None
