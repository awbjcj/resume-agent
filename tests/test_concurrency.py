import asyncio

from resume_agent.concurrency import Result, gather_isolated


def test_gather_isolated_preserves_order_and_isolates_errors():
    async def fn(x):
        await asyncio.sleep(0.01 * (3 - x))
        if x == 1:
            raise ValueError("boom")
        return x * 10

    results = asyncio.run(gather_isolated([0, 1, 2], fn))

    assert results[0].ok and results[0].value == 0
    assert (not results[1].ok) and isinstance(results[1].error, ValueError)
    assert results[2].ok and results[2].value == 20


def test_gather_isolated_reports_completion_count():
    seen: list[int] = []

    async def fn(x):
        await asyncio.sleep(0.001)
        return x

    asyncio.run(gather_isolated([0, 1, 2], fn, on_complete=seen.append))
    assert sorted(seen) == [1, 2, 3]


def test_gather_isolated_empty():
    assert asyncio.run(gather_isolated([], lambda x: x)) == []  # type: ignore[arg-type]


def test_gather_isolated_cancels_in_flight_tasks_when_checkpoint_raises():
    class StopRun(Exception):
        pass

    cancelled = 0
    checks = 0

    async def fn(x):
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
            return x
        except asyncio.CancelledError:
            cancelled += 1
            raise

    def checkpoint():
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise StopRun

    with __import__("pytest").raises(StopRun):
        asyncio.run(
            gather_isolated([0, 1, 2], fn, checkpoint=checkpoint, poll_interval=0.001)
        )

    assert cancelled == 3


def test_result_defaults():
    r = Result(ok=False)
    assert r.value is None and r.error is None
