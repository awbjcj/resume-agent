from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
)
from resume_agent.tailor.length import format_budget, resume_stats
from resume_agent.tailor.review_config import LengthBudget, ReviewConfig


def test_length_budget_defaults_present_on_config():
    cfg = ReviewConfig()
    assert cfg.length_budget.max_experiences == 4
    assert cfg.length_budget.max_bullets_per_role == 5
    assert cfg.length_budget.target_total_bullets == 20


def test_format_budget_mentions_one_page_and_numbers():
    text = format_budget(
        LengthBudget(max_experiences=3, max_bullets_per_role=4, target_total_bullets=15)
    )
    assert "single page" in text
    assert "3" in text and "4" in text and "15" in text


def test_resume_stats_counts_experiences_projects_and_bullets():
    rc = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance="e1",
                bullets=[
                    TailoredBullet(text="a", provenance="b1"),
                    TailoredBullet(text="b", provenance="b2"),
                ],
            )
        ],
        projects=[
            TailoredProject(
                name="Looms",
                provenance="p1",
                bullets=[TailoredBullet(text="c", provenance="p1b1")],
            )
        ],
    )
    stats = resume_stats(rc)
    assert "experiences=1" in stats
    assert "projects=1" in stats
    assert "total_bullets=3" in stats
