"""Benchmark the board read path against synthetic workspaces.

Usage:
    .venv/Scripts/python.exe scripts/bench_board.py
    .venv/Scripts/python.exe scripts/bench_board.py --rows 1000 5000 10000 --repeat 20

Seeds N shortlisted jobs (realistic criteria_json, a ~4.4 KB jd_text) into a
temp file-backed SQLite DB (WAL, same pragmas as production via make_engine),
then times services.board.list_board for the shortlist and triage boards.
Facts/aliases are absent on purpose: their loaders are already mtime-cached,
so this isolates query + row-build + filter/rank cost.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.board import list_board
from resume_agent.tracking.tables import Job


def seed(session: Session, n: int) -> None:
    jd = "Responsibilities include shipping software. " * 100  # ~4.4 KB
    for i in range(n):
        session.add(
            Job(
                source="greenhouse",
                url=f"https://example.com/jobs/{i}",
                company=f"Company {i % 199}",
                title=f"Software Engineer {i % 37}",
                location="Remote, US",
                jd_text=jd,
                status="shortlisted" if i % 2 == 0 else "raw",
                fit_score=i % 100,
                dedup_key=f"company {i % 199}|software engineer {i % 37}::{i}",
                criteria_json={
                    "hard_skills": ["python", "sql", "aws", "docker", "react"],
                    "soft_skills": ["communication", "ownership"],
                    "salary_range": {"min": 120000, "max": 180000},
                    "location_parts": {"country": "US", "region": "CA", "city": "SF"},
                },
            )
        )
        if i % 500 == 499:
            session.commit()
    session.commit()


def bench(engine, board: str, repeat: int) -> tuple[float, float]:
    times: list[float] = []
    with Session(engine) as session:
        for _ in range(repeat):
            start = time.perf_counter()
            list_board(session, board)  # type: ignore[arg-type]
            times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), sorted(times)[max(0, int(len(times) * 0.95) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, nargs="+", default=[1000, 5000, 10000])
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()

    print(f"{'rows':>7} {'board':>10} {'p50 ms':>8} {'p95 ms':>8}")
    for n in args.rows:
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(f"sqlite:///{(Path(tmp) / 'bench.db').as_posix()}")
            init_db(engine)
            with Session(engine) as session:
                seed(session, n)
            for board in ("shortlist", "triage"):
                p50, p95 = bench(engine, board, args.repeat)
                print(f"{n:>7} {board:>10} {p50:>8.1f} {p95:>8.1f}")
            # Windows holds the WAL file open until the engine is disposed;
            # release it before the TemporaryDirectory tries to unlink it.
            engine.dispose()


if __name__ == "__main__":
    main()
