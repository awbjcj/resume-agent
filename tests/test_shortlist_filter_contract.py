import json
from datetime import datetime
from pathlib import Path

import pytest

from resume_agent.dashboard.filtering import FilterState, apply_filters, sort_rows
from resume_agent.tracking.queries import ShortlistRow, SkillTag

CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "shortlist_filter.contract.json"

_SET_KEYS = {
    "remote",
    "sponsorship",
    "seniority",
    "employmentType",
    "industry",
    "country",
    "region",
    "city",
    "companySize",
    "skills",
}
_CAMEL_TO_SNAKE = {
    "jobId": "job_id",
    "fitScore": "fit_score",
    "fitRationale": "fit_rationale",
    "sponsorshipSignal": "sponsorship_signal",
    "salaryMin": "salary_min",
    "salaryMax": "salary_max",
    "salaryCurrency": "salary_currency",
    "remotePolicy": "remote_policy",
    "employmentType": "employment_type",
    "companySize": "company_size",
    "postedAt": "posted_at",
    "sicMajor": "sic_major",
    "sicLabel": "sic_label",
    "sicDivision": "sic_division",
    "locationCountry": "location_country",
    "locationRegion": "location_region",
    "locationCity": "location_city",
}
_STATE_CAMEL_TO_SNAKE = {
    "salaryMin": "salary_min",
    "fitMin": "fit_min",
    "employmentType": "employment_type",
    "companySize": "company_size",
}


def _parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def row_from_wire(d: dict) -> ShortlistRow:
    fields = {_CAMEL_TO_SNAKE.get(k, k): v for k, v in d.items() if k != "skills"}
    fields["posted_at"] = _parse_dt(fields.get("posted_at"))
    skills = [
        SkillTag(
            name=s["name"],
            covered=s.get("covered", False),
            required=s.get("required", False),
        )
        for s in d.get("skills", [])
    ]
    return ShortlistRow(
        job_id=fields["job_id"],
        company=fields.get("company"),
        title=fields.get("title"),
        location=fields.get("location"),
        fit_score=fields.get("fit_score"),
        fit_rationale=fields.get("fit_rationale"),
        sponsorship_signal=fields.get("sponsorship_signal"),
        salary_min=fields.get("salary_min"),
        salary_max=fields.get("salary_max"),
        salary_currency=fields.get("salary_currency"),
        remote_policy=fields.get("remote_policy"),
        seniority=fields.get("seniority"),
        employment_type=fields.get("employment_type"),
        industry=fields.get("industry"),
        company_size=fields.get("company_size"),
        posted_at=fields.get("posted_at"),
        skills=skills,
        sic_major=fields.get("sic_major"),
        sic_label=fields.get("sic_label"),
        sic_division=fields.get("sic_division"),
        location_country=fields.get("location_country"),
        location_region=fields.get("location_region"),
        location_city=fields.get("location_city"),
    )


def filter_state_from_wire(d: dict) -> FilterState:
    state = FilterState()
    for k, v in d.items():
        attr = _STATE_CAMEL_TO_SNAKE.get(k, k)
        if k in _SET_KEYS:
            setattr(state, attr, set(v))
        else:
            setattr(state, attr, v)
    return state


def _load_cases():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    return data["now"], data["cases"]


_NOW, _CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_python_satisfies_filter_contract(case):
    now = _parse_dt(_NOW)
    rows = [row_from_wire(r) for r in case["rows"]]
    state = filter_state_from_wire(case["filterState"])
    out = sort_rows(apply_filters(rows, state), state, now=now)
    assert [r.job_id for r in out] == case["expected"]
