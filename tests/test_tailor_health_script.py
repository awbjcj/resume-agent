import importlib.util
import json
import sqlite3
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "tailor_health", Path(__file__).resolve().parents[1] / "scripts" / "tailor_health.py"
)
assert _SPEC and _SPEC.loader
tailor_health = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tailor_health)


def _db(tmp_path: Path, rounds: list[list[dict]] | list[dict]) -> Path:
    path = tmp_path / "resume_agent.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "create table resume_versions (id integer, job_id integer, round integer, "
        "review_score integer, fact_check_passed integer, critique_json text)"
    )
    if rounds and isinstance(rounds[0], dict):
        rounds = [rounds]  # type: ignore[list-item]
    for round_num, critiques in enumerate(rounds, start=1):
        connection.execute(
            "insert into resume_versions values (?, 1, ?, 70, 0, ?)",
            (round_num, round_num, json.dumps(critiques)),
        )
    connection.commit()
    connection.close()
    return path


def test_all_gate_names_are_counted_and_blocking_kinds_are_keyed_by_gate(tmp_path):
    path = _db(
        tmp_path,
        [
            {"reviewer": "provenance", "score": 100, "passed": True, "issues": []},
            {
                "reviewer": "numeric-evidence",
                "score": 0,
                "passed": False,
                "issues": [{"severity": "blocking", "message": "the number '40'"}],
            },
            {
                "reviewer": "skill-naming",
                "score": 0,
                "passed": False,
                "issues": [{"severity": "blocking", "message": "skill entry names"}],
            },
        ],
    )

    report = tailor_health.collect(path)

    assert report["gate_failures"]["numeric-evidence"] == 1
    assert report["gate_failures"]["skill-naming"] == 1
    assert report["gate_failures"]["provenance"] == 0
    assert report["gate_failures"]["fact-check"] == 0
    assert report["blocking_issue_kinds"] == {
        "numeric-evidence: metric/number": 1,
        "skill-naming: skill entry": 1,
    }


def test_coverage_rate_rides_the_reviewer_means(tmp_path):
    path = _db(
        tmp_path,
        [[{"reviewer": "must-have-coverage", "score": 60, "passed": True, "issues": []}]],
    )

    report = tailor_health.collect(path)

    assert report["reviewer_means"]["must-have-coverage"] == 60.0


def test_coverage_rate_uses_weighted_rendered_and_covered_totals(tmp_path):
    path = _db(
        tmp_path,
        [
            [
                {
                    "reviewer": "must-have-coverage",
                    "score": 90,
                    "passed": True,
                    "covered_total": 10,
                    "rendered_total": 9,
                }
            ],
            [
                {
                    "reviewer": "must-have-coverage",
                    "score": 0,
                    "passed": True,
                    "covered_total": 2,
                    "rendered_total": 0,
                }
            ],
        ],
    )

    report = tailor_health.collect(path)

    assert report["reviewer_means"]["must-have-coverage"] == 75.0
