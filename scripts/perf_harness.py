"""Deterministic counters for the units the architecture plan says scale wrongly.

Three context managers, one per finding class:

* :func:`count_queries` — DB round trips per LLM call (spend metering per *call*
  instead of per *phase*).
* :func:`count_connections` — TCP/TLS setup per HTTP request (a fresh client per
  request instead of a pool per host).
* :func:`count_prompt_tokens` — full-price input tokens per run (a run-constant
  document re-sent in the one message kind agno cannot cache).

Every counter is exact and offline: nothing here samples, times, or talks to a
network. That is deliberate — a perf assertion that depends on wall clock is a
flaky test, and the numbers these produce are asserted on in
``tests/perf/test_baselines.py`` so a regression fails CI rather than being
noticed in a bill.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

__all__ = [
    "ConnectionCounts",
    "QueryCounts",
    "TokenCounts",
    "count_connections",
    "count_prompt_tokens",
    "count_queries",
]


# Statement prefixes worth separating. ``BEGIN IMMEDIATE`` takes SQLite's
# exclusive write lock, so it is counted apart from ordinary reads: ten selects
# and ten exclusive transactions are very different costs under concurrency.
_KINDS = (
    "BEGIN IMMEDIATE",
    "BEGIN DEFERRED",
    "BEGIN",
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "PRAGMA",
)


def _kind(statement: str) -> str:
    text = " ".join(statement.strip().split()).upper()
    for prefix in _KINDS:
        if text.startswith(prefix):
            return prefix
    return "OTHER"


@dataclass
class QueryCounts:
    """Statements executed against one engine, bucketed by prefix."""

    by_kind: Counter[str] = field(default_factory=Counter)
    statements: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.by_kind.values())

    @property
    def reads(self) -> int:
        return self.by_kind["SELECT"]

    @property
    def exclusive_transactions(self) -> int:
        return self.by_kind["BEGIN IMMEDIATE"]

    def per_unit(self, units: int) -> float:
        return self.total / units if units else 0.0

    def __str__(self) -> str:
        parts = ", ".join(f"{kind}={n}" for kind, n in sorted(self.by_kind.items()))
        return f"{self.total} statements ({parts})"


@contextmanager
def count_queries(engine: Engine, *, record_sql: bool = False) -> Iterator[QueryCounts]:
    """Count every statement ``engine`` executes inside the block.

    Hooks ``before_cursor_execute`` rather than wrapping ``Session`` so that
    statements issued by nested helpers — which is exactly where the duplicated
    spend derivation hides — are counted too.
    """
    counts = QueryCounts()

    def _on_execute(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        counts.by_kind[_kind(statement)] += 1
        if record_sql:
            counts.statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


@dataclass
class ConnectionCounts:
    """HTTP clients opened versus requests issued.

    A pooled transport keeps ``clients`` flat while ``requests`` grows; a
    module-level ``httpx.get`` per call makes them move together. The ratio is
    the measurement, not either number alone.
    """

    clients: int = 0
    requests: int = 0
    hosts: Counter[str] = field(default_factory=Counter)

    @property
    def requests_per_client(self) -> float:
        return self.requests / self.clients if self.clients else 0.0

    @property
    def distinct_hosts(self) -> int:
        return len(self.hosts)

    def __str__(self) -> str:
        return (
            f"{self.requests} requests over {self.clients} clients "
            f"({self.requests_per_client:.1f} per client), "
            f"{self.distinct_hosts} host(s)"
        )


@contextmanager
def count_connections() -> Iterator[ConnectionCounts]:
    """Count httpx client construction and request dispatch inside the block.

    Client construction stands in for connection setup: httpx opens a fresh
    pool per client, so a per-request client is a per-request TCP+TLS handshake.
    Counting construction rather than sockets keeps the measurement exact under
    a mock transport, which is how the offline suite runs.
    """
    import httpx

    counts = ConnectionCounts()
    client_init = httpx.Client.__init__
    async_client_init = httpx.AsyncClient.__init__
    client_send = httpx.Client.send
    async_client_send = httpx.AsyncClient.send

    def _init(self: Any, *args: Any, **kwargs: Any) -> None:
        counts.clients += 1
        client_init(self, *args, **kwargs)

    def _ainit(self: Any, *args: Any, **kwargs: Any) -> None:
        counts.clients += 1
        async_client_init(self, *args, **kwargs)

    def _send(self: Any, request: Any, **kwargs: Any) -> Any:
        counts.requests += 1
        counts.hosts[request.url.host] += 1
        return client_send(self, request, **kwargs)

    async def _asend(self: Any, request: Any, **kwargs: Any) -> Any:
        counts.requests += 1
        counts.hosts[request.url.host] += 1
        return await async_client_send(self, request, **kwargs)

    httpx.Client.__init__ = _init  # type: ignore[method-assign]
    httpx.AsyncClient.__init__ = _ainit  # type: ignore[method-assign]
    httpx.Client.send = _send  # type: ignore[method-assign]
    httpx.AsyncClient.send = _asend  # type: ignore[method-assign]
    try:
        yield counts
    finally:
        httpx.Client.__init__ = client_init  # type: ignore[method-assign]
        httpx.AsyncClient.__init__ = async_client_init  # type: ignore[method-assign]
        httpx.Client.send = client_send  # type: ignore[method-assign]
        httpx.AsyncClient.send = async_client_send  # type: ignore[method-assign]


@dataclass
class TokenCounts:
    """Prompt-token split across every recorded call inside the block."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def full_price_input(self) -> int:
        """Input tokens billed at 1x — the number prompt caching moves."""
        return self.input_tokens

    def per_call(self, field_name: str) -> float:
        return getattr(self, field_name) / self.calls if self.calls else 0.0

    def __str__(self) -> str:
        return (
            f"{self.calls} calls: in={self.input_tokens} out={self.output_tokens} "
            f"cache_read={self.cache_read_tokens} cache_write={self.cache_write_tokens}"
        )


def _token(metrics: Any, name: str) -> int:
    value = getattr(metrics, name, None)
    if value is None and isinstance(metrics, dict):
        value = metrics.get(name)
    if isinstance(value, (list, tuple)):
        value = sum(item or 0 for item in value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@contextmanager
def count_prompt_tokens() -> Iterator[TokenCounts]:
    """Tally token metrics off the ``record_call`` path.

    Wraps the recorder rather than the agent so the count is identical to what
    billing sees, and works with or without an active tenancy context (the real
    recorder returns early without one; the tally must not).
    """
    from resume_tailor_harness.tenancy import usage as usage_module

    counts = TokenCounts()
    original = usage_module.record_call

    def _record(agent: Any, response: Any) -> None:
        metrics = getattr(response, "metrics", None)
        if metrics is not None:
            counts.calls += 1
            counts.input_tokens += _token(metrics, "input_tokens")
            counts.output_tokens += _token(metrics, "output_tokens")
            counts.cache_read_tokens += _token(metrics, "cache_read_tokens")
            counts.cache_write_tokens += _token(
                metrics, "cache_write_tokens"
            ) or _token(metrics, "cache_creation_tokens")
        original(agent, response)

    usage_module.record_call = _record  # type: ignore[assignment]
    try:
        yield counts
    finally:
        usage_module.record_call = original  # type: ignore[assignment]
