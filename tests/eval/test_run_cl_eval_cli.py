import hashlib
import json
from pathlib import Path

import pytest

import evals.run_cl_eval as run_cl_eval
from evals.cl_runner import CLCaseResult
from evals.judge import JudgeVerdict
from evals.usage import UsageTotals
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.profile import Contact


def _write_case(case_dir: Path, case_id: str, target: str) -> None:
    (case_dir / f"{case_id}.json").write_text(
        json.dumps(
            {
                "id": case_id,
                "target": target,
                "profile_ref": "ada",
                "jd_text": "Backend",
                "criteria": {},
                "traps": [],
                "must_cite": [],
                "rubric": ["grounding"],
            }
        ),
        encoding="utf-8",
    )


def _fixture_dirs(tmp_path: Path) -> tuple[Path, Path]:
    cases = tmp_path / "cases"
    profiles = tmp_path / "profiles"
    cases.mkdir()
    profiles.mkdir()
    (profiles / "ada.json").write_text(
        json.dumps({"contact": {"name": "Ada"}}),
        encoding="utf-8",
    )
    return cases, profiles


def test_run_cl_eval_writes_artifact_with_style_metadata(tmp_path, monkeypatch):
    cases, profiles = _fixture_dirs(tmp_path)
    _write_case(cases, "cl_x", "cover_letter")
    style_guide = tmp_path / "style.md"
    style_guide.write_text("Write crisply.", encoding="utf-8")

    fake_result = CLCaseResult(
        case_id="cl_x",
        letter=CoverLetterContent(
            contact=Contact(name="Ada"),
            greeting="Hi",
            closing="Bye",
        ),
        revise_rounds=0,
        trap_ok=True,
        provenance_ok=True,
        judge=JudgeVerdict(output_quality=90),
        final_quality=90,
        usage=UsageTotals(),
    )
    captured: dict[str, str | None] = {}

    def fake_run(*args, style_guide=None, **kwargs):
        captured["style_guide"] = style_guide
        return fake_result

    monkeypatch.setattr(
        run_cl_eval,
        "build_cover_letter_agent",
        lambda model=None: object(),
    )
    monkeypatch.setattr(
        run_cl_eval,
        "build_cover_letter_reviser_agent",
        lambda model=None: object(),
    )
    monkeypatch.setattr(
        run_cl_eval,
        "build_cl_judge_agent",
        lambda model=None: object(),
    )
    monkeypatch.setattr(run_cl_eval, "run_cl_case", fake_run)

    output = tmp_path / "report.json"
    return_code = run_cl_eval.main(
        [
            "--cases",
            str(cases),
            "--profiles",
            str(profiles),
            "--style-guide",
            str(style_guide),
            "--out",
            str(output),
        ]
    )

    assert return_code == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["results"][0]["caseId"] == "cl_x"
    assert artifact["results"][0]["finalQuality"] == 90
    assert artifact["failures"] == []
    assert "cl judge prompt sha256" in artifact["metadata"]
    assert (
        artifact["metadata"]["style guide sha256"]
        == hashlib.sha256(b"Write crisply.").hexdigest()
    )
    assert captured["style_guide"] == "Write crisply."


def test_run_cl_eval_ignores_resume_cases(tmp_path):
    cases, profiles = _fixture_dirs(tmp_path)
    _write_case(cases, "resume_only", "resume")

    with pytest.raises(
        ValueError,
        match="no cover-letter eval cases found",
    ):
        run_cl_eval.main(["--cases", str(cases), "--profiles", str(profiles)])
