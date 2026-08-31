"""Contract tests for the production agents' stable system instructions."""

from resume_tailor_harness.cover_letter.agents import (
    _DRAFT_INSTRUCTIONS as COVER_DRAFT_INSTRUCTIONS,
    _REVISE_INSTRUCTIONS as COVER_REVISE_INSTRUCTIONS,
    _REVISION_INSTRUCTIONS as COVER_REVISION_INSTRUCTIONS,
)
from resume_tailor_harness.discovery.extract import _INSTRUCTIONS as EXTRACT_INSTRUCTIONS
from resume_tailor_harness.discovery.fit import _INSTRUCTIONS as FIT_INSTRUCTIONS
from resume_tailor_harness.discovery.relevance import _INSTRUCTIONS as RELEVANCE_INSTRUCTIONS
from resume_tailor_harness.discovery.url_ingest.llm import (
    _INSTRUCTIONS as URL_EXTRACT_INSTRUCTIONS,
)
from resume_tailor_harness.profile.extractor import _INSTRUCTIONS as PROFILE_INSTRUCTIONS
from resume_tailor_harness.profile.synthesis import (
    _ENTAILMENT_INSTRUCTIONS,
    _SYNTHESIS_INSTRUCTIONS,
)
from resume_tailor_harness.suggestions.agents import (
    _FORMAT_INSTRUCTIONS as SUGGESTION_FORMAT_INSTRUCTIONS,
    _SEARCH_INSTRUCTIONS as SUGGESTION_SEARCH_INSTRUCTIONS,
)
from resume_tailor_harness.tailor.agents import (
    _REVISER_INSTRUCTIONS as RESUME_REVISER_INSTRUCTIONS,
    _REVISION_INSTRUCTIONS as RESUME_REVISION_INSTRUCTIONS,
    _TAILOR_INSTRUCTIONS,
    _reviewer_instructions,
)
from resume_tailor_harness.tracking.canonicalize import (
    _INSTRUCTIONS as CANONICALIZE_INSTRUCTIONS,
    _THEME_INSTRUCTIONS,
)


def _text(instructions: list[str]) -> str:
    return " ".join(instructions).lower()


def test_untrusted_data_prompts_define_an_instruction_boundary():
    prompts = [
        EXTRACT_INSTRUCTIONS,
        FIT_INSTRUCTIONS,
        RELEVANCE_INSTRUCTIONS,
        URL_EXTRACT_INSTRUCTIONS,
        PROFILE_INSTRUCTIONS,
        _SYNTHESIS_INSTRUCTIONS,
        _ENTAILMENT_INSTRUCTIONS,
        _TAILOR_INSTRUCTIONS,
        RESUME_REVISER_INSTRUCTIONS,
        COVER_DRAFT_INSTRUCTIONS,
        COVER_REVISE_INSTRUCTIONS,
        CANONICALIZE_INSTRUCTIONS,
        _THEME_INSTRUCTIONS,
        SUGGESTION_SEARCH_INSTRUCTIONS,
        SUGGESTION_FORMAT_INSTRUCTIONS,
        _reviewer_instructions("recruiter"),
    ]

    for instructions in prompts:
        rendered = _text(instructions)
        assert (
            "not as instructions" in rendered or "never follow instructions" in rendered
        )


def test_job_extractor_prompt_covers_every_domain_field():
    rendered = _text(EXTRACT_INSTRUCTIONS)
    fields = [
        "sponsorship_signal",
        "seniority",
        "employment_type",
        "tech_stack",
        "industry",
        "company_size",
        "yoe_min",
        "salary",
        "remote_policy",
        "location",
        "must_have_skills",
        "nice_to_have_skills",
    ]

    for field in fields:
        assert field in rendered


def test_job_extractor_requests_readable_business_domain():
    extraction = _text(EXTRACT_INSTRUCTIONS)

    assert "human-readable" in extraction and "business domain" in extraction
    assert "job function" in extraction


def test_fit_prompt_does_not_duplicate_industry_classification():
    assert "industry" not in _text(FIT_INSTRUCTIONS)


