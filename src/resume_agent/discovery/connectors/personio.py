import httpx
from bs4 import BeautifulSoup

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig


def feed_url(token: str, country: str = "com") -> str:
    return f"https://{token}.jobs.personio.{country}/xml"


def _text(node) -> str:
    return node.get_text(strip=True) if node is not None else ""


def parse_personio(xml_text: str, token: str, country: str = "com") -> list[RawJob]:
    soup = BeautifulSoup(xml_text, "xml")
    rows = []
    for position in soup.find_all("position"):
        position_id = _text(position.find("id"))
        parts = []
        for section in position.find_all("jobDescription"):
            if heading := _text(section.find("name")):
                parts.append(f"<h2>{heading}</h2>")
            if value := section.find("value"):
                parts.append(value.get_text())
        rows.append(
            RawJob(
                source="personio",
                url=f"https://{token}.jobs.personio.{country}/job/{position_id}"
                if position_id
                else None,
                company=_text(position.find("subcompany")) or token,
                title=_text(position.find("name")),
                location=_text(position.find("office")) or None,
                jd_text=html_to_markdown("\n".join(parts)),
                posted_at=parse_iso_datetime(_text(position.find("createdAt"))),
            )
        )
    return rows


def fetch_personio(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = httpx.get(feed_url(target.token, target.country), timeout=30)
    response.raise_for_status()
    return parse_personio(response.text, target.token, target.country)
