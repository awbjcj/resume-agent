from datetime import date

from evals.scout_source_eval import ScoutSourceCase, run_source_case
from resume_agent.discovery.source_resolution.models import CompanySourceResolution


class StubResolver:
    def __init__(self, result: CompanySourceResolution | Exception) -> None:
        self.result = result

    def resolve(self, company: str, candidate_url: str) -> CompanySourceResolution:
        assert company == "Tempus"
        assert candidate_url == "https://www.tempus.com/careers/"
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _case() -> ScoutSourceCase:
    return ScoutSourceCase(
        company="Tempus",
        official_careers_url="https://www.tempus.com/careers/",
        expected_ats="workday",
        expected_board_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
        evidence_checked_at=date(2026, 8, 14),
    )


def test_source_eval_passes_only_for_an_exact_verified_board():
    result = run_source_case(
        _case(),
        StubResolver(
            CompanySourceResolution(
                company="Tempus",
                requested_url="https://www.tempus.com/careers/",
                canonical_board_url="https://tempus.wd5.myworkdayjobs.com/Tempus_Careers",
                ats="workday",
                status="verified",
                reason_code="VERIFIED_FIRST_PARTY",
            )
        ),
    )

    assert result.passed is True
    assert result.error is None


def test_source_eval_marks_wrong_or_unverified_results_as_failures():
    result = run_source_case(
        _case(),
        StubResolver(
            CompanySourceResolution(
                company="Tempus",
                requested_url="https://www.tempus.com/careers/",
                canonical_board_url="https://jobs.lever.co/tempus",
                ats="lever",
                status="unverified",
                reason_code="OWNERSHIP_NOT_PROVEN",
            )
        ),
    )

    assert result.passed is False
    assert result.actual_ats == "lever"
    assert result.status == "unverified"


def test_source_eval_reports_one_case_exception_without_raising():
    result = run_source_case(_case(), StubResolver(RuntimeError("offline")))

    assert result.passed is False
    assert result.error == "RuntimeError: offline"
