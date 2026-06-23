import httpx

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.harvest import gate_and_limit
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig

_URL = "https://remoteok.com/api"


def parse_remoteok(payload: list) -> list[RawJob]:
    """Map the RemoteOK API array to RawJobs, skipping the legal header element."""
    jobs: list[RawJob] = []
    for item in payload:
        if not isinstance(item, dict) or "position" not in item:
            continue
        jobs.append(
            RawJob(
                source="remoteok",
                url=item.get("url"),
                company=item.get("company"),
                title=item.get("position"),
                location=item.get("location") or "Remote",
                jd_text=html_to_markdown(item.get("description", "")),
                posted_at=parse_iso_datetime(item.get("date")),
            )
        )
    return jobs


class RemoteOKConnector:
    """Remote-jobs feed. One GET returns everything; filtered client-side."""

    name = "remoteok"

    def fetch(self, search: SearchConfig, limit: int | None = None) -> FetchResult:
        jobs, filtered = gate_and_limit(parse_remoteok(self._get_all()), search, limit)
        return FetchResult(jobs=jobs, filtered=filtered)

    def _get_all(self) -> list:
        resp = httpx.get(_URL, headers={"User-Agent": "resume-agent"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
