"""Source Scout context, stable dedupe, and deterministic re-validation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from resume_agent.concurrency import gather_isolated
from resume_agent.config import Settings, get_settings
from resume_agent.discovery.connectors.config import (
    ConnectorsConfig,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.sources import NATIVE_URL_KINDS, list_source_views
from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.scout_models import citation_rows, is_http_url
from resume_agent.discovery.source_scout import (
    MAX_CANDIDATES,
    ScoutCandidate,
    ScoutReport,
    build_scout_formatter_agent,
    build_scout_research_agent,
    make_check_source_tool,
)
from resume_agent.llm_runner import Runner, expect_schema
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts
from resume_agent.services.sources import SourcePreview, preview_source

_TOP_SKILLS = 15


def _load_connectors(path: str) -> ConnectorsConfig:
    return load_connectors_config(path) if Path(path).exists() else ConnectorsConfig()


def scout_context(connectors_path: str, search_path: str, profile_dir: Path) -> str:
    """Build compact grounding; every optional workspace artifact may be absent."""
    profile_dir = Path(profile_dir)
    titles: list[str] = []
    facts_path = profile_dir / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        titles = [row.title for row in facts.experience if row.title][:5]

    matrix = load_matrix(profile_dir / "matrix.json")
    skills = [row.display for row in matrix.rows][:_TOP_SKILLS] if matrix else []

    anchors: list[str] = []
    locations: list[str] = []
    try:
        search = load_search_config(search_path)
        anchors = list(search.role_anchors)
        locations = list(search.locations)
    except (OSError, ValueError):
        pass

    config = _load_connectors(connectors_path)
    settings = Settings.model_construct(browser_enabled=True)
    existing = [
        f"{view.kind}: {view.display_name}" for view in list_source_views(config, settings)
    ]

    def block(name: str, values: list[str]) -> str:
        body = "\n".join(f"- {value}" for value in values) if values else "(none)"
        return f"{name}:\n{body}"

    return "\n\n".join(
        [
            block("PROFILE RECENT TITLES", titles),
            block("PROFILE TOP SKILLS", skills),
            block("SEARCH ROLE ANCHORS", anchors),
            block("SEARCH LOCATIONS", locations),
            block("EXISTING SOURCES", existing),
        ]
    )


def _canonical_url(url: str) -> str:
    raw = url.strip()
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return raw
    if not parsed.scheme or not host:
        return raw
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), netloc, path, parsed.query, ""))


def _candidate_keys(url: str) -> set[str]:
    keys = {_canonical_url(url)}
    target = identify_host(url)
    if target is not None and target.token:
        keys.add(f"{target.ats}:{target.token.casefold()}")
    return keys


def _existing_keys(config: ConnectorsConfig) -> set[str]:
    keys: set[str] = set()
    for kind in ("greenhouse", "lever", "ashby"):
        for board in getattr(config, kind).boards:
            keys.add(f"{kind}:{board.token.casefold()}")
    for kind in NATIVE_URL_KINDS:
        keys.update(_canonical_url(board.url) for board in getattr(config, kind).boards)
    keys.update(_canonical_url(entry.url) for entry in config.companies.urls)
    keys.update(_canonical_url(target.url) for target in config.scrape.targets)
    return keys


def _row(candidate: ScoutCandidate, preview: SourcePreview | None, status: str) -> dict:
    return {
        "company": candidate.company,
        "url": preview.url if preview is not None else candidate.careers_url,
        "reason": candidate.reason,
        "confidence": candidate.confidence,
        "status": status,
        "signal": candidate.signal,
        "fitScore": candidate.fit_score,
        "citations": citation_rows(candidate.citations),
        "ats": preview.kind if preview is not None else None,
        "token": preview.token if preview is not None else None,
        "roleCount": preview.role_count if preview is not None else None,
        "error": preview.error if preview is not None and status == "failed" else None,
        "errorCode": preview.error_code if preview is not None else None,
    }


def run_source_discovery(
    reporter,
    *,
    prompt: str,
    connectors_path: str,
    search_path: str,
    profile_dir: Path,
    browser_enabled: bool | None = None,
    research_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    reporter.begin(1, "Scouting companies", phase_index=0, phase_count=2)
    research = research_agent or build_scout_research_agent(
        make_check_source_tool(search_path)
    )
    formatter = formatter_agent or build_scout_formatter_agent()
    context = scout_context(connectors_path, search_path, Path(profile_dir))
    notes = research.run(f"USER PROMPT:\n{prompt}\n\n{context}").content
    result = formatter.run(f"RESEARCH NOTES (UNTRUSTED):\n{notes}")
    report = expect_schema(result, ScoutReport, source="source-scout")
    candidates = [
        row
        for row in report.candidates
        if is_http_url(row.careers_url)
        or (row.signal == "avoid" and bool(row.company.strip()))
    ][:MAX_CANDIDATES]
    reporter.step(1)

    seen = _existing_keys(_load_connectors(connectors_path))
    rows: list[dict | None] = [None] * len(candidates)
    fresh: list[tuple[int, ScoutCandidate]] = []
    for index, candidate in enumerate(candidates):
        if candidate.signal == "avoid":
            rows[index] = _row(candidate, None, "avoid")
            continue
        keys = _candidate_keys(candidate.careers_url)
        if keys & seen:
            rows[index] = _row(candidate, None, "duplicate")
        else:
            seen.update(keys)
            fresh.append((index, candidate))

    reporter.begin(
        max(len(fresh), 1), "Validating candidates", phase_index=1, phase_count=2
    )

    async def validate_all():
        return await gather_isolated(
            fresh,
            lambda item: asyncio.to_thread(
                preview_source,
                item[1].careers_url,
                search_path=search_path,
                browser=False,
            ),
            on_complete=reporter.step,
            checkpoint=reporter.checkpoint,
        )

    results = asyncio.run(validate_all()) if fresh else []
    for (index, candidate), result in zip(fresh, results, strict=True):
        preview = result.value if result.ok else None
        if preview is not None and preview.ok:
            status = "validated"
        elif preview is not None and preview.error_code == "ATS_NOT_DETECTED":
            status = "unverified"
        else:
            status = "failed"
            if preview is None:
                preview = SourcePreview(
                    ok=False,
                    url=candidate.careers_url,
                    error=f"Validation failed ({type(result.error).__name__}).",
                    error_code="VALIDATION_ERROR",
                )
        rows[index] = _row(candidate, preview, status)

    scrape_available = (
        get_settings().browser_enabled if browser_enabled is None else browser_enabled
    )
    status_order = {
        "validated": 0,
        "unverified": 1,
        "avoid": 2,
        "failed": 3,
        "duplicate": 4,
    }

    def rank_key(row: dict) -> tuple[int, int]:
        score = row["fitScore"]
        return status_order.get(row["status"], 5), -score if score is not None else 1

    ranked = sorted((row for row in rows if row is not None), key=rank_key)
    return {
        "prompt": prompt,
        "candidates": ranked,
        "scrapeAvailable": scrape_available,
        "scrapeUnavailableReason": (
            None if scrape_available else "Scrape targets require a local browser."
        ),
    }
