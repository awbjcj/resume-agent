import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import filter_by_search
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

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs = filter_by_search(parse_adzuna(self._get_results(search)), search)
        return jobs[:limit] if limit is not None else jobs

    def _get_results(self, search: SearchConfig) -> dict:
        terms = list(
            dict.fromkeys(t.strip() for t in [*search.titles, *search.keywords] if t.strip())
        )
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": " ".join(terms),
            "results_per_page": 50,
        }
        if search.locations:
            params["where"] = search.locations[0]
        resp = httpx.get(f"{_BASE}/{self.country}/search/1", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
