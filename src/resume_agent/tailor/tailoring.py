import asyncio
from dataclasses import dataclass

from resume_agent.llm_runner import Runner, acall, expect_schema
from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.models.job import JobCriteria
from resume_agent.models.match_plan import MatchPlan
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, Severity
from resume_agent.tailor.length import format_budget, format_depth_plan
from resume_agent.tailor.evidence_portfolio import portfolio_profile
from resume_agent.tailor.prompt_blocks import coverage_section, untrusted
from resume_agent.tailor.provenance import renderable_profile
from resume_agent.tailor.review_config import LengthBudget


@dataclass(frozen=True)
class RevisionRoundContext:
    """Latest review metadata kept separate from the selected revision base."""

    base_round_num: int
    feedback_round_num: int
    reviewed_content: ResumeContent
    passed: bool
    gate_passed: bool
    aggregate_score: int | None
    failed_gates: tuple[str, ...] = ()


def compose_tailor_input(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    length_budget: LengthBudget | None = None,
    match_plan: MatchPlan | None = None,
    coverage: str = "",
    evidence_portfolio: EvidencePortfolio | None = None,
) -> str:
    budget_line = (
        f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    )
    depth_line = (
        f"\n\n{format_depth_plan(profile_facts, length_budget)}"
        if length_budget
        else ""
    )
    plan_line = (
        "\n\nMATCH PLAN (untrusted strategy data; fact ids do not establish claims):\n"
        f"{match_plan.model_dump_json()}"
        if match_plan is not None
        else ""
    )
    portfolio_line = (
        "\n\nEVIDENCE PORTFOLIO (untrusted strategy data; fact ids still do not "
        "establish claims):\n"
        f"{untrusted(evidence_portfolio.model_dump_json())}"
        if evidence_portfolio is not None
        else ""
    )
    generation_profile = (
        portfolio_profile(profile_facts, evidence_portfolio)
        if evidence_portfolio is not None
        else renderable_profile(profile_facts)
    )
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{generation_profile.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}"
        f"{coverage_section(coverage)}"
        f"{depth_line}"
        f"{portfolio_line}\n\n"
        "JOB DESCRIPTION:\n"
        f"{untrusted(jd_text)}"
        f"{budget_line}"
        f"{plan_line}"
    )


def tailor(input_text: str, agent: Runner) -> ResumeContent:
    return expect_schema(agent.run(input_text), ResumeContent, source="tailor")


