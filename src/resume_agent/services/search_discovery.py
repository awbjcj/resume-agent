"""Search Scout context, per-kind dedupe, and run orchestration.

Mirrors ``services/source_discovery.py`` minus the validation fan-out: search
terms need no reachability probe, so this is research -> format -> dedupe.
"""

from __future__ import annotations

from pathlib import Path

from resume_agent.discovery.search_config import load_search_config
from resume_agent.discovery.scout_models import citation_rows
from resume_agent.discovery.search_scout import (
    MAX_SUGGESTIONS,
    SearchSuggestions,
    build_search_scout_formatter_agent,
    build_search_scout_research_agent,
)
from resume_agent.llm_runner import Runner, expect_schema
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts

_TOP_SKILLS = 15

# SearchSuggestion.kind -> the SearchConfig list field it dedupes against.
_EXISTING_FIELD = {
    "keyword": "keywords",
    "title": "titles",
    "role_anchor": "role_anchors",
    "exclude_term": "exclude_terms",
    "location": "locations",
    "seniority": "experience_levels",
    "adjacent_role": "titles",
}


def scout_search_context(search_path: str, profile_dir: Path) -> str:
    """Build compact grounding; every optional workspace artifact may be absent."""
    profile_dir = Path(profile_dir)
    titles: list[str] = []
    facts_path = profile_dir / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        titles = [row.title for row in facts.experience if row.title][:5]

    matrix = load_matrix(profile_dir / "matrix.json")
    skills = [row.display for row in matrix.rows][:_TOP_SKILLS] if matrix else []

    keywords: list[str] = []
    job_titles: list[str] = []
    anchors: list[str] = []
    excludes: list[str] = []
    try:
        search = load_search_config(search_path)
        keywords = list(search.keywords)
        job_titles = list(search.titles)
        anchors = list(search.role_anchors)
        excludes = list(search.exclude_terms)
    except (OSError, ValueError):
        pass

    def block(name: str, values: list[str]) -> str:
        body = "\n".join(f"- {value}" for value in values) if values else "(none)"
        return f"{name}:\n{body}"

    return "\n\n".join(
        [
            block("PROFILE RECENT TITLES", titles),
            block("PROFILE TOP SKILLS", skills),
            block("CURRENT KEYWORDS", keywords),
            block("CURRENT TITLES", job_titles),
            block("CURRENT ROLE ANCHORS", anchors),
            block("CURRENT EXCLUDE TERMS", excludes),
        ]
    )


def _existing_terms(search_path: str) -> dict[str, set[str]]:
    fields = set(_EXISTING_FIELD.values())
    try:
        search = load_search_config(search_path)
    except (OSError, ValueError):
        return {field: set() for field in fields}
    return {
        field: {term.casefold() for term in getattr(search, field, [])}
        for field in fields
    }


def run_search_discovery(
    reporter,
    *,
    prompt: str,
    search_path: str,
    profile_dir: Path,
    research_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    reporter.begin(1, "Scouting search terms", phase_index=0, phase_count=1)
    research = research_agent or build_search_scout_research_agent()
    formatter = formatter_agent or build_search_scout_formatter_agent()
    context = scout_search_context(search_path, Path(profile_dir))
    notes = research.run(f"USER PROMPT:\n{prompt}\n\n{context}").content
    result = formatter.run(f"RESEARCH NOTES (UNTRUSTED):\n{notes}")
    report = expect_schema(result, SearchSuggestions, source="search-scout")

    existing = _existing_terms(search_path)
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for suggestion in report.suggestions[:MAX_SUGGESTIONS]:
        value = suggestion.value.strip()
        if not value:
            continue
        kind = suggestion.kind
        fold = value.casefold()
        destination = _EXISTING_FIELD[kind]
        dedupe_key = (destination, fold)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        status = "duplicate" if fold in existing[destination] else "new"
        rows.append(
            {
                "value": value,
                "kind": kind,
                "reason": suggestion.reason,
                "status": status,
                "fitScore": suggestion.fit_score,
                "citations": citation_rows(suggestion.citations),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["status"] == "new" else 1,
            -row["fitScore"] if row["fitScore"] is not None else 1,
        )
    )
    reporter.step(1)
    return {"prompt": prompt, "suggestions": rows}