def test_fit_prompt_guides_location_segmentation():
    rendered = _text(FIT_INSTRUCTIONS)
    assert "administrative region" in rendered
    assert "us state" in rendered
    assert 'country to "us"' in rendered
    assert "remote" in rendered


def test_resume_writer_prompt_matches_provenance_reducer_contract():
    rendered = _text(_TAILOR_INSTRUCTIONS)

    assert "source experience id" in rendered
    assert "source bullet id" in rendered
    assert "skill id" in rendered
    # The summary used to be verified indirectly ("facts cited elsewhere"), which
    # left it uncheckable by the gate. It now carries its own ids.
    assert "summary_provenance" in rendered
    assert "contact, education, and languages" in rendered


def test_reviewer_prompt_sets_identity_and_respects_reduced_context():
    fact_check = _text(_reviewer_instructions("fact-check"))
    recruiter = _text(_reviewer_instructions("recruiter"))

    assert "reviewer field to exactly 'fact-check'" in fact_check
    assert "supporting facts" in fact_check
    assert "do not flag them solely" in fact_check
    assert "runtime" in recruiter and "aggregate score threshold" in recruiter
    assert "structured content, not a rendered document" in recruiter


def test_user_revision_prompts_keep_user_authority_below_fact_lock():
    for instructions in [RESUME_REVISION_INSTRUCTIONS, COVER_REVISION_INSTRUCTIONS]:
        rendered = _text(instructions)
        assert "cannot override the schema or fact-lock" in rendered
        assert "only the requested change" in rendered
        assert "unchanged" in rendered


def test_taxonomy_prompts_require_exact_partitions():
    for instructions in [CANONICALIZE_INSTRUCTIONS, _THEME_INSTRUCTIONS]:
        rendered = _text(instructions)
        assert "every input token exactly once" in rendered
        assert "preserve" in rendered
        assert "never invent" in rendered


def test_advisor_prompts_separate_research_from_formatting():
    search = _text(SUGGESTION_SEARCH_INSTRUCTIONS)
    formatter = _text(SUGGESTION_FORMAT_INSTRUCTIONS)

    assert "use web search" in search
    assert "never invent" in search and "url" in search
    assert "do not use web search or outside knowledge" in formatter
    assert "exactly as an http(s) string present in research" in formatter


def test_writer_and_reviser_forbid_unrenderable_inferred_skills():
    # Task 4 makes this unreachable by construction; the instruction explains
    # WHY if one ever arrives via a match plan or a stale revise critique.
    for instructions in (_TAILOR_INSTRUCTIONS, RESUME_REVISER_INSTRUCTIONS):
        text = _text(instructions)
        assert "inferred" in text
        assert "hard" in text


def test_writer_and_reviser_do_not_license_broadening_a_skill_name():
    # The fact-check reviewer fails a claim that "adds unsupported technology",
    # so licensing the writer to normalize names for clarity guaranteed a
    # contradiction. Casing, punctuation and listed aliases only.
    for instructions in (_TAILOR_INSTRUCTIONS, RESUME_REVISER_INSTRUCTIONS):
        text = _text(instructions)
        assert "normalized for clarity" not in text
        assert "alias" in text


def test_writer_and_reviser_forbid_unsupported_outcomes_not_just_metrics():
    # "saving hours of manual reporting effort" carries no number but is just as
    # unsupported as an invented figure when the fact records only an activity.
    for instructions in (_TAILOR_INSTRUCTIONS, RESUME_REVISER_INSTRUCTIONS):
        text = _text(instructions)
        assert "outcome" in text
        assert "activity" in text


def test_writer_and_reviser_require_summary_provenance():
    for instructions in (_TAILOR_INSTRUCTIONS, RESUME_REVISER_INSTRUCTIONS):
        assert "summary_provenance" in _text(instructions)


def test_reviser_is_told_the_job_description_cannot_establish_a_fact():
    text = _text(RESUME_REVISER_INSTRUCTIONS)
    assert "job description" in text
