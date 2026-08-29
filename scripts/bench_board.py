"""Benchmark the board read path against synthetic workspaces.

Usage:
    .venv/Scripts/python.exe scripts/bench_board.py
    .venv/Scripts/python.exe scripts/bench_board.py --rows 2000 --repeat 10 --page 1 last
    .venv/Scripts/python.exe scripts/bench_board.py --board pipeline --page 40

Seeds N jobs (realistic criteria_json, a ~5.6 KB jd_text) into a
temp file-backed SQLite DB (WAL, same pragmas as production via make_engine),
then times services.board.list_board and records the serialized board payload.
Facts/aliases are absent on purpose: their loaders are already mtime-cached,
so this isolates query + row-build + filter/rank cost.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import statistics
import tempfile
import time
from pathlib import Path

from sqlmodel import Session

from resume_agent.api.mappers import to_board_page
from resume_agent.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_agent.db import init_db, make_engine
from resume_agent.services.board import list_board
from resume_agent.tracking.tables import Job

BOARDS = ("shortlist", "triage", "pipeline")
ITEM_MODELS = {
    "shortlist": ShortlistItem,
    "triage": TriageItem,
    "pipeline": PipelineItem,
}
STATUSES = ("shortlisted", "raw", "approved", "tailored", "rendered", "rejected")


@dataclass(frozen=True)
class BenchmarkResult:
    board: str
    page: int
    total_pages: int
    p50_ms: float
    p95_ms: float
    total_bytes: int
    jd_text_bytes: int
    facets_bytes: int


def seed(session: Session, n: int) -> None:
    jd = "Responsibilities include shipping reliable software. " * 115  # ~5.6 KB
    for i in range(n):
        session.add(
            Job(
                source="greenhouse",
                url=f"https://example.com/jobs/{i}",
                company=f"Company {i % 199}",
                title=f"Software Engineer {i % 37}",
                location="Remote, US",
                jd_text=jd,
                status=STATUSES[i % len(STATUSES)],
                fit_score=i % 100,
                dedup_key=f"company {i % 199}|software engineer {i % 37}::{i}",
                criteria_json={
                    "must_have_skills": ["python", "sql"],
                    "nice_to_have_skills": ["aws", "docker"],
                    "tech_stack": ["react"],
                    "salary_range": {
                        "minimum": 120000,
                        "maximum": 180000,
                        "currency": "USD",
                    },
                    "location_parts": {"country": "US", "region": "CA", "city": "SF"},
                    "remote_policy": "remote",
                    "sponsorship_signal": "silent",
                    "seniority": "senior",
                    "employment_type": "full_time",
                    "industry": "software",
                    "company_size": "scaleup",
                },
            )
        )
        if i % 500 == 499:
            session.commit()
    session.commit()


def _payload_sizes(result, board: str) -> tuple[int, int, int]:
    response = to_board_page(result.page, ITEM_MODELS[board], result.facets)
    payload = response.model_dump(by_alias=True, mode="json")
    total_bytes = len(response.model_dump_json(by_alias=True).encode("utf-8"))
    jd_text_bytes = sum(
        len(str(item.get("jdText", "")).encode("utf-8")) for item in payload["data"]
    )
    facets_bytes = len(
        json.dumps(payload["facets"], ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    return total_bytes, jd_text_bytes, facets_bytes


def bench(engine, board: str, repeat: int, page: int = 1) -> BenchmarkResult:
    times: list[float] = []
    with Session(engine) as session:
        for _ in range(repeat):
            start = time.perf_counter()
            list_board(session, board, page=page)  # type: ignore[arg-type]
            times.append((time.perf_counter() - start) * 1000)
        result = list_board(session, board, page=page)  # type: ignore[arg-type]
        total_bytes, jd_text_bytes, facets_bytes = _payload_sizes(result, board)
    return BenchmarkResult(
        board=board,
        page=page,
        total_pages=result.page.total_pages,
        p50_ms=statistics.median(times),
        p95_ms=sorted(times)[max(0, int(len(times) * 0.95) - 1)],
        total_bytes=total_bytes,
        jd_text_bytes=jd_text_bytes,
        facets_bytes=facets_bytes,
    )


def _resolve_pages(engine, board: str, requested: list[str]) -> list[int]:
    with Session(engine) as session:
        total_pages = list_board(session, board).page.total_pages  # type: ignore[arg-type]
    pages: list[int] = []
    for value in requested:
        if value == "last":
            page = max(1, total_pages)
        else:
            page = int(value)
            if page < 1:
                raise ValueError("--page values must be positive integers or 'last'")
        if page not in pages:
            pages.append(page)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, nargs="+", default=[1000, 5000, 10000])
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--board", nargs="+", choices=BOARDS, default=list(BOARDS))
    parser.add_argument("--page", nargs="+", default=["1"])
    args = parser.parse_args()

    print(
        f"{'rows':>7} {'board':>10} {'page':>5} {'p50 ms':>8} {'p95 ms':>8} "
        f"{'total B':>10} {'jdText B':>10} {'facets B':>10}"
    )
    for n in args.rows:
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(f"sqlite:///{(Path(tmp) / 'bench.db').as_posix()}")
            init_db(engine)
            with Session(engine) as session:
                seed(session, n)
            for board in args.board:
                for page in _resolve_pages(engine, board, args.page):
                    result = bench(engine, board, args.repeat, page=page)
                    print(
                        f"{n:>7} {board:>10} {result.page:>5} "
                        f"{result.p50_ms:>8.1f} {result.p95_ms:>8.1f} "
                        f"{result.total_bytes:>10} {result.jd_text_bytes:>10} "
                        f"{result.facets_bytes:>10}"
                    )
            # Windows holds the WAL file open until the engine is disposed;
            # release it before the TemporaryDirectory tries to unlink it.
            engine.dispose()


if __name__ == "__main__":
    main()
