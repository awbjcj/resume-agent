"""Grounding, feedback rendering, and deterministic Scout dedupe keys."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import (
    ConnectorsConfig,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.connectors.sources import (
    NATIVE_URL_KINDS,
    list_source_views,
)
from resume_agent.discovery.search_config import load_search_config
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts

_TOP_SKILLS = 15
_DISMISSAL_LEDGER_CAP = 20
TRANSCRIPT_CHAR_CAP = 12_000

_EXISTING_FIELD = {
    "keyword": "keywords",
    "title": "titles",
    "role_anchor": "role_anchors",
    "exclude_term": "exclude_terms",
    "location": "locations",
    "seniority": "experience_levels",
    "adjacent_role": "titles",
}


def _load_connectors(path: str) -> ConnectorsConfig:
    return load_connectors_config(path) if Path(path).exists() else ConnectorsConfig()


def _block(name: str, values: list[str]) -> str:
    return f"{name}:\n" + (
        "\n".join(f"- {value}" for value in values) if values else "(none)"
    )


def scout_context(connectors_path: str, search_path: str, profile_dir: Path) -> str:
    profile_dir = Path(profile_dir)
    titles: list[str] = []
    facts_path = profile_dir / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        titles = [row.title for row in facts.experience if row.title][:5]
    matrix = load_matrix(profile_dir / "matrix.json")
    skills = [row.display for row in matrix.rows][:_TOP_SKILLS] if matrix else []

    search_values = {field: [] for field in set(_EXISTING_FIELD.values())}
    try:
        search = load_search_config(search_path)
        search_values = {
            field: list(getattr(search, field, [])) for field in search_values
        }
    except (OSError, ValueError):
        pass
    existing = [
        f"{view.kind}: {view.display_name}"
        for view in list_source_views(
            _load_connectors(connectors_path),
            Settings.model_construct(browser_enabled=True),
        )
    ]
    return "\n\n".join(
        [
            _block("PROFILE RECENT TITLES", titles),
            _block("PROFILE TOP SKILLS", skills),
            _block("CURRENT KEYWORDS", search_values["keywords"]),
            _block("CURRENT TITLES", search_values["titles"]),
            _block("CURRENT ROLE ANCHORS", search_values["role_anchors"]),
            _block("CURRENT EXCLUDE TERMS", search_values["exclude_terms"]),
            _block("CURRENT LOCATIONS", search_values["locations"]),
            _block("CURRENT SENIORITY", search_values["experience_levels"]),
            _block("EXISTING SOURCES", existing),
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
    default_port = (parsed.scheme.casefold() == "http" and port == 80) or (
        parsed.scheme.casefold() == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path.rstrip("/") or "/",
            parsed.query,
            "",
        )
    )


def _candidate_keys(url: str) -> set[str]:
    keys = {_canonical_url(url)}
    target = identify_host(url)
    if target is not None and target.token:
        keys.add(f"{target.ats}:{target.token.casefold()}")
    return keys


def _existing_keys(config: ConnectorsConfig) -> set[str]:
    keys: set[str] = set()
    for kind in ("greenhouse", "lever", "ashby"):
        keys.update(
            f"{kind}:{row.token.casefold()}" for row in getattr(config, kind).boards
        )
    for kind in NATIVE_URL_KINDS:
        keys.update(_canonical_url(row.url) for row in getattr(config, kind).boards)
    keys.update(_canonical_url(row.url) for row in config.companies.urls)
    keys.update(_canonical_url(row.url) for row in config.scrape.targets)
    return keys


def _existing_terms(search_path: str) -> dict[str, set[str]]:
    fields = set(_EXISTING_FIELD.values())
    try:
        search = load_search_config(search_path)
    except (OSError, ValueError):
        return {field: set() for field in fields}
    return {
        field: {value.casefold() for value in getattr(search, field, [])}
        for field in fields
    }


def _company_key(company: str) -> str:
    return "company:" + " ".join(company.casefold().split())


def session_source_keys(session: dict) -> set[str]:
    keys: set[str] = set()
    for proposal in session.get("proposals", []):
        if proposal.get("kind") != "source" or not proposal.get("source"):
            continue
        source = proposal["source"]
        company = str(source.get("company", "")).strip()
        if company:
            keys.add(_company_key(company))
        url = str(source.get("url", "")).strip()
        if url:
            keys.update(_candidate_keys(url))
    return keys


def session_term_keys(session: dict) -> set[str]:
    keys: set[str] = set()
    for proposal in session.get("proposals", []):
        if proposal.get("kind") != "search_term" or not proposal.get("term"):
            continue
        term = proposal["term"]
        field = _EXISTING_FIELD.get(term.get("term_kind"))
        value = str(term.get("value", "")).strip()
        if field and value:
            keys.add(f"{field}:{value.casefold()}")
    return keys


def render_goal(session: dict) -> str:
    return f"STANDING GOAL (UNTRUSTED USER GOAL):\n{session.get('goal', '').strip() or '(none)'}"


def _proposal_label(proposal: dict) -> str:
    if proposal.get("kind") == "source":
        return str((proposal.get("source") or {}).get("company", "")).strip()
    term = proposal.get("term") or {}
    return f'{term.get("term_kind", "term")} "{str(term.get("value", "")).strip()}"'


def render_ledger(session: dict) -> str:
    proposals = session.get("proposals", [])
    added = [_proposal_label(row) for row in proposals if row.get("status") == "added"]
    dismissed = [row for row in proposals if row.get("status") == "dismissed"]
    recent = dismissed[-_DISMISSAL_LEDGER_CAP:]
    lines = ["FEEDBACK LEDGER (UNTRUSTED USER FEEDBACK):"]
    lines.append("ALREADY ADDED: " + (", ".join(filter(None, added)) or "(none)"))
    lines.append("DISMISSED — DO NOT PROPOSE AGAIN:")
    lines.extend(
        f"- {_proposal_label(row)} — user said: {row.get('dismiss_reason') or '(no reason given)'}"
        for row in recent
    )
    if not recent:
        lines.append("(none)")
    if len(dismissed) > len(recent):
        lines.append(f"[… {len(dismissed) - len(recent)} older dismissals omitted …]")
    return "\n".join(lines)


def render_transcript(session: dict, char_cap: int = TRANSCRIPT_CHAR_CAP) -> str:
    header = "TRANSCRIPT (UNTRUSTED USER AND MODEL DATA):"
    turn_lines = [
        f"{str(turn.get('role', '')).upper()}: {str(turn.get('text', '')).strip()}"
        + (f"\nNOTICE: {turn['notice']}" if turn.get("notice") else "")
        for turn in session.get("turns", [])
    ]
    body = "\n".join(turn_lines)
    rendered = f"{header}\n{body}"
    if len(rendered) <= char_cap:
        return rendered
    marker = "[… older turns elided …]"
    available = max(char_cap - len(header) - len(marker) - 2, 0)
    kept: list[str] = []
    used = 0
    for line in reversed(turn_lines):
        cost = len(line) + (1 if kept else 0)
        if used + cost > available:
            break
        kept.append(line)
        used += cost
    tail = "\n".join(reversed(kept))
    return f"{header}\n{marker}" + (f"\n{tail}" if tail else "")
