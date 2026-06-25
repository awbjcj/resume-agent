"""Error-isolated concurrent fan-out for LLM calls.

asyncio (not threads) keeps SQLModel Session reads/writes on one thread. Only
the leaf network calls run concurrently, bounded by the semaphore threaded into
``resume_agent.llm_runner.acall``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class Result(Generic[R]):
    """Outcome of one fanned-out call: a value on success, else the exception."""

    ok: bool
    value: R | None = None
    error: Exception | None = None


async def gather_isolated(
    items: Sequence[T],
    fn: Callable[[T], Awaitable[R]],
    *,
    on_complete: Callable[[int], None] | None = None,
) -> list[Result[R]]:
    """Run ``fn(item)`` for every item concurrently; results stay in input order."""
    results: list[Result[R]] = [Result(ok=False) for _ in items]
    completed = 0

    async def run_one(index: int, item: T) -> None:
        nonlocal completed
        try:
            results[index] = Result(ok=True, value=await fn(item))
        except Exception as exc:
            results[index] = Result(ok=False, error=exc)
        finally:
            completed += 1
            if on_complete is not None:
                try:
                    on_complete(completed)
                except Exception:
                    # Progress reporting is best-effort. A transient write
                    # failure (e.g. a Windows os.replace sharing violation, the
                    # same race read_progress already retries around) must not
                    # escape this finally: the outer gather runs without
                    # return_exceptions, so it would abort the whole fan-out and
                    # discard every sibling's in-flight LLM result.
                    pass

    await asyncio.gather(*(run_one(i, item) for i, item in enumerate(items)))
    return results
