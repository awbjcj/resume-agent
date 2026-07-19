from resume_agent.gmail.client import EmailMessage
from resume_agent.llm_runner import Runner

_LABELS = ("rejection", "interview", "assessment", "offer")

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("offer", ("pleased to offer", "offer letter", "excited to offer", "extend an offer")),
    (
        "rejection",
        (
            "unfortunately",
            "not moving forward",
            "decided not to",
            "other candidates",
            "won't be proceeding",
            "regret to inform",
            "will not be moving",
        ),
    ),
    (
        "assessment",
        ("assessment", "coding challenge", "take-home", "hackerrank", "codesignal", "online test"),
    ),
    ("interview", ("interview", "schedule a call", "phone screen", "meet with", "your availability")),
]


def classify_email(email: EmailMessage, llm: Runner | None = None) -> str:
    """Return one of rejection|interview|assessment|offer|none."""
    text = f"{email.subject}\n{email.body or email.snippet}".lower()
    for label, phrases in _RULES:
        if any(phrase in text for phrase in phrases):
            return label
    if llm is not None:
        guess = str(getattr(llm.run(_prompt(email)), "content", "")).strip().lower()
        if guess in _LABELS:
            return guess
    return "none"


def _prompt(email: EmailMessage) -> str:
    return (
        "Classify this recruiting email as exactly one word: "
        "rejection, interview, assessment, offer, or none.\n\n"
        f"Subject: {email.subject}\nBody: {email.body or email.snippet}"
    )


def build_classifier_llm() -> Runner | None:
    """Cheap-tier fallback agent, or None when that provider has no key."""
    from resume_agent.llm_runner import (
        AgentRunner,
        build_model,
        resolve_api_key,
        retry_kwargs,
    )
    from resume_agent.tailor.agents import model_for_tier

    model_id = model_for_tier("cheap")
    if not resolve_api_key(model_id):
        return None
    from agno.agent import Agent

    return AgentRunner(Agent(model=build_model(model_id), **retry_kwargs()))


def hydrating_classifier(service, llm: Runner | None):
    """Classifier that lazily fetches the full body for matched messages.

    propose_transitions only calls classify AFTER an email matched an
    application, so the body fetch happens for matches only.
    """
    from resume_agent.gmail.client import fetch_message_body

    def classify(email: EmailMessage) -> str:
        if email.body is None and email.message_id:
            try:
                email.body = fetch_message_body(service, email.message_id)
            except Exception:  # noqa: BLE001 — snippet-only is a fine fallback
                email.body = ""
        return classify_email(email, llm)

    return classify
