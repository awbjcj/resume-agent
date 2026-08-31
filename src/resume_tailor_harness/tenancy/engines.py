from __future__ import annotations

import threading

from sqlalchemy.engine import Engine

from resume_tailor_harness.db import init_db, make_engine


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, tuple[str, Engine]] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str, db_url: str) -> Engine:
        with self._lock:
            cached = self._engines.get(user_id)
            if cached is not None:
                cached_url, engine = cached
                if cached_url != db_url:
                    raise ValueError(
                        f"user {user_id!r} is already bound to a different database"
                    )
                return engine
            engine = make_engine(db_url)
            try:
                init_db(engine)
            except BaseException:
                engine.dispose()
                raise
            self._engines[user_id] = (db_url, engine)
            return engine

    def evict(self, user_id: str) -> None:
        with self._lock:
            cached = self._engines.pop(user_id, None)
        if cached is not None:
            cached[1].dispose()

    def close_all(self) -> None:
        with self._lock:
            engines = [engine for _, engine in self._engines.values()]
            self._engines.clear()
        for engine in engines:
            engine.dispose()
