"""Thread-safe wakeups for readers of durable run streams."""

from __future__ import annotations

import asyncio
import threading


class StreamNotifier:
    """Fan append notifications from worker threads out to async subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}

    def subscribe(self) -> asyncio.Event:
        event = asyncio.Event()
        with self._lock:
            self._subscribers[event] = asyncio.get_running_loop()
        return event

    def unsubscribe(self, event: asyncio.Event) -> None:
        with self._lock:
            self._subscribers.pop(event, None)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def notify(self) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.items())
        stale: list[asyncio.Event] = []
        for event, loop in subscribers:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                stale.append(event)
        if stale:
            with self._lock:
                for event in stale:
                    self._subscribers.pop(event, None)
