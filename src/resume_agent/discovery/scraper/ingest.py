from typing import Protocol

from sqlmodel import Session

from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.search_config import SearchConfig


class JobSource(Protocol):
    def search(self, config: SearchConfig) -> list[ScrapedCard]: ...
    def fetch_jd(self, card: ScrapedCard) -> str: ...


def ingest_scraped(
    session: Session,
    source: JobSource,
    config: SearchConfig,
    limit: int | None = None,
) -> int:
    """Fetch scraped jobs, insert raw jobs through shared dedupe, and return count added."""
    added = 0
    for index, card in enumerate(source.search(config)):
        if limit is not None and index >= limit:
            break
        jd_text = source.fetch_jd(card).strip()
        if not jd_text:
            continue
        job = add_job(
            session,
            source="linkedin",
            jd_text=jd_text,
            url=card.url,
            company=card.company,
            title=card.title,
            location=card.location,
        )
        if job is not None:
            added += 1
    return added
