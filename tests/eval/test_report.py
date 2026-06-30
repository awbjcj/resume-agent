import json

from evals.judge import DimensionScore, JudgeVerdict
from evals.metrics import ProbeRecord, RoundRecord
from evals.report import render_artifact, render_report
from evals.runner import CaseResult
from evals.usage import UsageTotals
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


def _result(case_id: str, quality: int, ats_score: int) -> CaseResult:
    content = ResumeContent(contact=Contact(name="Ada"), summary=f"Resume {case_id}")
    critiques = [
        ReviewCritique(reviewer="ats-keyword", score=ats_score, passed=True)
    ]
    return CaseResult(
        case_id=case_id,
        jd_text="Backend role",
        criteria=JobCriteria(),
        rubric=["relevance"],
        traps=[],
        rounds=[RoundRecord(1, content, ats_score, critiques)],
        trap_avoided=True,
        provenance_ok=True,
        must_cite_covered=True,
        budget_ok=True,
        judge=JudgeVerdict(
            output_quality=quality,
            dimensions=[
                DimensionScore(
                    dimension="relevance", score=quality, rationale="x"
                )
            ],
            summary="s",
        ),
        final_quality=quality,
        probes=[ProbeRecord(f"{case_id}-trap", True)],
        usage=UsageTotals(calls=3, total_tokens=100, cost=0.01),
    )


def test_report_has_table_and_aggregate():
    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)]
    )
    results = [_result(f"c{index}", 50 + index * 5, 50 + index * 5) for index in range(1, 6)]

    markdown = render_report(results, config)

    assert "c1" in markdown and "c2" in markdown
    assert "**Mean output_quality:** 65" in markdown
    assert "Weakest reviewer" in markdown
    assert "Fact-check probe recall" in markdown
    assert "regressed" in markdown
    assert "total_tokens" in markdown


def test_report_insufficient_data_for_correlation():
    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)]
    )

    markdown = render_report([_result("c1", 90, 90)], config)

    assert "insufficient data" in markdown


def test_report_does_not_pair_stale_reviewer_score_with_final_judge_score():
    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)]
    )
    result = _result("c1", 90, 10)
    final_content = ResumeContent(contact=Contact(name="Ada"), summary="final")
    result.rounds.append(
        RoundRecord(
            2,
            final_content,
            None,
            [ReviewCritique(reviewer="provenance", score=0, passed=False)],
        )
    )

    markdown = render_report([result], config)

    assert "ats-keyword: panel_agreement = insufficient data (n=0)" in markdown


def test_render_artifact_preserves_complete_result_data():
    result = _result("c1", 90, 80)

    artifact = json.loads(
        render_artifact(
            [result],
            metadata={"git commit": "abc123"},
            failures=["c2: RuntimeError: failed"],
        )
    )

    serialized = artifact["results"][0]
    assert serialized["rounds"][-1]["content"]["summary"] == "Resume c1"
    assert serialized["rounds"][0]["critiques"][0]["reviewer"] == "ats-keyword"
    assert serialized["usage"]["total_tokens"] == 100
    assert artifact["metadata"] == {"git commit": "abc123"}
    assert artifact["failures"] == ["c2: RuntimeError: failed"]
