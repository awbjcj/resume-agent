from types import SimpleNamespace

import pytest

from evals.usage import MeteredRunner, UsageCollector


class _Result:
    def __init__(self, content, metrics=None):
        self.content = content
        self.metrics = metrics


def _metrics(
    *,
    input_tokens=0,
    output_tokens=0,
    total_tokens=0,
    cache_read_tokens=0,
    cache_write_tokens=0,
    duration=None,
    cost=None,
):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        duration=duration,
        cost=cost,
    )


class _SyncDelegate:
    def __init__(self, results):
        self._results = iter(results)

    def run(self, prompt):
        return next(self._results)


class _AsyncDelegate:
    def __init__(self, result):
        self._result = result

    async def arun(self, prompt):
        return self._result


def test_metered_runner_accumulates_sync_metrics_and_preserves_result():
    collector = UsageCollector()
    first = _Result(
        "first",
        _metrics(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cache_read_tokens=2,
            duration=0.25,
            cost=0.01,
        ),
    )
    second = _Result(
        "second",
        _metrics(
            input_tokens=20,
            output_tokens=7,
            total_tokens=27,
            cache_write_tokens=3,
            duration=0.75,
            cost=0.02,
        ),
    )
    runner = MeteredRunner(_SyncDelegate([first, second]), collector)

    returned_first = runner.run("one")
    returned_second = runner.run("two")
    usage = collector.snapshot()

    assert returned_first is first and returned_first.content == "first"
    assert returned_second is second and returned_second.content == "second"
    assert usage.calls == 2
    assert usage.failed_calls == 0
    assert usage.metrics_calls == 2
    assert usage.input_tokens == 30
    assert usage.output_tokens == 12
    assert usage.total_tokens == 42
    assert usage.cache_read_tokens == 2
    assert usage.cache_write_tokens == 3
    assert usage.duration == 1.0
    assert usage.cost == pytest.approx(0.03)


async def test_metered_runner_observes_async_result():
    collector = UsageCollector()
    result = _Result(
        {"value": 1},
        _metrics(input_tokens=4, output_tokens=2, total_tokens=6, cost=0.005),
    )

    returned = await MeteredRunner(_AsyncDelegate(result), collector).arun("prompt")
    usage = collector.snapshot()

    assert returned is result
    assert returned.content == {"value": 1}
    assert usage.calls == 1
    assert usage.metrics_calls == 1
    assert usage.total_tokens == 6
    assert usage.cost == 0.005


def test_no_metrics_counts_call_and_keeps_cost_unknown():
    collector = UsageCollector()

    MeteredRunner(_SyncDelegate([_Result("ok")]), collector).run("prompt")
    usage = collector.snapshot()

    assert usage.calls == 1
    assert usage.failed_calls == 0
    assert usage.metrics_calls == 0
    assert usage.cost is None


def test_missing_cost_on_metrics_makes_aggregate_cost_unknown():
    collector = UsageCollector()
    runner = MeteredRunner(
        _SyncDelegate(
            [
                _Result("priced", _metrics(total_tokens=1, cost=0.01)),
                _Result("unpriced", _metrics(total_tokens=2, cost=None)),
            ]
        ),
        collector,
    )

    runner.run("one")
    runner.run("two")
    usage = collector.snapshot()

    assert usage.metrics_calls == 2
    assert usage.total_tokens == 3
    assert usage.cost is None


def test_raising_delegate_counts_failure_and_reraises_same_error():
    class _RaisingDelegate:
        def run(self, prompt):
            raise error

    error = RuntimeError("provider failed")
    collector = UsageCollector()

    with pytest.raises(RuntimeError) as caught:
        MeteredRunner(_RaisingDelegate(), collector).run("prompt")

    usage = collector.snapshot()
    assert caught.value is error
    assert usage.calls == 1
    assert usage.failed_calls == 1
    assert usage.metrics_calls == 0
    assert usage.cost is None
