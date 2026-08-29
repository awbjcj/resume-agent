import pytest
from pydantic import ValidationError

from resume_agent.config import Settings


def test_event_reminder_defaults_match_the_design() -> None:
    settings = Settings()
    assert settings.interview_reminder_hours == 24
    assert settings.offer_deadline_reminder_days == 2


def test_zero_disables_event_reminders() -> None:
    settings = Settings(interview_reminder_hours=0, offer_deadline_reminder_days=0)
    assert settings.interview_reminder_hours == 0
    assert settings.offer_deadline_reminder_days == 0


@pytest.mark.parametrize(
    "field", ["interview_reminder_hours", "offer_deadline_reminder_days"]
)
def test_negative_event_reminder_leads_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: -1})