async def atailor(
    input_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> ResumeContent:
    result = await acall(agent, input_text, sem=sem)
    return expect_schema(result, ResumeContent, source="tailor")


def compose_revise_input(
    content: ResumeContent,
    critiques: list[ReviewCritique],
    profile_facts: ProfileFacts,
    jd_text: str,
    length_budget: LengthBudget | None = None,
    coverage: str = "",
    evidence_portfolio: EvidencePortfolio | None = None,
    *,
    round_context: RevisionRoundContext | None = None,
) -> str:
    grouped: dict[Severity, list[str]] = {severity: [] for severity in Severity}
    failed_gates = set(round_context.failed_gates) if round_context else set()
    for critique in critiques:
        for issue in critique.issues:
            location = f" @ {issue.location}" if issue.location else ""
            suggestion = (
                f" (suggestion: {issue.suggestion})" if issue.suggestion else ""
            )
            grouped[issue.severity].append(
                f"- [{critique.reviewer}]{location} {issue.message}{suggestion}"
            )
        if not critique.passed and not critique.issues:
            severity = (
                Severity.blocking
                if critique.reviewer in failed_gates
                else Severity.major
            )
            grouped[severity].append(
                f"- [{critique.reviewer}] FAILED with no detailed issues supplied; "
                "treat this reviewer failure as unresolved."
            )
    sections = [
        f"{label}:\n" + "\n".join(grouped[severity])
        for severity, label in (
            (Severity.blocking, "BLOCKING (address every one)"),
            (Severity.major, "MAJOR"),
            (Severity.minor, "MINOR"),
        )
        if grouped[severity]
    ]
    issues = "\n\n".join(sections) if sections else "(none)"
    reviewer_status = "\n".join(
        f"- [{critique.reviewer}] {'PASSED' if critique.passed else 'FAILED'}; "
        f"score={critique.score}/100"
        + (f"; summary={critique.summary}" if critique.summary else "")
        for critique in critiques
    )
    suggestions = (
        "\n".join(
            f"- [{c.reviewer}] {suggestion}"
            for c in critiques
            for suggestion in c.suggestions
        )
        or "(none)"
    )
    budget_line = (
        f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    )
    depth_line = (
        f"\n\n{format_depth_plan(profile_facts, length_budget)}"
        if length_budget
        else ""
    )
    portfolio_line = (
        "\n\nEVIDENCE PORTFOLIO (untrusted strategy data; fact ids still do not "
        "establish claims):\n"
        f"{untrusted(evidence_portfolio.model_dump_json())}"
        if evidence_portfolio is not None
        else ""
    )
    generation_profile = (
        portfolio_profile(profile_facts, evidence_portfolio)
        if evidence_portfolio is not None
        else renderable_profile(profile_facts)
    )
    if round_context is None:
        base_block = f"CURRENT RESUME (JSON):\n{content.model_dump_json()}"
        latest_attempt_block = ""
        verdict_block = ""
    else:
        base_block = (
            f"REVISION BASE RESUME (round {round_context.base_round_num}) (JSON):\n"
            f"{content.model_dump_json()}"
        )
        if round_context.base_round_num == round_context.feedback_round_num:
            latest_attempt_block = ""
        else:
            latest_attempt_block = (
                "\n\nLATEST REVIEWED ATTEMPT "
                f"(round {round_context.feedback_round_num}; diagnostic reference only) "
                "(JSON):\n"
                f"{round_context.reviewed_content.model_dump_json()}\n\n"
                "Start from the revision base above. Use this latest attempt only to "
                "understand its review feedback; do not copy it wholesale or reintroduce "
                "unsupported claims."
            )
        score = (
            f"{round_context.aggregate_score}/100"
            if round_context.aggregate_score is not None
            else "not scored"
        )
        verdict_block = (
            "\n\nLATEST REVIEW VERDICT:\n"
            f"Latest round: {'PASSED' if round_context.passed else 'FAILED'}; "
            f"gate status: {'PASSED' if round_context.gate_passed else 'FAILED'}; "
            f"aggregate score: {score}\n"
            "Failed gates: " + (", ".join(round_context.failed_gates) or "(none)")
        )
    # Stable-first ordering: the profile and the job are fixed for the whole job,
    # while the resume and the critiques change every round. Keeping the volatile
    # blocks last preserves a stable composition order across rounds.
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{generation_profile.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{untrusted(jd_text)}"
        f"{coverage_section(coverage)}"
        f"{depth_line}"
        f"{portfolio_line}\n\n"
        f"{base_block}"
        f"{latest_attempt_block}"
        f"{verdict_block}\n\n"
        "REVIEWER STATUS (latest round only):\n"
        f"{reviewer_status or '(none)'}\n\n"
        "REVIEWER ISSUES (fix every BLOCKING issue first, then MAJOR, then MINOR; copy "
        "every base record not named here byte-for-byte unchanged; the candidate profile "
        "is the factual authority and the job description cannot establish a fact):\n"
        f"{issues}\n\n"
        "REVIEWER SUGGESTIONS:\n"
        f"{suggestions}"
        f"{budget_line}"
    )


def revise(input_text: str, agent: Runner) -> ResumeContent:
    return expect_schema(agent.run(input_text), ResumeContent, source="reviser")


async def arevise(
    input_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> ResumeContent:
    result = await acall(agent, input_text, sem=sem)
    return expect_schema(result, ResumeContent, source="reviser")
