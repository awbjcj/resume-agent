"""Bounded web-search support and coverage accounting for Discovery Scout."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from resume_tailor_harness.discovery.source_resolution.catalog import BOARD_FAMILIES
from resume_tailor_harness.sessions.stream import (
    StreamEvent,
    StreamSink,
    ToolCompleted,
    ToolStarted,
)

SearchInterruption = Literal["SEARCH_RATE_LIMITED", "SEARCH_BUDGET_EXHAUSTED"]


@dataclass
class SearchBudget:
    max_uses: int = 5
    used: int = 0
    rate_limited: bool = False
    queries: list[str] = field(default_factory=list)

    def reserve(self, query: str) -> SearchInterruption | None:
        if self.rate_limited:
            return "SEARCH_RATE_LIMITED"
        if self.used >= self.max_uses:
            return "SEARCH_BUDGET_EXHAUSTED"
        self.used += 1
        self.queries.append(query)
        return None


def _error_payload(code: SearchInterruption) -> str:
    return json.dumps({"ok": False, "error_code": code, "results": []})


def make_budgeted_web_search_tool(budget: SearchBudget, *, backend=None):
    """Return a five-use web search function suitable for an Agno tool list."""

    if backend is None:
        from agno.tools.duckduckgo import DuckDuckGoTools

        backend = DuckDuckGoTools(
            enable_news=False,
            fixed_max_results=5,
        ).web_search

    def web_search(query: str) -> str:
        """Search the public web for company careers pages and ATS boards.

        Args:
            query: A focused public-web search query.
        """

        if error := budget.reserve(query):
            return _error_payload(error)
        try:
            return backend(query, 5)
        except RatelimitException:
            budget.rate_limited = True
            return _error_payload("SEARCH_RATE_LIMITED")
        except TimeoutException:
            return _error_payload("SEARCH_BUDGET_EXHAUSTED")
        except DDGSException:
            return json.dumps({"ok": True, "results": []})

    return web_search


@dataclass(frozen=True)
class SearchCoverage:
    searched_families: list[str]
    unsearched_families: list[str]
    interruption_reason: SearchInterruption | None = None


class SearchCoverageSink:
    """Observe Scout search events without changing their delivery order or data."""

    def __init__(self, downstream: StreamSink) -> None:
        self._downstream = downstream
        self._searched_families: set[str] = set()
        self._interruption_reason: SearchInterruption | None = None

    def emit(self, event: StreamEvent) -> None:
        if isinstance(event, ToolStarted) and "web_search" in event.name.casefold():
            self._record_query(event.args_preview)
        elif isinstance(event, ToolCompleted) and "web_search" in event.name.casefold():
            self._record_result(event.result_preview)
        self._downstream.emit(event)

    def close(self) -> None:
        self._downstream.close()

    def snapshot(self) -> SearchCoverage:
        kinds = [family.kind for family in BOARD_FAMILIES]
        searched = [kind for kind in kinds if kind in self._searched_families]
        return SearchCoverage(
            searched_families=searched,
            unsearched_families=[
                kind for kind in kinds if kind not in self._searched_families
            ],
            interruption_reason=self._interruption_reason,
        )

    def _record_query(self, query: str) -> None:
        query = query.casefold()
        for family in BOARD_FAMILIES:
            if any(host.casefold() in query for host in family.search_hosts):
                self._searched_families.add(family.kind)

    def _record_result(self, result: str) -> None:
        result = result.casefold()
        if "search_rate_limited" in result or "rate limit" in result:
            self._interruption_reason = "SEARCH_RATE_LIMITED"
        elif "search_budget_exhausted" in result and self._interruption_reason is None:
            self._interruption_reason = "SEARCH_BUDGET_EXHAUSTED"
