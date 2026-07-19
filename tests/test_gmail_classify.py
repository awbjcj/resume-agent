from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import EmailMessage


def _email(subject, snippet=""):
    return EmailMessage(sender="r@acme.com", sender_domain="acme.com", subject=subject, snippet=snippet)


def test_rejection_detected():
    assert classify_email(_email("Update", "Unfortunately we are not moving forward.")) == "rejection"


def test_offer_beats_other_signals():
    assert classify_email(_email("We are excited to offer you the role after your interview")) == "offer"


def test_interview_and_assessment():
    assert classify_email(_email("Let's schedule a phone screen")) == "interview"
    assert classify_email(_email("Next step: a take-home coding challenge")) == "assessment"


def test_classify_prefers_body_over_snippet():
    email = EmailMessage(
        sender="hr@acme.com",
        sender_domain="acme.com",
        subject="Update",
        snippet="no keywords here",
        body="We are pleased to offer you the position.",
    )
    assert classify_email(email) == "offer"


def test_inconclusive_returns_none_without_llm():
    assert classify_email(_email("Thanks for your time")) == "none"


def test_llm_fallback_used_only_when_rules_inconclusive():
    class _Result:
        content = "interview"

    class _LLM:
        def run(self, prompt):
            return _Result()

        async def arun(self, prompt):
            return self.run(prompt)

    assert classify_email(_email("Re: your application"), llm=_LLM()) == "interview"
