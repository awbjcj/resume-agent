from resume_agent.llm_runner import Runner, expect_schema
from resume_agent.models.cover_letter import CoverLetterContent
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts


def compose_cover_letter_input(
    jd_text: str, criteria: JobCriteria, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def draft_cover_letter(input_text: str, agent: Runner) -> CoverLetterContent:
    return expect_schema(
        agent.run(input_text), CoverLetterContent, source="cover-letter draft"
    )


def compose_revise_input(
    content: CoverLetterContent,
    unsupported_ids: list[str],
    profile_facts: ProfileFacts,
    jd_text: str,
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT COVER LETTER (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "UNSUPPORTED PROVENANCE IDS (remove or re-ground these claims):\n"
        f"{', '.join(unsupported_ids)}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def revise_cover_letter(input_text: str, agent: Runner) -> CoverLetterContent:
    return expect_schema(
        agent.run(input_text), CoverLetterContent, source="cover-letter reviser"
    )
