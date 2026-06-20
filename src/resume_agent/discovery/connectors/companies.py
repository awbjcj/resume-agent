import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.google import fetch_google
from resume_agent.discovery.connectors.greenhouse import fetch_greenhouse_board, parse_greenhouse
from resume_agent.discovery.connectors.lever import fetch_lever_board, parse_lever
from resume_agent.discovery.connectors.tesla import fetch_tesla
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.connectors.workday import fetch_workday
from resume_agent.discovery.search_config import SearchConfig


# Adapters: thin, late-bound wrappers so each backend stays monkeypatchable at the
# module seam and shares one dispatch shape: (target, search, limit) -> RawJob[].
def _greenhouse(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return parse_greenhouse(fetch_greenhouse_board(target.token), target.token)


def _lever(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return parse_lever(fetch_lever_board(target.token), target.token)


def _ashby(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return parse_ashby(fetch_ashby_board(target.token), target.token)


def _workday(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return fetch_workday(target, search, limit)


def _tesla(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return fetch_tesla(target, search, limit)


def _google(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    return fetch_google(target, search, limit)


# ats -> adapter(target, search, limit) -> RawJob[]
_BACKENDS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workday": _workday,
    "tesla": _tesla,
    "google": _google,
}


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
            backend = _BACKENDS.get(target.ats)
            if backend is None:
                self.failures[url] = f"{target.ats.title()} recognized, not yet supported"
                continue
            try:
                jobs.extend(backend(target, search, limit))
            except httpx.HTTPError as exc:
                self.failures[url] = board_error(exc)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                # Reverse-engineered singleton payloads (Tesla/Google) may shift shape; isolate a
                # parse failure to this URL instead of aborting the whole pull.
                self.failures[url] = f"parse error: {type(exc).__name__}"

        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs
