import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.schema import EvalCase, load_case, load_cases, load_profile
from resume_tailor_harness.models.profile import Contact, ProfileFacts


def _case_dict() -> dict:
    return {
        "id": "case_x",
        "profile_ref": "ada",
        "jd_text": "Backend role requiring Kubernetes.",
        "criteria": None,
        "traps": [
            {
                "id": "missing-k8s",
                "kind": "missing_skill",
                "forbidden_terms": ["Kubernetes", "k8s"],
                "description": "no k8s in profile",
                "probe_claim": "Built and operated Kubernetes clusters.",
                "probe_provenance": "e1b1",
            }
        ],
        "must_cite": ["e1"],
        "rubric": ["relevance", "impact"],
    }


def test_load_case_roundtrips(tmp_path: Path):
    path = tmp_path / "case_x.json"
    path.write_text(json.dumps(_case_dict()), encoding="utf-8")

    case = load_case(path)

    assert isinstance(case, EvalCase)
    assert case.id == "case_x"
    assert case.traps[0].forbidden_terms == ["Kubernetes", "k8s"]
    assert case.criteria is None


def test_load_case_rejects_malformed(tmp_path: Path):
    bad = _case_dict()
    del bad["jd_text"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_case(path)


def test_load_case_rejects_unknown_trap_kind_and_blank_terms(tmp_path: Path):
    bad = _case_dict()
    bad["traps"][0]["kind"] = "other"
    bad["traps"][0]["forbidden_terms"] = []
    path = tmp_path / "bad-trap.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_case(path)


def test_load_cases_sorted(tmp_path: Path):
    for name in ("case_02", "case_01"):
        data = _case_dict()
        data["id"] = name
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")

    cases = load_cases(tmp_path)

    assert [case.id for case in cases] == ["case_01", "case_02"]


def test_load_profile_reads_referenced_file(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    facts = ProfileFacts(contact=Contact(name="Ada"))
    (profiles / "ada.json").write_text(facts.model_dump_json(), encoding="utf-8")
    case = EvalCase(**_case_dict())

    loaded = load_profile(case, profiles)

    assert isinstance(loaded, ProfileFacts)
    assert loaded.contact.name == "Ada"


def test_target_defaults_to_resume():
    case = load_case(Path("evals/cases/case_01_missing_skill.json"))

    assert case.target == "resume"


def test_portfolio_expectation_roundtrips():
    case = load_case(Path("evals/cases/case_10_keyword_mismatch.json"))

    assert case.portfolio_expectation is not None
    assert case.portfolio_expectation.label == "safe_alias"
    assert case.portfolio_expectation.mandatory_evidence_ids == [
        "e1b1",
        "e1b2",
        "e1b3",
    ]


def test_cover_letter_target_roundtrips(tmp_path: Path):
    data = _case_dict()
    data["target"] = "cover_letter"
    path = tmp_path / "case.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert load_case(path).target == "cover_letter"
