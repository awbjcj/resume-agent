import json

from ddgs.exceptions import DDGSException, RatelimitException

from resume_agent.discovery.source_resolution.search import (
    SearchBudget,
    SearchCoverageSink,
    make_budgeted_web_search_tool,
)
from resume_agent.sessions.stream import ToolCompleted, ToolStarted


def test_fallback_search_opens_the_circuit_after_rate_limit():
    backend_calls = 0

    def backend(query: str, max_results: int = 5) -> str:
        nonlocal backend_calls
        del query, max_results
        backend_calls += 1
        raise RatelimitException("too many requests")

    search = make_budgeted_web_search_tool(SearchBudget(max_uses=5), backend=backend)

    first = json.loads(search("Intuitive careers"))
    second = json.loads(search("Tempus careers"))

    assert first["error_code"] == "SEARCH_RATE_LIMITED"
    assert second["error_code"] == "SEARCH_RATE_LIMITED"
    assert backend_calls == 1


def test_fallback_search_returns_empty_results_when_no_results_found():
    def backend(query: str, max_results: int = 5) -> str:
        del query, max_results
        raise DDGSException("No results found.")

    search = make_budgeted_web_search_tool(SearchBudget(max_uses=5), backend=backend)

    result = json.loads(search("Intuitive careers"))

    assert result == {"ok": True, "results": []}


def test_search_coverage_forwards_events_and_tracks_unsearched_families():
    class Sink:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)

        def close(self):
            pass

    downstream = Sink()
    sink = SearchCoverageSink(downstream)
    started = ToolStarted(
        "t1",
        "web_search",
        '"Intuitive" site:jobs.lever.co OR site:myworkdayjobs.com careers',
    )
    completed = ToolCompleted("t1", "web_search", '{"error_code":"SEARCH_RATE_LIMITED"}')

    sink.emit(started)
    sink.emit(completed)
    snapshot = sink.snapshot()

    assert downstream.events == [started, completed]
    assert snapshot.searched_families == ["lever", "workday"]
    assert "smartrecruiters" in snapshot.unsearched_families
    assert snapshot.interruption_reason == "SEARCH_RATE_LIMITED"
