from dataclasses import dataclass
from typing import Any

from resume_agent.llm_runner import Runner


@dataclass(frozen=True)
class UsageTotals:
    calls: int = 0
    failed_calls: int = 0
    metrics_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration: float = 0.0
    cost: float | None = None


class UsageCollector:
    def __init__(self) -> None:
        self._calls = 0
        self._failed_calls = 0
        self._metrics_calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._total_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._duration = 0.0
        self._cost = 0.0
        self._cost_complete = True

    def start_call(self) -> None:
        self._calls += 1

    def fail_call(self) -> None:
        self._failed_calls += 1

    def observe(self, result: Any) -> None:
        metrics = getattr(result, "metrics", None)
        if metrics is None:
            self._cost_complete = False
            return
        self._metrics_calls += 1
        self._input_tokens += getattr(metrics, "input_tokens", 0) or 0
        self._output_tokens += getattr(metrics, "output_tokens", 0) or 0
        self._total_tokens += getattr(metrics, "total_tokens", 0) or 0
        self._cache_read_tokens += getattr(metrics, "cache_read_tokens", 0) or 0
        self._cache_write_tokens += getattr(metrics, "cache_write_tokens", 0) or 0
        self._duration += getattr(metrics, "duration", 0.0) or 0.0
        cost = getattr(metrics, "cost", None)
        if cost is None:
            self._cost_complete = False
        else:
            self._cost += cost

    def snapshot(self) -> UsageTotals:
        cost = (
            self._cost
            if self._metrics_calls > 0 and self._cost_complete
            else None
        )
        return UsageTotals(
            calls=self._calls,
            failed_calls=self._failed_calls,
            metrics_calls=self._metrics_calls,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            total_tokens=self._total_tokens,
            cache_read_tokens=self._cache_read_tokens,
            cache_write_tokens=self._cache_write_tokens,
            duration=self._duration,
            cost=cost,
        )


class MeteredRunner:
    def __init__(self, delegate: Runner, collector: UsageCollector) -> None:
        self._delegate = delegate
        self._collector = collector

    def run(self, prompt: str) -> Any:
        self._collector.start_call()
        try:
            result = self._delegate.run(prompt)
        except Exception:
            self._collector.fail_call()
            raise
        self._collector.observe(result)
        return result

    async def arun(self, prompt: str) -> Any:
        self._collector.start_call()
        try:
            result = await self._delegate.arun(prompt)
        except Exception:
            self._collector.fail_call()
            raise
        self._collector.observe(result)
        return result
