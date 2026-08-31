from evals.metrics import (
    ProbeRecord,
    RoundRecord,
    convergence,
    correlation,
    fact_check_trap_recall,
)
from resume_tailor_harness.models.profile import Contact
from resume_tailor_harness.models.resume import ResumeContent, TailoredBullet, TailoredExperience


def _content(bullet_text: str) -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance="e1",
                bullets=[TailoredBullet(text=bullet_text, provenance="b1")],
            )
        ],
    )


def test_probe_recall_caught_and_missed():
    probes = [
        ProbeRecord("k8s", True),
        ProbeRecord("aws", False),
        ProbeRecord("go", None, "timeout"),
    ]

    assert fact_check_trap_recall(probes) == 0.5


def test_probe_recall_none_when_no_probe_ran():
    assert fact_check_trap_recall([]) is None


def test_correlation_min_n_guard():
    assert correlation([1, 2, 3], [1, 2, 3], min_n=5) is None


def test_correlation_perfect():
    result = correlation([1, 2, 3, 4, 5], [10, 20, 30, 40, 50], min_n=5)

    assert result is not None and abs(result - 1.0) < 1e-9


def test_convergence_detects_regression():
    rounds = [
        RoundRecord(1, _content("a"), 80, []),
        RoundRecord(2, _content("b"), 70, []),
    ]

    used, regressed = convergence(rounds)

    assert used == 2
    assert regressed is True


def test_convergence_monotonic():
    rounds = [
        RoundRecord(1, _content("a"), 80, []),
        RoundRecord(2, _content("b"), 90, []),
    ]

    assert convergence(rounds) == (2, False)


def test_convergence_ignores_provenance_only_placeholder_score():
    rounds = [
        RoundRecord(1, _content("a"), 80, []),
        RoundRecord(2, _content("b"), None, []),
    ]

    assert convergence(rounds) == (2, False)
