from resume_tailor_harness.llm_runner import Runner, expect_schema
from resume_tailor_harness.models.cover_letter import CoverLetterContent
from resume_tailor_harness.models.profile import ProfileFacts


def compose_user_revision_input(
    content: CoverLetterContent, instruction: str, profile_facts: ProfileFacts
) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT COVER LETTER (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "USER INSTRUCTION (apply exactly; change only what is asked):\n"
        f"{instruction}"
    )


def apply_revision(input_text: str, agent: Runner) -> CoverLetterContent:
    return expect_schema(
        agent.run(input_text), CoverLetterContent, source="cover-letter revision"
    )
