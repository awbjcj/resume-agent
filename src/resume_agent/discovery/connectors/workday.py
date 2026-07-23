import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown, primary_search_term
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.tenancy.context import current_context

_PAGE = 20  # cxs page size
_MAX_OFFSET = (
    1000  # safety ceiling: <=51 pages (~1020 rows) even if a tenant ignores searchText
)
_FACETS_DIR = Path("data/workday_facets")

# Large Workday boards (thousands of postings) fire many list + detail requests;
# an intermittent throttle (429) or transient 5xx must not abort the whole pull.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 4  # one initial call + three retries
_RETRY_BACKOFF_S = 2.0  # exponential base when the server sends no Retry-After
_MAX_RETRY_SLEEP_S = 30.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header; None for absent/date/garbage."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None  # HTTP-date form is rare here; fall back to backoff


def _request_with_retry(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Issue a Workday request, retrying transient throttles/5xx with backoff.

    Honors a numeric ``Retry-After`` when present, else exponential backoff.
    After ``_RETRY_ATTEMPTS`` the last error is re-raised so a persistently
    failing endpoint still surfaces as a per-URL failure upstream (the
    companies connector isolates it rather than aborting sibling URLs).
    """
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            response = send()
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status not in _RETRY_STATUSES or attempt + 1 >= _RETRY_ATTEMPTS:
                raise
            delay = _retry_after_seconds(error.response)
            if delay is None:
                delay = _RETRY_BACKOFF_S * (2**attempt)
            time.sleep(min(delay, _MAX_RETRY_SLEEP_S))
    raise AssertionError("unreachable")  # pragma: no cover


def default_facets_dir() -> Path:
    """Per-tenant facet cache when a workspace is active, else the flat default.

    ``fetch_workday`` runs inside a pull run, where ``RunManager.submit`` has
    copied the caller's ``UserContext`` into the worker, so each workspace's
    resolved location facets live under its own root (which provisioning creates
    and reset targets) instead of a shared cwd path.
    """
    context = current_context()
    return context.paths.workday_facets_dir if context is not None else _FACETS_DIR


@dataclass
class WorkdayRow(RawJob):
    """A list-page RawJob that remembers its detail path for the N+1 fetch."""

    external_path: str = ""


def _base(target: AtsTarget) -> str:
    return f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com"


def cxs_jobs_url(target: AtsTarget) -> str:
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/jobs"


def list_request_body(
    search: SearchConfig,
    offset: int,
    applied_facets: dict[str, list[str]] | None = None,
) -> dict:
    return {
        "appliedFacets": applied_facets or {},
        "limit": _PAGE,
        "offset": offset,
        "searchText": primary_search_term(search),
    }


def _facet_values(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _facet_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _facet_values(value)


def resolve_location_facets(
    page: dict, locations: list[str]
) -> dict[str, list[str]]:
    """Resolve every requested location under location-only facet parameters."""
    wanted = [location.strip().casefold() for location in locations if location.strip()]
    facets = page.get("facets")
    if not wanted or not isinstance(facets, list):
        return {}

    matched: set[int] = set()
    applied: dict[str, list[str]] = {}
    for facet in facets:
        if not isinstance(facet, dict):
            continue
        parameter = facet.get("facetParameter")
        if not isinstance(parameter, str) or "location" not in parameter.casefold():
            continue
        for value in _facet_values(facet.get("values")):
            descriptor = value.get("descriptor")
            facet_id = value.get("id")
            if not isinstance(descriptor, str) or not isinstance(facet_id, str):
                continue
            haystack = descriptor.casefold()
            matching = {
                index
                for index, location in enumerate(wanted)
                if location == haystack
                or (
                    len(location) >= 3
                    and len(haystack) >= 3
                    and (location in haystack or haystack in location)
                )
            }
            if not matching:
                continue
            matched.update(matching)
            ids = applied.setdefault(parameter, [])
            if facet_id not in ids:
                ids.append(facet_id)
    return applied if len(matched) == len(wanted) else {}


def _facet_cache_path(target: AtsTarget, base_dir: str | Path) -> Path:
    return Path(base_dir) / f"{target.tenant}-{target.site}.json"


def _normalized_locations(locations: list[str]) -> list[str]:
    return sorted(location.strip() for location in locations if location.strip())


def load_cached_facets(
    target: AtsTarget,
    locations: list[str],
    base_dir: str | Path = _FACETS_DIR,
) -> dict[str, list[str]] | None:
    """Load a matching, well-shaped cache; ``{}`` is a remembered miss."""
    try:
        payload = json.loads(
            _facet_cache_path(target, base_dir).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("locations") != _normalized_locations(
        locations
    ):
        return None
    applied = payload.get("appliedFacets")
    if not isinstance(applied, dict):
        return None
    if not all(
        isinstance(parameter, str)
        and isinstance(ids, list)
        and all(isinstance(facet_id, str) for facet_id in ids)
        for parameter, ids in applied.items()
    ):
        return None
    return applied


def save_cached_facets(
    target: AtsTarget,
    locations: list[str],
    applied: dict[str, list[str]],
    base_dir: str | Path = _FACETS_DIR,
) -> None:
    path = _facet_cache_path(target, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "locations": _normalized_locations(locations),
        "appliedFacets": applied,
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_list_rows(target: AtsTarget, page: dict) -> list[WorkdayRow]:
    rows: list[WorkdayRow] = []
    for item in page.get("jobPostings", []):
        path = item.get("externalPath") or ""
        rows.append(
            WorkdayRow(
                source="workday",
                url=f"{_base(target)}{path}" if path else None,
                company=target.tenant,
                title=item.get("title"),
                location=item.get("locationsText"),
                jd_text="",
                external_path=path,
            )
        )
    return rows


def cxs_detail_url(target: AtsTarget, external_path: str) -> str:
    # external_path already begins with "/job/..."; the cxs detail endpoint is the
    # site path with that suffix appended verbatim (no special-casing of the prefix).
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}{external_path}"


def apply_detail(row: WorkdayRow, detail: dict) -> None:
    info = detail.get("jobPostingInfo") or {}
    row.jd_text = html_to_markdown(info.get("jobDescription", ""))
    if info.get("externalUrl"):
        row.url = info["externalUrl"]
    if info.get("location"):
        row.location = info["location"]
    info_company = info.get("companyName")
    if isinstance(info_company, str) and info_company.strip():
        company = info_company.strip()
        if row.company and company.casefold() != row.company.casefold():
            row.stale_company = row.stale_company or row.company
        row.company = company
    row.posted_at = parse_iso_datetime(info.get("startDate"))


def _list_page(
    target: AtsTarget,
    search: SearchConfig,
    offset: int,
    applied_facets: dict[str, list[str]],
) -> dict:
    response = _request_with_retry(
        lambda: httpx.post(
            cxs_jobs_url(target),
            json=list_request_body(search, offset, applied_facets),
            timeout=30,
        )
    )
    return response.json()


def _remember_facets(
    target: AtsTarget,
    locations: list[str],
    applied: dict[str, list[str]],
    facets_dir: str | Path,
) -> bool:
    try:
        save_cached_facets(target, locations, applied, facets_dir)
    except OSError:
        return False
    return True


def _list_pages(
    target: AtsTarget,
    search: SearchConfig,
    facets_dir: str | Path = _FACETS_DIR,
):
    locations = [location.strip() for location in search.locations if location.strip()]
    cached = load_cached_facets(target, locations, facets_dir) if locations else {}
    applied = cached or {}
    offset = 0
    page = None

    if locations and cached is None:
        plain_page = _list_page(target, search, 0, {})
        resolved = resolve_location_facets(plain_page, locations)
        if not _remember_facets(target, locations, resolved, facets_dir):
            resolved = {}
        if resolved:
            faceted_page = _list_page(target, search, 0, resolved)
            if faceted_page.get("jobPostings"):
                applied = resolved
                page = faceted_page
            else:
                applied = {}
                _remember_facets(target, locations, {}, facets_dir)
                page = plain_page
        else:
            page = plain_page

    while offset <= _MAX_OFFSET:
        if page is None:
            page = _list_page(target, search, offset, applied)
        postings = page.get("jobPostings") or []
        if not postings:
            if offset == 0 and applied:
                applied = {}
                _remember_facets(target, locations, {}, facets_dir)
                page = None
                continue
            return
        yield from parse_list_rows(target, page)
        total = page.get("total")
        offset += _PAGE
        if isinstance(total, int) and offset >= total:
            return
        page = None


def _fetch_detail(target: AtsTarget, row: WorkdayRow) -> dict | None:
    # No detail path -> cannot fetch a description; skip rather than GET a bad URL.
    if not row.external_path:
        return None
    resp = _request_with_retry(
        lambda: httpx.get(cxs_detail_url(target, row.external_path), timeout=30)
    )
    return resp.json()


def fetch_workday(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
    facets_dir: str | Path | None = None,
) -> list[RawJob]:
    """List with safe location facets, then gate and detail-fetch survivors."""
    if facets_dir is None:
        facets_dir = default_facets_dir()
    return harvest_detailed(
        _list_pages(target, search, facets_dir),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
