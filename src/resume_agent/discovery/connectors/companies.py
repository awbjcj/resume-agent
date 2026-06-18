import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.greenhouse import fetch_greenhouse_board, parse_greenhouse
from resume_agent.discovery.connectors.lever import fetch_lever_board, parse_lever
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.search_config import SearchConfig


class CompaniesConnector:
    """Pull openings from company careers URLs by auto-detecting their ATS."""

    name = "companies"

    def __init__(self, urls: list[str]):
        self.urls = urls
        self.failures: dict[str, str] = {}
        self.filtered = 0

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs: list[RawJob] = []
        self.failures = {}
        self.filtered = 0

        for url in self.urls:
            target = detect_ats(url)
            if target is None:
                self.failures[url] = "no known ATS detected"
                continue

            try:
                jobs.extend(self._fetch_target(url, target))
            except httpx.HTTPError as exc:
                self.failures[url] = board_error(exc)

        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs

    def _fetch_target(self, url: str, target: AtsTarget) -> list[RawJob]:
        company = target.token
        if target.ats == "greenhouse":
            return parse_greenhouse(fetch_greenhouse_board(target.token), company)
        if target.ats == "lever":
            return parse_lever(fetch_lever_board(target.token), company)
        if target.ats == "ashby":
            return parse_ashby(fetch_ashby_board(target.token), company)

        self.failures[url] = f"{target.ats.title()} recognized, not yet supported"
        return []
