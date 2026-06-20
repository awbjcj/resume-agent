import httpx

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.harvest import gate_and_limit
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.adzuna.com/v1/api/jobs"


def parse_adzuna(payload: dict) -> list[RawJob]:
    """Map an Adzuna search payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("results", []):
        jobs.append(
            RawJob(
                source="adzuna",
                url=item.get("redirect_url"),
                company=(item.get("company") or {}).get("display_name"),
                title=item.get("title"),
                location=(item.get("location") or {}).get("display_name"),
                jd_text=item.get("description") or "",
                posted_at=parse_iso_datetime(item.get("created")),
            )
        )
    return jobs


class AdzunaConnector:
    """Keyword aggregator. One search call; results filtered client-side too."""

    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, country: str = "us"):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country

    def fetch(self, search: SearchConfig, limit: int | None = None) -> FetchResult:
        jobs, filtered = gate_and_limit(parse_adzuna(self._get_results(search)), search, limit)
        return FetchResult(jobs=jobs, filtered=filtered)

    def _get_results(self, search: SearchConfig) -> dict:
        role_terms = [
            term.strip() for term in [*search.role_anchors, *search.keywords] if term.strip()
        ]
        params: dict[str, str | int] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "category": "it-jobs",
            "results_per_page": 50,
        }
        if role_terms:
            # Adzuna `what_or` is space-delimited (match any word); commas would
            # cling to terms ("engineer,") and break matching.
            params["what_or"] = " ".join(dict.fromkeys(role_terms))
        excludes = [term.strip() for term in search.exclude_terms if term.strip()]
        if excludes:
            params["what_exclude"] = " ".join(excludes)
        if search.locations:
            params["where"] = search.locations[0]
            if search.distance is not None:
                params["distance"] = search.distance
        if search.min_salary is not None:
            params["salary_min"] = search.min_salary
        if search.max_days_old is not None:
            params["max_days_old"] = search.max_days_old
        # Page 1 preserves the current single-request fetch volume while narrowing the query.
        resp = httpx.get(f"{_BASE}/{self.country}/search/1", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
