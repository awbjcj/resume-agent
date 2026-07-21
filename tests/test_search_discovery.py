from dataclasses import dataclass
from typing import Any

import yaml


@dataclass
class _FakeResponse:
    content: Any


class _FakeRunner:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResponse(self._content)

    async def arun(self, prompt):
        return _FakeResponse(self._content)


class _Reporter:
    def begin(self, *a, **k):
        pass

    def step(self, *a, **k):
        pass

    def checkpoint(self, *a, **k):
        pass


def test_run_search_discovery_dedupes_against_existing(tmp_path):
    from resume_agent.discovery.search_scout import SearchSuggestion, SearchSuggestions
    from resume_agent.services.search_discovery import run_search_discovery

    search_path = tmp_path / "search.yaml"
    search_path.write_text(yaml.safe_dump({"keywords": ["python"], "titles": []}))

    report = SearchSuggestions(
        suggestions=[
            SearchSuggestion(value="Python", kind="keyword", reason="dup"),
            SearchSuggestion(value="Rust", kind="keyword", reason="new"),
        ]
    )
    result = run_search_discovery(
        _Reporter(),
        prompt="platform roles",
        search_path=str(search_path),
        profile_dir=tmp_path,
        research_agent=_FakeRunner("notes"),
        formatter_agent=_FakeRunner(report),
    )
    by_value = {s["value"]: s["status"] for s in result["suggestions"]}
    assert by_value["Python"] == "duplicate"
    assert by_value["Rust"] == "new"
    assert result["prompt"] == "platform roles"


def test_run_search_discovery_dedupe_is_per_kind(tmp_path):
    from resume_agent.discovery.search_scout import SearchSuggestion, SearchSuggestions
    from resume_agent.services.search_discovery import run_search_discovery

    search_path = tmp_path / "search.yaml"
    search_path.write_text(yaml.safe_dump({"keywords": ["python"], "titles": []}))

    report = SearchSuggestions(
        suggestions=[
            # Same term "python" but as a title, not a keyword -> not a dup.
            SearchSuggestion(value="Python", kind="title", reason="role"),
        ]
    )
    result = run_search_discovery(
        _Reporter(),
        prompt="x",
        search_path=str(search_path),
        profile_dir=tmp_path,
        research_agent=_FakeRunner("notes"),
        formatter_agent=_FakeRunner(report),
    )
    assert result["suggestions"][0]["status"] == "new"


def test_scout_search_context_tolerates_missing_artifacts(tmp_path):
    from resume_agent.services.search_discovery import scout_search_context

    context = scout_search_context(str(tmp_path / "search.yaml"), tmp_path)
    assert "CURRENT KEYWORDS" in context
    assert "PROFILE TOP SKILLS" in context
