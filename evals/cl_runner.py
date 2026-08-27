from dataclasses import dataclass

from evals.judge import (
    JudgeVerdict,
    compose_cl_judge_input,
    validate_judge_verdict,
)
from evals.schema import EvalCase
from evals.textscan import cover_letter_text, terms_hit
from evals.usage import MeteredRunner, UsageCollector, UsageTotals
from resume_agent.cover_letter.drafting import (
    compose_cover_letter_input,
    compose_revise_input,
    draft_cover_letter,
    revise_cover_letter,
)
from resume_agent.cover_letter.provenance import (
    collect_fact_ids,
    unsupported_provenance,
)
from resume_agent.llm_runner import Runner
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.profile import ProfileFacts


@dataclass(kw_only=True)
class CLCaseResult:
    case_id: str
    letter: CoverLetterContent
    revise_rounds: int
    trap_ok: bool
    provenance_ok: bool
    judge: JudgeVerdict
    final_quality: int
    usage: UsageTotals

    def __init__(
        self,
        *,
        case_id: str,
        letter: CoverLetterContent,
        revise_rounds: int,
        trap_ok: bool,
        provenance_ok: bool,
        judge: JudgeVerdict,
        final_quality: int,
        usage: UsageTotals,
    ) -> None:
        """Construct a result with an explicit signature for static analyzers."""
        self.case_id = case_id
        self.letter = letter
        self.revise_rounds = revise_rounds
        self.trap_ok = trap_ok
        self.provenance_ok = provenance_ok
        self.judge = judge
        self.final_quality = final_quality
        self.usage = usage


def run_cl_case(
    case: EvalCase,
    profile: ProfileFacts,
    draft_agent: Runner,
    reviser_agent: Runner,
    judge_agent: Runner,
    *,
    max_rounds: int = 2,
    style_guide: str | None = None,
) -> CLCaseResult:
    """Run the production cover-letter loop in memory, then measure the result."""
    if case.criteria is None:
        raise ValueError(f"{case.id}: cover-letter cases must embed criteria")
    usage = UsageCollector()
    draft = MeteredRunner(draft_agent, usage)
    reviser = MeteredRunner(reviser_agent, usage)
    fact_ids = collect_fact_ids(profile)

    content = draft_cover_letter(
        compose_cover_letter_input(case.jd_text, case.criteria, profile),
        draft,
    )
    revise_rounds = 0
    for _ in range(max_rounds - 1):
        unsupported = unsupported_provenance(content, fact_ids)
        if not unsupported:
            break
        revise_rounds += 1
        content = revise_cover_letter(
            compose_revise_input(
                content,
                unsupported,
                profile,
                case.jd_text,
            ),
            reviser,
        )

    verdict = (
        MeteredRunner(judge_agent, usage)
        .run(
            compose_cl_judge_input(
                content,
                profile,
                case.jd_text,
                case.rubric,
                style_guide,
            )
        )
        .content
    )
    if not isinstance(verdict, JudgeVerdict):
        raise TypeError(
            f"Expected JudgeVerdict from judge, got {type(verdict).__name__}"
        )
    validate_judge_verdict(verdict, case.rubric)
    return CLCaseResult(
        case_id=case.id,
        letter=content,
        revise_rounds=revise_rounds,
        trap_ok=not terms_hit(cover_letter_text(content), case.traps),
        provenance_ok=not unsupported_provenance(content, fact_ids),
        judge=verdict,
        final_quality=verdict.output_quality,
        usage=usage.snapshot(),
    )
