from dataclasses import dataclass, field


from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown, with_meta_lines
from resume_agent.discovery.search_config import SearchConfig


@dataclass
class BambooHrRow(RawJob):
    opening_id: str = ""
    # Department and remote status are on the *list* item only, so they are
    # captured there and prepended when the detail fetch fills in the body.
    meta_lines: list[str] = field(default_factory=list)


def list_url(token: str) -> str:
    return f"https://{token}.bamboohr.com/careers/list"


def detail_url(token: str, opening_id: str) -> str:
    return f"https://{token}.bamboohr.com/careers/{opening_id}/detail"


def _location(item: dict) -> str | None:
    location = item.get("atsLocation") or item.get("location") or {}
    parts = (
        location.get("city"),
        location.get("state") or location.get("province"),
        location.get("country"),
    )
    result = ", ".join(filter(None, parts))
    return result or ("Remote" if item.get("isRemote") else None)


def _list_meta_lines(item: dict) -> list[str]:
    """The sidebar facts BambooHR puts on the list row rather than the detail."""
    lines = []
    if item.get("isRemote"):
        lines.append("Workplace Type: Remote")
    if department := item.get("departmentLabel"):
        lines.append(f"Department: {department}")
    return lines


def bamboohr_meta_lines(
    opening: dict,
    *,
    location: str | None = None,
    fallback: list[str] | None = None,
) -> list[str]:
    """Render detail metadata, filling only missing labels from the list row."""
    lines: list[str] = []
    if resolved_location := location or _location(opening):
        lines.append(f"Location: {resolved_location}")
    if opening.get("isRemote"):
        lines.append("Workplace Type: Remote")
    for label, key in (
        ("Employment Type", "employmentStatusLabel"),
        ("Department", "departmentLabel"),
    ):
        if value := opening.get(key):
            lines.append(f"{label}: {value}")
    if pay := opening.get("compensation"):
        lines.append(f"Compensation: {pay}")

    present_labels = {line.partition(":")[0] for line in lines}
    if "isRemote" in opening:
        # An explicit false is authoritative even though it renders no line.
        present_labels.add("Workplace Type")
    lines.extend(
        line
        for line in fallback or []
        if line.partition(":")[0] not in present_labels
    )
    return lines


def parse_bamboohr(payload: dict, token: str) -> list[BambooHrRow]:
    rows = []
    for item in payload.get("result") or []:
        opening_id = str(item.get("id") or "")
        rows.append(
            BambooHrRow(
                source="bamboohr",
                url=f"https://{token}.bamboohr.com/careers/{opening_id}"
                if opening_id
                else None,
                company=token,
                title=item.get("jobOpeningName"),
                location=_location(item),
                jd_text="",
                opening_id=opening_id,
                meta_lines=_list_meta_lines(item),
                company_provenance="token",
            )
        )
    return rows


def apply_detail(row: BambooHrRow, detail: dict) -> None:
    opening = ((detail.get("result") or {}).get("jobOpening")) or {}
    row.url = opening.get("jobOpeningShareUrl") or row.url
    row.title = opening.get("jobOpeningName") or row.title
    row.posted_at = parse_iso_datetime(opening.get("datePosted"))
    # Resolve the location before rendering the header, so the line carries the
    # detail payload's value rather than the coarser one from the list row.
    detail_location = _location(opening)
    if detail_location:
        row.location = detail_location
    elif opening.get("isRemote") is False and row.location == "Remote":
        row.location = None
    row.jd_text = with_meta_lines(
        bamboohr_meta_lines(
            opening, location=row.location, fallback=row.meta_lines
        ),
        html_to_markdown(opening.get("description") or ""),
    )


def fetch_bamboohr(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(list_url(target.token))
    response.raise_for_status()
    rows = parse_bamboohr(response.json(), target.token)

    def fetch_detail(row: BambooHrRow) -> dict | None:
        if not row.opening_id:
            return None
        detail = board.get(detail_url(target.token, row.opening_id))
        detail.raise_for_status()
        return detail.json()

    return harvest_detailed(
        rows,
        fetch_detail,
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
