"""Read-only health report over stored resume versions.

Answers the questions that diagnosed the 2026-07-27 scoring bug, so the same
numbers can be re-read after a change instead of re-derived by hand:

  * how scores are distributed, and how many rounds have no score at all
  * which gate actually blocked each failing round
  * which blocking issues each gate is raising

Usage:
    python scripts/tailor_health.py <path-to-resume_agent.db> [--json]

It opens the database read-only and writes nothing.
"""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Buckets for blocking issues, most specific pattern first. These
# are the categories the 2026-07-27 investigation found; they are a reporting
# convenience, not a contract.
_ISSUE_KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("summary claim", re.compile(r"\bsummary\b")),
    ("skill entry", re.compile(r"\bskill\b|supports only|supports '")),
    ("metric/number", re.compile(r"\bmetric\b|\d")),
    ("scope/wording", re.compile(r"not supported|no evidence|unsupported")),
]

# Every gate that can block a round. ``provenance`` and ``fact-check`` were the
# original two; ``skill-naming`` and ``numeric-evidence`` are deterministic
# gates added 2026-08-04 that intercept mechanically-provable violations before
# the panel runs.
_GATE_REVIEWERS = frozenset(
    {"provenance", "fact-check", "skill-naming", "numeric-evidence"}
)
_GATE_REVIEWER_ORDER = (
    "provenance",
    "fact-check",
    "skill-naming",
    "numeric-evidence",
)
_COVERAGE_REVIEWER = "must-have-coverage"


def _issue_kind(message: str) -> str:
    lowered = message.lower()
    for name, pattern in _ISSUE_KINDS:
        if pattern.search(lowered):
            return name
    return "other"


def _coverage_totals(critique: dict[str, Any]) -> tuple[int, int] | None:
    """Read runtime-only coverage totals, if this is a valid measurement."""
    if critique.get("reviewer") != _COVERAGE_REVIEWER:
        return None
    covered = critique.get("covered_total")
    rendered = critique.get("rendered_total")
    if (
        isinstance(covered, int)
        and not isinstance(covered, bool)
        and isinstance(rendered, int)
        and not isinstance(rendered, bool)
        and covered >= 0
        and 0 <= rendered <= covered
    ):
        return covered, rendered
    return None


def collect(db_path: Path) -> dict[str, Any]:
    # Read-only: a health check must never be able to mutate the data it reports.
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = list(
            connection.execute(
                "select id, job_id, round, review_score, fact_check_passed, critique_json "
                "from resume_versions order by job_id, round"
            )
        )
    finally:
        connection.close()

    scores: collections.Counter[str] = collections.Counter()
    gate_failures: collections.Counter[str] = collections.Counter(
        {reviewer: 0 for reviewer in _GATE_REVIEWER_ORDER}
    )
    issue_kinds: collections.Counter[str] = collections.Counter()
    reviewer_scores: dict[str, list[int]] = collections.defaultdict(list)
    coverage_rendered = coverage_covered = 0
    coverage_has_totals = False
    per_job: dict[int, list[tuple[int, int | None, bool]]] = collections.defaultdict(list)
    unscored = zeros = 0

    for _vid, job_id, round_num, score, clean, critique_json in rows:
        if score is None:
            unscored += 1
            scores["unscored"] += 1
        else:
            if score == 0:
                zeros += 1
            scores[f"{score // 10 * 10}-{score // 10 * 10 + 9}"] += 1
        per_job[job_id].append((round_num, score, bool(clean)))

        for critique in json.loads(critique_json or "[]"):
            reviewer = critique.get("reviewer", "?")
            if isinstance(critique.get("score"), int):
                reviewer_scores[reviewer].append(critique["score"])
            if totals := _coverage_totals(critique):
                covered, rendered = totals
                coverage_covered += covered
                coverage_rendered += rendered
                coverage_has_totals = True
            if not critique.get("passed", True) and reviewer in _GATE_REVIEWERS:
                gate_failures[reviewer] += 1
                for issue in critique.get("issues") or []:
                    if issue.get("severity") == "blocking":
                        kind = _issue_kind(issue.get("message", ""))
                        issue_kinds[f"{reviewer}: {kind}"] += 1

    improved = regressed = same = 0
    for rounds in per_job.values():
        ordered = sorted(rounds)
        for (_, before, _), (_, after, _) in itertools.pairwise(ordered):
            if before is None or after is None:
                continue
            if after > before:
                improved += 1
            elif after < before:
                regressed += 1
            else:
                same += 1

    reviewer_means = {
        name: round(sum(values) / len(values), 1)
        for name, values in sorted(reviewer_scores.items())
    }
    if coverage_has_totals and coverage_covered:
        reviewer_means[_COVERAGE_REVIEWER] = round(
            100 * coverage_rendered / coverage_covered, 1
        )

    return {
        "versions": len(rows),
        "jobs": len(per_job),
        "zero_scores": zeros,
        "unscored": unscored,
        "score_buckets": dict(sorted(scores.items())),
        "gate_failures": dict(gate_failures),
        "blocking_issue_kinds": dict(issue_kinds.most_common()),
        "reviewer_means": reviewer_means,
        "round_transitions": {
            "improved": improved,
            "regressed": regressed,
            "same": same,
        },
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"versions={report['versions']}  jobs={report['jobs']}",
        f"zero scores={report['zero_scores']}  unscored={report['unscored']}",
        "",
        "score buckets:",
        *(f"  {k:>10}  {v}" for k, v in report["score_buckets"].items()),
        "",
        "gate failures (which gate actually blocked):",
        *(f"  {k:>12}  {v}" for k, v in report["gate_failures"].items()),
        "",
        "blocking issues by gate and kind:",
        *(f"  {k:>32}  {v}" for k, v in report["blocking_issue_kinds"].items()),
        "",
        "mean score by reviewer:",
        *(f"  {k:>14}  {v}" for k, v in report["reviewer_means"].items()),
        "",
        "round-over-round transitions: "
        + ", ".join(f"{k}={v}" for k, v in report["round_transitions"].items()),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path, help="path to a workspace resume_agent.db")
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    args = parser.parse_args(argv)

    if not args.db.exists():
        parser.error(f"no such database: {args.db}")

    report = collect(args.db)
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
