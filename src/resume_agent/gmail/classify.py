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
    text = f"{email.subject}\n{email.snippet}".lower()
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
        f"Subject: {email.subject}\nBody: {email.snippet}"
    )
