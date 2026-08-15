"""One source of truth for every generic ATS board Scout can resolve."""

from __future__ import annotations

from dataclasses import dataclass

from resume_agent.discovery.connectors.detect import AtsTarget


@dataclass(frozen=True)
class BoardFamily:
    """Discovery and canonical URL rules for one supported ATS family."""

    kind: str
    label: str
    search_hosts: tuple[str, ...]
    sample_url: str
    canonical_template: str | None
    search_group: int


BOARD_FAMILIES: tuple[BoardFamily, ...] = (
    BoardFamily(
        "greenhouse",
        "Greenhouse",
        ("job-boards.greenhouse.io", "boards.greenhouse.io"),
        "https://job-boards.greenhouse.io/acme",
        "https://job-boards.greenhouse.io/{token}",
        1,
    ),
    BoardFamily(
        "lever",
        "Lever",
        ("jobs.lever.co",),
        "https://jobs.lever.co/acme",
        "https://jobs.lever.co/{token}",
        1,
    ),
    BoardFamily(
        "ashby",
        "Ashby",
        ("jobs.ashbyhq.com",),
        "https://jobs.ashbyhq.com/acme",
        "https://jobs.ashbyhq.com/{token}",
        1,
    ),
    BoardFamily(
        "workday",
        "Workday",
        ("myworkdayjobs.com",),
        "https://acme.wd5.myworkdayjobs.com/Acme_Careers",
        None,
        1,
    ),
    BoardFamily(
        "smartrecruiters",
        "SmartRecruiters",
        ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"),
        "https://careers.smartrecruiters.com/acme",
        "https://careers.smartrecruiters.com/{token}",
        2,
    ),
    BoardFamily(
        "workable",
        "Workable",
        ("apply.workable.com", "workable.com"),
        "https://apply.workable.com/acme",
        "https://apply.workable.com/{token}",
        2,
    ),
    BoardFamily(
        "recruitee",
        "Recruitee",
        ("recruitee.com",),
        "https://acme.recruitee.com",
        "https://{token}.recruitee.com",
        2,
    ),
    BoardFamily(
        "personio",
        "Personio",
        ("jobs.personio.com", "jobs.personio.de"),
        "https://acme.jobs.personio.com",
        "https://{token}.jobs.personio.{country}",
        2,
    ),
    BoardFamily(
        "breezy",
        "Breezy",
        ("breezy.hr",),
        "https://acme.breezy.hr",
        "https://{token}.breezy.hr",
        3,
    ),
    BoardFamily(
        "jazzhr",
        "JazzHR",
        ("applytojob.com",),
        "https://acme.applytojob.com",
        "https://{token}.applytojob.com",
        3,
    ),
    BoardFamily(
        "bamboohr",
        "BambooHR",
        ("bamboohr.com",),
        "https://acme.bamboohr.com/careers",
        "https://{token}.bamboohr.com/careers",
        3,
    ),
)

_BY_KIND = {family.kind: family for family in BOARD_FAMILIES}


def board_family(kind: str) -> BoardFamily | None:
    return _BY_KIND.get(kind)


def canonical_target_url(target: AtsTarget) -> str | None:
    """Build the durable public board root for a recognized target."""
    if target.ats == "workday":
        if not (target.tenant and target.datacenter and target.site):
            return None
        return (
            f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com/"
            f"{target.site}"
        )
    family = board_family(target.ats)
    if family is None or family.canonical_template is None or not target.token:
        return None
    return family.canonical_template.format(token=target.token, country=target.country)


def targeted_ats_query_templates() -> tuple[str, ...]:
    """Return three bounded search templates covering every catalog host once."""
    groups: dict[int, list[str]] = {}
    for family in BOARD_FAMILIES:
        groups.setdefault(family.search_group, []).extend(family.search_hosts)
    return tuple(
        '"{company}" ( '
        + " OR ".join(f"site:{host}" for host in groups[group])
        + " ) careers jobs"
        for group in sorted(groups)
    )


def render_supported_board_guidance(max_search_uses: int) -> str:
    """Render catalog-driven Scout instructions without a second provider list."""
    host_rows = [
        f"- {family.label}: " + ", ".join(family.search_hosts)
        for family in BOARD_FAMILIES
    ]
    return "\n".join(
        [
            f"Use at most {max_search_uses} web searches (five web searches by default).",
            'First search: "{company}" official careers jobs. Prefer the corporate careers domain.',
            "If unresolved, run these three ATS-host queries in order and stop after ownership verifies:",
            *(f"- {query}" for query in targeted_ats_query_templates()),
            "Supported families and hosts:",
            *host_rows,
        ]
    )
