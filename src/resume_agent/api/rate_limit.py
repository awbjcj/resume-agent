from __future__ import annotations

import threading
import time


class FailedAttemptLimiter:
    def __init__(self, max_failures: int = 10, window_seconds: float = 900.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        cutoff = now - self.window_seconds
        current = [value for value in self._failures.get(key, ()) if value > cutoff]
        if current:
            self._failures[key] = current
        else:
            self._failures.pop(key, None)
        return current

    def blocked(self, username: str, ip: str, *, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        with self._lock:
            return (
                len(self._prune((username.casefold(), ip), moment)) >= self.max_failures
            )

    def record_failure(
        self, username: str, ip: str, *, now: float | None = None
    ) -> None:
        moment = time.time() if now is None else now
        with self._lock:
            key = (username.casefold(), ip)
            self._prune(key, moment)
            self._failures.setdefault(key, []).append(moment)

    def reset(self, username: str, ip: str) -> None:
        with self._lock:
            self._failures.pop((username.casefold(), ip), None)
