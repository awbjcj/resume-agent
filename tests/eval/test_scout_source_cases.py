from datetime import date
from pathlib import Path

from evals.scout_source_eval import load_source_cases
from resume_agent.discovery.source_resolution.catalog import BOARD_FAMILIES


CASES_PATH = Path("evals/scout_source_cases.json")


def test_live_source_cases_are_current_supported_and_unique():
    cases = load_source_cases(CASES_PATH)

    assert {case.company for case in cases} == {"Intuitive Surgical", "Tempus"}
    assert len({case.company.casefold() for case in cases}) == len(cases)
    assert {case.expected_ats for case in cases} <= {
        family.kind for family in BOARD_FAMILIES
    }
    assert all(str(case.expected_board_url).startswith("https://") for case in cases)
    assert all(case.evidence_checked_at <= date.today() for case in cases)
