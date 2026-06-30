from evals.judge import DimensionScore, JudgeVerdict
from evals.runner import CaseResult, run_case
from evals.schema import EvalCase, Trap
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.services.agents import TailorBundle
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


class _Result:
    def __init__(self, content):
        self.content = content


def _clean_resume() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance="e1",
                bullets=[TailoredBullet(text="Built REST API", provenance="b1")],
            )
        ],
    )


class _Tailor:
    def run(self, prompt):
        return _Result(_clean_resume())

    async def arun(self, prompt):
        return self.run(prompt)


class _Reviewer:
    def run(self, prompt):
        if "Kubernetes" in prompt:
            return _Result(
                ReviewCritique(
                    reviewer="fact-check",
                    score=0,
                    passed=False,
                    issues=[
                        ReviewIssue(
                            severity=Severity.blocking,
                            message="unsupported Kubernetes",
                        )
                    ],
                )
            )
        return _Result(
            ReviewCritique(reviewer="fact-check", score=100, passed=True)
        )

    async def arun(self, prompt):
        return self.run(prompt)


class _ProbeFailReviewer:
    def __init__(self):
        self._calls = 0

    def run(self, prompt):
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("probe provider failed")
        return _Result(
            ReviewCritique(reviewer="fact-check", score=100, passed=True)
        )

    async def arun(self, prompt):
        return self.run(prompt)


class _Judge:
    def run(self, prompt):
        verdict = JudgeVerdict(
            output_quality=91,
            dimensions=[
                DimensionScore(
                    dimension="relevance", score=91, rationale="good"
                )
            ],
            summary="good",
        )
        return _Result(verdict)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Eng",
                bullets=[Bullet(id="b1", text="Built API")],
            )
        ],
    )


def _case() -> EvalCase:
    return EvalCase(
        id="c1",
        profile_ref="ada",
        jd_text="Backend",
        criteria=JobCriteria(),
        traps=[
            Trap(
                id="k8s",
                kind="missing_skill",
                forbidden_terms=["Kubernetes"],
                description="x",
                probe_claim="Built Kubernetes clusters",
                probe_provenance="b1",
            )
        ],
        must_cite=["e1", "b1"],
        rubric=["relevance"],
    )


def _config() -> ReviewConfig:
    return ReviewConfig(
        max_rounds=1,
        score_threshold=80,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )


def _bundle(reviewer) -> TailorBundle:
    return TailorBundle(
        tailor=_Tailor(),
        reviser=_Tailor(),
        reviewers={"fact-check": reviewer},
        revision=_Tailor(),
    )


def test_run_case_collects_signals():
    result = run_case(_case(), _facts(), _config(), _bundle(_Reviewer()), _Judge())

    assert isinstance(result, CaseResult)
    assert result.case_id == "c1"
    assert result.trap_avoided is True
    assert result.provenance_ok is True
    assert result.must_cite_covered is True
    assert result.final_quality == 91
    assert len(result.rounds) == 1
    assert {critique.reviewer for critique in result.rounds[0].critiques} == {
        "provenance",
        "fact-check",
    }
    assert result.probes[0].trap_id == "k8s"
    assert result.probes[0].detected is True
    assert result.usage.calls == 4


def test_run_case_records_probe_failure_and_keeps_case_result():
    result = run_case(
        _case(), _facts(), _config(), _bundle(_ProbeFailReviewer()), _Judge()
    )

    assert result.final_quality == 91
    assert result.probes[0].detected is None
    assert result.probes[0].error == "RuntimeError: probe provider failed"
    assert result.usage.calls == 4
    assert result.usage.failed_calls == 1
