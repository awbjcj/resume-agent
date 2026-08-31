import pytest
from pydantic import ValidationError

from resume_tailor_harness.models.profile import Bullet, Project


def test_bullet_aspect_is_optional_but_closed():
    assert Bullet(text="Investigated a production incident").aspect is None
    assert (
        Bullet(text="Led the incident review", aspect="leadership").aspect
        == "leadership"
    )
    with pytest.raises(ValidationError, match="aspect"):
        Bullet.model_validate({"text": "Made it better", "aspect": "made-up"})


def test_legacy_project_highlights_become_stable_addressable_bullets():
    payload = {
        "id": "prj_alpha",
        "name": "Alpha",
        "highlights": ["Shipped the dashboard", "Shipped the dashboard"],
    }

    first = Project.model_validate(payload)
    second = Project.model_validate(payload)

    assert [highlight.text for highlight in first.highlights] == [
        "Shipped the dashboard",
        "Shipped the dashboard",
    ]
    assert all(highlight.id for highlight in first.highlights)
    assert [highlight.id for highlight in first.highlights] == [
        highlight.id for highlight in second.highlights
    ]
    assert first.highlights[0].id != first.highlights[1].id


def test_all_extraction_prompts_require_a_closed_bullet_aspect():
    from resume_tailor_harness.profile.extractor import _INSTRUCTIONS as extractor_instructions
    from resume_tailor_harness.profile.project_extractor import (
        _INSTRUCTIONS as project_instructions,
    )
    from resume_tailor_harness.profile.synthesis import _SYNTHESIS_INSTRUCTIONS

    for instructions in (
        extractor_instructions,
        project_instructions,
        _SYNTHESIS_INSTRUCTIONS,
    ):
        assert "aspect" in " ".join(instructions).casefold()
