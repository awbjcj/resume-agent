import json
import subprocess
import sys
from pathlib import Path

import evals.run_scout_source_eval as run_scout_source_eval
from resume_tailor_harness.discovery.source_resolution.models import CompanySourceResolution


def test_live_source_cli_writes_a_read_only_result_report(tmp_path, monkeypatch):
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                {
                    "company": "Tempus",
                    "official_careers_url": "https://www.tempus.com/careers/",
                    "expected_ats": "workday",
                    "expected_board_url": "https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
                    "evidence_checked_at": "2026-08-14",
                }
            ]
        ),
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    class Resolver:
        def __init__(self, search_path: str) -> None:
            captured["search_path"] = search_path

        def resolve(self, company: str, url: str) -> CompanySourceResolution:
            return CompanySourceResolution(
                company=company,
                requested_url=url,
                canonical_board_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
                ats="workday",
                status="verified",
                reason_code="VERIFIED_FIRST_PARTY",
            )

    monkeypatch.setattr(run_scout_source_eval, "CompanySourceResolver", Resolver)
    output = tmp_path / "report.json"

    assert (
        run_scout_source_eval.main(
            [
                "--cases",
                str(cases),
                "--output",
                str(output),
                "--search-path",
                "config/eval-search.yaml",
                "--timeout-seconds",
                "20",
            ]
        )
        == 0
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert payload["results"][0]["passed"] is True
    assert captured["search_path"] == "config/eval-search.yaml"


def test_direct_source_eval_script_bootstraps_the_repository_imports():
    root = Path(__file__).parents[2]

    result = subprocess.run(
        [sys.executable, "evals/run_scout_source_eval.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Scout ATS board accuracy" in result.stdout
