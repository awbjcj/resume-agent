from dataclasses import dataclass
from typing import Any

import yaml

from resume_agent.discovery.scout_models import Citation
from resume_agent.discovery.search_scout import SearchSuggestion, SearchSuggestions
from resume_agent.services.search_discovery import run_search_discovery


@dataclass
class _Response:
    content: Any


class _Runner:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return _Response(self.content)


class _Reporter:
    def begin(self, *_args, **_kwargs):
        pass

    def step(self, *_args, **_kwargs):
        pass


def _run(tmp_path, suggestions, existing=None):
    search_path = tmp_path / "search.yaml"
    search_path.write_text(yaml.safe_dump(existing or {}), encoding="utf-8")
    return run_search_discovery(
        _Reporter(),
        prompt="p",
        search_path=str(search_path),
        profile_dir=tmp_path,
        research_agent=_Runner("notes"),
        formatter_agent=_Runner(SearchSuggestions(suggestions=suggestions)),
    )


def test_new_kinds_dedupe_against_their_config_destinations(tmp_path):
    result = _run(
        tmp_path,
        [
            SearchSuggestion(value="Berlin", kind="location", fit_score=80),
            SearchSuggestion(value="mid-senior", kind="seniority", fit_score=70),
            SearchSuggestion(value="Architect", kind="title", fit_score=60),
            SearchSuggestion(value="architect", kind="adjacent_role", fit_score=95),
        ],
        existing={"locations": ["Berlin"], "experience_levels": ["entry"]},
    )

    assert [(row["kind"], row["status"]) for row in result["suggestions"]] == [
        ("seniority", "new"),
        ("title", "new"),
        ("location", "duplicate"),
    ]


def test_search_rows_rank_and_filter_unsafe_citations(tmp_path):
    result = _run(
        tmp_path,
        [
            SearchSuggestion(value="low", kind="keyword", fit_score=20),
            SearchSuggestion(
                value="high",
                kind="keyword",
                fit_score=95,
                citations=[
                    Citation(url="https://example.test/high", title="High"),
                    Citation(url="file:///secret", title="unsafe"),
                ],
            ),
        ],
    )

    assert [row["value"] for row in result["suggestions"]] == ["high", "low"]
    assert result["suggestions"][0]["citations"] == [
        {"url": "https://example.test/high", "title": "High"}
    ]
