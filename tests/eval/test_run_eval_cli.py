import json
from pathlib import Path

import evals.run_eval as run_eval
from evals.judge import JudgeVerdict
from evals.metrics import RoundRecord
from evals.runner import CaseResult
from evals.usage import UsageTotals
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.tailor.review_config import ReviewConfig, ReviewerSpec


def _write_case(case_dir: Path, case_id: str) -> None:
    (case_dir / f"{case_id}.json").write_text(
        json.dumps(
            {
                "id": case_id,
                "profile_ref": "ada",
                "jd_text": "Backend",
                "criteria": {},
                "traps": [],
                "must_cite": [],
                "rubric": ["relevance"],
            }
        ),
        encoding="utf-8",
    )


def _case_result(case) -> CaseResult:
    content = ResumeContent(contact=Contact(name="Ada"))
    assert case.criteria is not None
    return CaseResult(
        case_id=case.id,
        jd_text=case.jd_text,
        criteria=case.criteria,
        rubric=case.rubric,
        traps=case.traps,
        rounds=[RoundRecord(1, content, 90, [])],
        trap_avoided=True,
        provenance_ok=True,
        must_cite_covered=True,
        budget_ok=True,
        judge=JudgeVerdict(output_quality=90),
        final_quality=90,
        probes=[],
        usage=UsageTotals(),
    )


def _write_fixture_dirs(tmp_path: Path, *case_ids: str) -> tuple[Path, Path]:
    cases = tmp_path / "cases"
    profiles = tmp_path / "profiles"
    cases.mkdir()
    profiles.mkdir()
    (profiles / "ada.json").write_text(
        ProfileFacts(contact=Contact(name="Ada")).model_dump_json(),
        encoding="utf-8",
    )
    for case_id in case_ids:
        _write_case(cases, case_id)
    return cases, profiles


def _fake_agent_builders(monkeypatch) -> None:
    monkeypatch.setattr(
        run_eval,
        "build_tailor_bundle",
        lambda config, style_guide=None: object(),
    )
    monkeypatch.setattr(run_eval, "build_judge_agent", lambda model_id=None: object())


def test_main_writes_report(tmp_path: Path, monkeypatch):
    cases, profiles = _write_fixture_dirs(tmp_path, "case_01")
    _fake_agent_builders(monkeypatch)
    monkeypatch.setattr(
        run_eval,
        "run_case",
        lambda case, profile, config, bundle, judge_agent, **kwargs: _case_result(case),
    )

    out = tmp_path / "report.md"
    return_code = run_eval.main(
        ["--cases", str(cases), "--profiles", str(profiles), "--out", str(out)]
    )

    assert return_code == 0
    assert "case_01" in out.read_text(encoding="utf-8")
    assert out.with_suffix(".json").exists()


def test_parser_exposes_locked_live_flags():
    args = run_eval.build_argparser().parse_args(
        ["--model", "openai:gpt-4.1-mini", "--live-criteria", "--fail-fast"]
    )

    assert args.model == "openai:gpt-4.1-mini"
    assert args.live_criteria is True
    assert args.fail_fast is True


def test_main_preserves_completed_cases_and_continues_after_failure(
    tmp_path: Path, monkeypatch
):
    cases, profiles = _write_fixture_dirs(tmp_path, "case_01", "case_02", "case_03")
    _fake_agent_builders(monkeypatch)
    called: list[str] = []

    def _fake_run_case(case, profile, config, bundle, judge_agent, **kwargs):
        called.append(case.id)
        if case.id == "case_02":
            raise RuntimeError("provider failed")
        return _case_result(case)

    monkeypatch.setattr(run_eval, "run_case", _fake_run_case)
    out = tmp_path / "report.md"

    return_code = run_eval.main(
        ["--cases", str(cases), "--profiles", str(profiles), "--out", str(out)]
    )

    artifact = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert return_code == 1
    assert called == ["case_01", "case_02", "case_03"]
    assert [result["case_id"] for result in artifact["results"]] == [
        "case_01",
        "case_03",
    ]
    assert artifact["failures"] == ["case_02: RuntimeError: provider failed"]
    assert "case_01" in out.read_text(encoding="utf-8")


def test_live_criteria_builds_one_shared_extractor(tmp_path: Path, monkeypatch):
    cases, profiles = _write_fixture_dirs(tmp_path, "case_01", "case_02")
    bundle = object()
    judge = object()
    extractor = object()
    monkeypatch.setattr(run_eval, "build_eval_bundle", lambda *args: bundle)
    monkeypatch.setattr(run_eval, "build_judge_agent", lambda model_id=None: judge)
    extractor_builds: list[str | None] = []

    def _build_extract_agent(model_id=None):
        extractor_builds.append(model_id)
        return extractor

    monkeypatch.setattr(run_eval, "build_extract_agent", _build_extract_agent)
    seen_extractors = []

    def _fake_run_case(case, profile, config, seen_bundle, seen_judge, **kwargs):
        assert seen_bundle is bundle
        assert seen_judge is judge
        assert kwargs["live_criteria"] is True
        seen_extractors.append(kwargs["extract_agent"])
        return _case_result(case)

    monkeypatch.setattr(run_eval, "run_case", _fake_run_case)

    return_code = run_eval.main(
        [
            "--cases",
            str(cases),
            "--profiles",
            str(profiles),
            "--out",
            str(tmp_path / "report.md"),
            "--live-criteria",
        ]
    )

    assert return_code == 0
    assert extractor_builds == [None]
    assert seen_extractors == [extractor, extractor]


def test_build_eval_bundle_applies_model_override_to_every_lane(monkeypatch):
    config = ReviewConfig(
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="recruiter"),
        ]
    )
    calls = []
    monkeypatch.setattr(
        run_eval,
        "build_tailor_agent",
        lambda model_id, style_guide: (
            calls.append(("tailor", model_id, style_guide)) or "tailor"
        ),
    )
    monkeypatch.setattr(
        run_eval,
        "build_reviser_agent",
        lambda model_id, style_guide: (
            calls.append(("reviser", model_id, style_guide)) or "reviser"
        ),
    )
    monkeypatch.setattr(
        run_eval,
        "build_revision_agent",
        lambda model_id, style_guide: (
            calls.append(("revision", model_id, style_guide)) or "revision"
        ),
    )
    monkeypatch.setattr(
        run_eval,
        "build_reviewer_agent",
        lambda name, model_id, style_guide=None, score_bands=False: (
            calls.append((name, model_id, style_guide)) or name
        ),
    )

    bundle = run_eval.build_eval_bundle(config, "guide", "openai:gpt-x")

    assert bundle.tailor == "tailor"
    assert bundle.reviser == "reviser"
    assert bundle.revision == "revision"
    assert bundle.reviewers == {
        "fact-check": "fact-check",
        "recruiter": "recruiter",
    }
    assert calls == [
        ("tailor", "openai:gpt-x", "guide"),
        ("reviser", "openai:gpt-x", "guide"),
        ("fact-check", "openai:gpt-x", "guide"),
        ("recruiter", "openai:gpt-x", "guide"),
        ("revision", "openai:gpt-x", "guide"),
    ]


def test_build_eval_bundle_delegates_default_routing(monkeypatch):
    config = ReviewConfig()
    expected = object()
    calls = []

    def _build_tailor_bundle(seen_config, style_guide=None):
        calls.append((seen_config, style_guide))
        return expected

    monkeypatch.setattr(run_eval, "build_tailor_bundle", _build_tailor_bundle)

    assert run_eval.build_eval_bundle(config, "guide", None) is expected
    assert calls == [(config, "guide")]
