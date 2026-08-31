"""Pooled, retrying, timeout-owning HTTP for **configured** board endpoints.

Every ATS connector used to call module-level ``httpx.get(...)``. That builds a
fresh ``Client`` per call, and a fresh client is a fresh connection pool: a new
TCP connection and a new TLS handshake for every request. A board pull is
list-then-detail against a *single host* — exactly the shape a keep-alive pool
exists for — so the work was being paid per request instead of per host.

Two adapters for "talk HTTP carefully" already existed: ``workday.py``'s
throttle retry (which only Workday had) and ``security/outbound.py``'s pinned,
byte-capped, redirect-revalidating gateway. One is a hypothetical seam; two is a
real one. This is the third thing they were both approximating — a pool — and
it absorbs the retry and the ``timeout=30`` that had been copy-pasted across
fifteen modules.

**Scope is deliberately narrow.** This serves endpoints the *operator*
configured: a Greenhouse board token, a Workday tenant, an ATS API URL rebuilt
from a validated ``AtsTarget``. It is **not** for user-supplied URLs. Those keep
going through ``security/outbound.py``, whose address pinning, per-hop redirect
revalidation, and byte caps are mandatory and are not re-implemented here.

Nor is this session handed to ``fetch_public_text`` as its client, even though
that function accepts one. The gateway pins each request to the IP it validated
and carries the real hostname in an ``sni_hostname`` extension — but httpx keys
its connection pool on the request URL's origin, which for a pinned request is
the *IP*. A shared pool would therefore be free to hand a connection negotiated
with one hostname's SNI to a request intended for a different hostname that
resolves to the same address. A per-call client cannot do that, which is why
the gateway builds its own. Pooling there needs a pool keyed by SNI, not this
one.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

import httpx

__all__ = [
    "DEFAULT_TIMEOUT",
    "RETRY_STATUSES",
    "BoardSession",
    "board_session",
    "current_session",
    "get",
    "post",
]

# One timeout for every board endpoint. It lived as a bare ``timeout=30`` in
# roughly fifteen modules, which meant it could only ever be changed in fifteen
# places or not at all.
DEFAULT_TIMEOUT = 30.0

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_ATTEMPTS = 4  # one initial call plus three retries
RETRY_BACKOFF_S = 2.0  # exponential base when the server sends no Retry-After
MAX_RETRY_SLEEP_S = 30.0

# A board pull talks to few hosts and many paths, so the pool is sized for depth
# per host rather than breadth across hosts.
MAX_CONNECTIONS = 32
MAX_KEEPALIVE_CONNECTIONS = 16


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds from a numeric ``Retry-After``; ``None`` for absent/date/garbage."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None  # the HTTP-date form is rare here; fall back to backoff


class BoardSession:
    """A pooled HTTP client with the board-endpoint retry policy built in.

    ``get``/``post`` keep ``httpx.get``'s contract — they return the response
    and do **not** raise for status — so a call site that tolerates a 404, or
    checks the status itself, behaves exactly as before. The only difference is
    that a transient status is retried before that response comes back.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        attempts: int = RETRY_ATTEMPTS,
        transport: httpx.BaseTransport | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._attempts = max(1, attempts)
        self._client = httpx.Client(
            # HTTP/2 multiplexes, which matters most for the detail fan-out
            # where many requests target one host at once.
            http2=True,
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=MAX_CONNECTIONS,
                max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
            ),
            transport=transport,
            headers=headers,
        )

    @property
    def client(self) -> httpx.Client:
        """The underlying client, for callers that already accept one."""
        return self._client

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(self._attempts):
            response = self._client.request(method, url, **kwargs)
            if response.status_code not in RETRY_STATUSES:
                return response
            last = response
            if attempt + 1 >= self._attempts:
                break
            delay = _retry_after_seconds(response)
            if delay is None:
                delay = RETRY_BACKOFF_S * (2**attempt)
            time.sleep(min(delay, MAX_RETRY_SLEEP_S))
        assert last is not None  # the loop runs at least once
        return last

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BoardSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


_current: ContextVar[BoardSession | None] = ContextVar("board_session", default=None)


@contextmanager
def board_session(session: BoardSession | None = None) -> Iterator[BoardSession]:
    """Install one pooled session for the duration of a pull run.

    Scoped rather than process-global so a run's connections are released when
    the run ends, and so a test can install its own transport without leaking
    into the next test.
    """
    owned = session is None
    active = session or BoardSession()
    token = _current.set(active)
    try:
        yield active
    finally:
        _current.reset(token)
        if owned:
            active.close()


def current_session() -> BoardSession | None:
    """The run-scoped session, if a pull installed one."""
    return _current.get()


def _resolve() -> tuple[BoardSession, bool]:
    active = _current.get()
    if active is not None:
        return active, False
    # No run installed one — a single-connector CLI path or a direct call. A
    # private session keeps behaviour identical, just without the reuse.
    return BoardSession(), True


def get(url: str, **kwargs: Any) -> httpx.Response:
    """GET a configured board endpoint through the run's pool."""
    session, private = _resolve()
    try:
        return session.get(url, **kwargs)
    finally:
        if private:
            session.close()


def post(url: str, **kwargs: Any) -> httpx.Response:
    """POST to a configured board endpoint through the run's pool."""
    session, private = _resolve()
    try:
        return session.post(url, **kwargs)
    finally:
        if private:
            session.close()
