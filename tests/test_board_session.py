"""BoardSession: one pool, one timeout, one retry policy for board endpoints."""

from __future__ import annotations

import httpx
import pytest

from resume_agent.discovery.connectors.http import (
    DEFAULT_TIMEOUT,
    BoardSession,
    board_session,
    current_session,
)
from resume_agent.discovery.connectors import http as board


class _Recorder(httpx.BaseTransport):
    """A transport that answers from a script and counts what it was asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.script = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.script.pop(0) if self.script else httpx.Response(200, json={})
        response.request = request
        return response


def test_many_requests_to_one_host_share_a_single_client(monkeypatch):
    """A board pull is list-then-detail against one host: pool, don't handshake."""
    opened = 0
    original = httpx.Client.__init__

    def _counting_init(self, *args, **kwargs):
        nonlocal opened
        opened += 1
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", _counting_init)

    with BoardSession(transport=_Recorder()) as session:
        for index in range(10):
            session.get(f"https://boards-api.greenhouse.io/v1/boards/t{index}")

    assert opened == 1


def test_a_transient_status_is_retried_and_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    transport = _Recorder(
        httpx.Response(429, headers={"retry-after": "0"}),
        httpx.Response(200, json={"jobs": [{"id": 1}]}),
    )

    with BoardSession(transport=transport) as session:
        response = session.get("https://acme.wd5.myworkdayjobs.com/x")

    assert response.status_code == 200
    assert len(transport.requests) == 2


def test_a_non_transient_status_is_returned_without_retrying():
    """A 404 is an answer. Retrying it burns the budget for a real throttle."""
    transport = _Recorder(httpx.Response(404))

    with BoardSession(transport=transport) as session:
        response = session.get("https://boards-api.greenhouse.io/v1/boards/nope")

    assert response.status_code == 404
    assert len(transport.requests) == 1


def test_retries_are_bounded_and_the_last_response_is_returned(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    transport = _Recorder(*[httpx.Response(503) for _ in range(10)])

    with BoardSession(transport=transport, attempts=4) as session:
        response = session.get("https://acme.wd5.myworkdayjobs.com/x")

    assert response.status_code == 503
    assert len(transport.requests) == 4


def test_a_numeric_retry_after_is_honoured_over_the_backoff(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))
    transport = _Recorder(
        httpx.Response(429, headers={"retry-after": "7"}),
        httpx.Response(200, json={}),
    )

    with BoardSession(transport=transport) as session:
        session.get("https://acme.wd5.myworkdayjobs.com/x")

    assert slept == [7.0]


def test_a_garbage_retry_after_falls_back_to_exponential_backoff(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))
    transport = _Recorder(
        httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200, json={}),
    )

    with BoardSession(transport=transport) as session:
        session.get("https://acme.wd5.myworkdayjobs.com/x")

    assert slept == [2.0]


def test_the_session_owns_the_timeout():
    """The constant lived as a bare `timeout=30` in about fifteen modules."""
    with BoardSession(transport=_Recorder()) as session:
        assert session.client.timeout.connect == DEFAULT_TIMEOUT
        assert session.client.timeout.read == DEFAULT_TIMEOUT


def test_module_level_helpers_use_the_run_scoped_session():
    transport = _Recorder(httpx.Response(200, json={"ok": True}))

    with board_session(BoardSession(transport=transport)) as session:
        assert current_session() is session
        response = board.get("https://boards-api.greenhouse.io/v1/boards/t")

    assert response.json() == {"ok": True}
    assert current_session() is None


def test_a_call_outside_a_run_still_works_on_a_private_session(monkeypatch):
    """Single-connector CLI paths never installed a session; they must still work."""
    transport = _Recorder(httpx.Response(200, json={"ok": True}))
    monkeypatch.setattr(
        board, "_resolve", lambda: (BoardSession(transport=transport), True)
    )

    assert current_session() is None
    assert board.get("https://boards-api.greenhouse.io/v1/boards/t").status_code == 200


def test_the_run_scoped_session_closes_when_the_run_ends():
    with board_session() as session:
        assert session.client.is_closed is False
    assert session.client.is_closed is True


def test_a_supplied_session_is_not_closed_by_the_scope():
    """The caller that built it owns it."""
    session = BoardSession(transport=_Recorder())
    with board_session(session):
        pass
    assert session.client.is_closed is False
    session.close()


@pytest.mark.parametrize("method", ["get", "post"])
def test_both_verbs_share_the_pool_and_the_policy(monkeypatch, method):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    transport = _Recorder(httpx.Response(503), httpx.Response(200, json={}))

    with BoardSession(transport=transport) as session:
        response = getattr(session, method)("https://acme.wd5.myworkdayjobs.com/x")

    assert response.status_code == 200
    assert [request.method for request in transport.requests] == [
        method.upper(),
        method.upper(),
    ]
