# Resume Agent v2 — Gmail Auto-Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read recent Gmail messages (read-only), match each to a tracked application by company, classify it (rejection / interview / assessment / offer) with a rules pre-filter and an optional cheap-LLM fallback, and **propose** application-status transitions. `sync-status` lists the proposals; `--apply` applies them. Status is **never** flipped silently.

**Architecture:** This is **Plan 5 of 6** for v2 (spec `docs/superpowers/specs/2026-06-11-resume-agent-v2-connectors-design.md`), an independent leaf depending only on v1 tracking. All the decision logic — classification, matching, and the forward-only transition guard — is **pure and unit-tested**; the only un-CI-tested code is the Gmail I/O shell (like the LinkedIn driver). The human-confirm gate is the default: proposals print; applying requires the explicit `--apply` flag.

**Tech Stack:** Python 3.13, uv, **google-api-python-client + google-auth + google-auth-oauthlib** (new deps), SQLModel, Typer, pytest.

**Depends on:** v1 tracking merged (`tracking.tables` `Application`/`ApplicationStatus`/`Job`, `tracking.repository.update_application_status`, `cli._engine`). Optionally reuses `llm_runner.Runner` for the LLM fallback.

> **Commit convention:** every commit ends with `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`.

---

## Architecture notes (the two lenses)

**Deepening:** three deep, pure modules behind tiny signatures — `classify_email(email) -> str`, `match_email_to_application(email, jobs) -> Job | None`, `propose_transitions(emails, pairs, classify) -> list[Proposal]`. The **interface is the test surface**: every risky heuristic is exercised against constructed `EmailMessage`s with no network. Gmail's API surface is hidden behind `fetch_recent_messages`, so the rest of the system depends on the small `EmailMessage` dataclass, not Google's payloads.

**Restraint (karpathy):** read-only scope (no label/archive writes); no polling daemon (a manual command); the LLM fallback is *optional* and only fires when rules are inconclusive — most mail is classified for free. The forward-only guard prevents nonsensical proposals (e.g. moving an `offer` back to `interview`) without modeling a full state machine.

---

## File Structure

```
pyproject.toml                         # MODIFY — add google api deps
src/resume_agent/gmail/
  __init__.py                          # CREATE
  client.py                            # CREATE — EmailMessage + Gmail I/O (not CI-tested)
  classify.py                          # CREATE — classify_email (rules + LLM fallback)
  match.py                             # CREATE — match_email_to_application
  propose.py                           # CREATE — Proposal + propose_transitions
src/resume_agent/tracking/queries.py   # MODIFY — application_job_pairs
src/resume_agent/cli.py                # MODIFY — sync-status command
tests/test_gmail_classify.py           # CREATE
tests/test_gmail_match.py              # CREATE
tests/test_gmail_propose.py            # CREATE
tests/test_cli_sync_status.py          # CREATE
```

---

## Task 1: dependencies + `EmailMessage` + Gmail client shell

**Files:**
- Modify: `pyproject.toml`
- Create: `src/resume_agent/gmail/__init__.py`, `src/resume_agent/gmail/client.py`

> The Gmail I/O is the only un-CI-tested code in this plan (a real OAuth-authenticated API). First run opens a consent screen once; the token caches to `data/gmail_token.json` (git-ignored), mirroring the LinkedIn burner-session pattern. `EmailMessage` (the boundary type) is plain data.

- [ ] **Step 1: Add dependencies**

Run: `uv add google-api-python-client google-auth google-auth-oauthlib`
Expected: `pyproject.toml` + `uv.lock` updated; install succeeds.

- [ ] **Step 2: Ignore the cached token**

Add to `.gitignore`:
```gitignore
data/gmail_token.json
```

- [ ] **Step 3: Implement the boundary type + client shell**

Create `src/resume_agent/gmail/__init__.py`:
```python
"""Read-only Gmail integration: fetch → match → classify → PROPOSE status transitions."""
```

Create `src/resume_agent/gmail/client.py`:
```python
import base64
from dataclasses import dataclass
from pathlib import Path

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_PATH = "config/gmail_credentials.json"
TOKEN_PATH = "data/gmail_token.json"


@dataclass
class EmailMessage:
    """The minimal email shape the matcher/classifier need."""

    sender: str
    sender_domain: str
    subject: str
    snippet: str
    thread_id: str | None = None


def build_gmail_service(credentials_path: str = CREDENTIALS_PATH, token_path: str = TOKEN_PATH):
    """Build an authenticated, read-only Gmail service. Opens a consent screen on first run."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _domain(sender: str) -> str:
    if "@" not in sender:
        return ""
    return sender.split("@", 1)[1].rstrip(">").strip().lower()


def fetch_recent_messages(service, max_results: int = 50) -> list[EmailMessage]:
    """Fetch recent inbox messages as EmailMessages (read-only)."""
    listing = service.users().messages().list(userId="me", maxResults=max_results, labelIds=["INBOX"]).execute()
    messages: list[EmailMessage] = []
    for ref in listing.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="metadata",
                                             metadataHeaders=["From", "Subject"]).execute()
        headers = msg.get("payload", {}).get("headers", [])
        sender = _header(headers, "From")
        messages.append(
            EmailMessage(
                sender=sender,
                sender_domain=_domain(sender),
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                thread_id=msg.get("threadId"),
            )
        )
    return messages


# base64 retained for future full-body fetch; metadata format needs no decode yet.
_ = base64
```

- [ ] **Step 4: Verify it imports without network**

Run: `uv run python -c "from resume_agent.gmail.client import EmailMessage, build_gmail_service, fetch_recent_messages; print('import ok')"`
Expected: prints `import ok` (no API call at import time).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src/resume_agent/gmail/__init__.py src/resume_agent/gmail/client.py
git commit -m "feat(gmail): deps + EmailMessage + read-only client shell" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: email classification (rules + optional LLM fallback)

**Files:**
- Create: `src/resume_agent/gmail/classify.py`
- Test: `tests/test_gmail_classify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gmail_classify.py`:
```python
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


def test_inconclusive_returns_none_without_llm():
    assert classify_email(_email("Thanks for your time")) == "none"


def test_llm_fallback_used_only_when_rules_inconclusive():
    class _Result:
        content = "interview"

    class _LLM:
        def run(self, prompt):
            return _Result()

    assert classify_email(_email("Re: your application"), llm=_LLM()) == "interview"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gmail_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.gmail.classify'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/gmail/classify.py`:
```python
from resume_agent.gmail.client import EmailMessage
from resume_agent.llm_runner import Runner

_LABELS = ("rejection", "interview", "assessment", "offer")

# Checked in priority order: a positive offer outranks a rejection phrase, which
# outranks assessment/interview (a rejection email often mentions "interview").
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("offer", ("pleased to offer", "offer letter", "excited to offer", "extend an offer")),
    ("rejection", ("unfortunately", "not moving forward", "decided not to", "other candidates",
                   "won't be proceeding", "regret to inform", "will not be moving")),
    ("assessment", ("assessment", "coding challenge", "take-home", "hackerrank", "codesignal", "online test")),
    ("interview", ("interview", "schedule a call", "phone screen", "meet with", "your availability")),
]


def classify_email(email: EmailMessage, llm: Runner | None = None) -> str:
    """Return one of rejection|interview|assessment|offer|none.

    Deterministic rules first; an optional LLM adjudicates only inconclusive mail.
    """
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gmail_classify.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/gmail/classify.py tests/test_gmail_classify.py
git commit -m "feat(gmail): rules+LLM email classification" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: match an email to a tracked job

**Files:**
- Create: `src/resume_agent/gmail/match.py`
- Test: `tests/test_gmail_match.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gmail_match.py`:
```python
from resume_agent.gmail.client import EmailMessage
from resume_agent.gmail.match import match_email_to_application
from resume_agent.tracking.tables import Job


def _job(id_, company):
    return Job(id=id_, source="manual", company=company, title="Eng")


def test_matches_company_in_sender_domain():
    email = EmailMessage(sender="ta@acme.com", sender_domain="acme.com", subject="Hi", snippet="")
    job = match_email_to_application(email, [_job(1, "Acme Corp"), _job(2, "Beta")])
    assert job.id == 1


def test_matches_company_in_subject_text():
    email = EmailMessage(sender="noreply@greenhouse.io", sender_domain="greenhouse.io",
                         subject="Your application to Beta", snippet="")
    job = match_email_to_application(email, [_job(1, "Acme"), _job(2, "Beta")])
    assert job.id == 2


def test_no_match_returns_none():
    email = EmailMessage(sender="x@unknown.com", sender_domain="unknown.com", subject="Newsletter", snippet="")
    assert match_email_to_application(email, [_job(1, "Acme")]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gmail_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.gmail.match'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/gmail/match.py`:
```python
import re

from resume_agent.gmail.client import EmailMessage
from resume_agent.tracking.tables import Job


def _company_token(company: str) -> str:
    """The first alphanumeric word of a company name, lowercased (e.g. 'Acme Corp' -> 'acme')."""
    words = re.findall(r"[a-z0-9]+", company.lower())
    return words[0] if words else ""


def match_email_to_application(email: EmailMessage, jobs: list[Job]) -> Job | None:
    """Return the job whose company appears in the email's sender domain or subject/snippet."""
    haystack = f"{email.subject} {email.snippet}".lower()
    domain = (email.sender_domain or "").lower()
    for job in jobs:
        if not job.company:
            continue
        token = _company_token(job.company)
        if token and (token in domain or token in haystack):
            return job
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gmail_match.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/gmail/match.py tests/test_gmail_match.py
git commit -m "feat(gmail): match email to tracked job by company" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: propose transitions (forward-only) + pairs helper

**Files:**
- Create: `src/resume_agent/gmail/propose.py`
- Modify: `src/resume_agent/tracking/queries.py`
- Test: `tests/test_gmail_propose.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gmail_propose.py`:
```python
from resume_agent.gmail.client import EmailMessage
from resume_agent.gmail.propose import Proposal, propose_transitions
from resume_agent.tracking.tables import Application, ApplicationStatus, Job


def _email(subject, domain="acme.com"):
    return EmailMessage(sender=f"r@{domain}", sender_domain=domain, subject=subject, snippet="")


def _pair(app_id, status, company):
    job = Job(id=app_id, source="manual", company=company, title="Eng")
    app = Application(id=app_id, job_id=app_id, status=status)
    return (app, job)


def _classify(email):
    s = email.subject.lower()
    if "offer" in s:
        return "offer"
    if "interview" in s:
        return "interview"
    if "unfortunately" in s:
        return "rejection"
    return "none"


def test_proposes_forward_transition():
    pairs = [_pair(1, ApplicationStatus.submitted.value, "Acme")]
    props = propose_transitions([_email("interview invite")], pairs, _classify)
    assert props == [Proposal(1, "Acme — Eng", "submitted", "interview", "interview invite")]


def test_skips_backward_transition():
    pairs = [_pair(1, ApplicationStatus.offer.value, "Acme")]
    # An "interview" email after an offer must NOT regress the status.
    assert propose_transitions([_email("interview follow-up")], pairs, _classify) == []


def test_rejection_allowed_from_active_state():
    pairs = [_pair(1, ApplicationStatus.interview.value, "Acme")]
    props = propose_transitions([_email("unfortunately update")], pairs, _classify)
    assert props[0].proposed_status == "rejected"


def test_unmatched_or_none_email_yields_nothing():
    pairs = [_pair(1, ApplicationStatus.submitted.value, "Acme")]
    assert propose_transitions([_email("newsletter", domain="other.com")], pairs, _classify) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gmail_propose.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.gmail.propose'`.

- [ ] **Step 3: Implement the proposer**

Create `src/resume_agent/gmail/propose.py`:
```python
from dataclasses import dataclass

from resume_agent.gmail.client import EmailMessage
from resume_agent.gmail.match import match_email_to_application
from resume_agent.tracking.tables import Application, ApplicationStatus, Job

_CLASS_TO_STATUS = {
    "rejection": ApplicationStatus.rejected.value,
    "interview": ApplicationStatus.interview.value,
    "assessment": ApplicationStatus.interview.value,
    "offer": ApplicationStatus.offer.value,
}
_RANK = {"ready": 0, "submitted": 1, "interview": 2, "offer": 3}
_TERMINAL = {ApplicationStatus.rejected.value, ApplicationStatus.closed.value}


@dataclass
class Proposal:
    application_id: int
    label: str
    current_status: str
    proposed_status: str
    evidence: str


def _is_forward(current: str, proposed: str) -> bool:
    if current in _TERMINAL:
        return False
    if proposed == ApplicationStatus.rejected.value:
        return True  # a rejection can arrive from any active state
    return _RANK.get(proposed, 0) > _RANK.get(current, 0)


def propose_transitions(emails, pairs: list[tuple[Application, Job]], classify) -> list[Proposal]:
    """Match each email to an application and propose a forward status change. Pure; applies nothing."""
    by_job_id = {job.id: (app, job) for app, job in pairs if job.id is not None}
    jobs = [job for _, job in pairs]
    proposals: list[Proposal] = []
    for email in emails:
        job = match_email_to_application(email, jobs)
        if job is None or job.id not in by_job_id:
            continue
        app, job = by_job_id[job.id]
        proposed = _CLASS_TO_STATUS.get(classify(email))
        if proposed is None or app.id is None or not _is_forward(app.status, proposed):
            continue
        proposals.append(
            Proposal(app.id, f"{job.company} — {job.title}", app.status, proposed, email.subject)
        )
    return proposals
```

- [ ] **Step 4: Add the pairs query helper**

In `src/resume_agent/tracking/queries.py`, update the tables import to include `Application`:
```python
from resume_agent.tracking.tables import Application, Job, JobStatus
```
Add at the end of the file:
```python
def application_job_pairs(session: Session) -> list[tuple[Application, Job]]:
    """Every application paired with its job (for matching emails to applications)."""
    pairs: list[tuple[Application, Job]] = []
    for app in session.exec(select(Application)).all():
        job = session.get(Job, app.job_id)
        if job is not None:
            pairs.append((app, job))
    return pairs
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_gmail_propose.py tests/test_tracking_queries.py -v`
Expected: PASS (proposer tests + existing query tests still green).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/gmail/propose.py src/resume_agent/tracking/queries.py tests/test_gmail_propose.py
git commit -m "feat(gmail): forward-only transition proposals + pairs helper" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `sync-status` CLI command

**Files:**
- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_cli_sync_status.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_sync_status.py`:
```python
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.gmail.client import EmailMessage
from resume_agent.tracking.repository import application_for_job, save_application
from resume_agent.tracking.tables import Application, ApplicationStatus

runner = CliRunner()


def _seed(db_url):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        save_application(s, Application(job_id=job.id, status=ApplicationStatus.submitted.value))


def test_sync_status_lists_then_applies(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed(db_url)
    monkeypatch.setattr(cli, "build_gmail_service", lambda: object())
    monkeypatch.setattr(
        cli, "fetch_recent_messages",
        lambda service, max_results=50: [
            EmailMessage(sender="ta@acme.com", sender_domain="acme.com",
                         subject="Interview invitation", snippet="schedule a phone screen")
        ],
    )

    listed = runner.invoke(cli.app, ["sync-status", "--db-url", db_url])
    assert listed.exit_code == 0, listed.output
    assert "Acme" in listed.output and "interview" in listed.output
    assert "--apply" in listed.output  # nudge, nothing applied yet

    applied = runner.invoke(cli.app, ["sync-status", "--apply", "--db-url", db_url])
    assert applied.exit_code == 0, applied.output

    # The seeded Acme application should now be 'interview'.
    from sqlmodel import select

    from resume_agent.tracking.tables import Job

    with get_session(make_engine(db_url)) as s:
        acme = s.exec(select(Job).where(Job.company == "Acme")).first()
        assert application_for_job(s, acme.id).status == ApplicationStatus.interview.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_sync_status.py -v`
Expected: FAIL — `AttributeError: module 'resume_agent.cli' has no attribute 'build_gmail_service'`.

- [ ] **Step 3: Add imports**

In `src/resume_agent/cli.py`, add:
```python
from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import build_gmail_service, fetch_recent_messages
from resume_agent.gmail.propose import propose_transitions
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import update_application_status
```
(If `update_application_status` is already imported, don't duplicate.)

- [ ] **Step 4: Add the command**

Add after `dashboard_cmd` in `src/resume_agent/cli.py`:
```python
@app.command("sync-status")
def sync_status_cmd(
    apply: bool = typer.Option(False, "--apply", help="Apply the proposed transitions (default: list only)."),
    max_results: int = typer.Option(50, help="How many recent emails to scan."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scan recent Gmail and propose application-status updates (apply only with --apply)."""
    service = build_gmail_service()
    emails = fetch_recent_messages(service, max_results=max_results)
    engine = _engine(db_url)
    with get_session(engine) as session:
        pairs = application_job_pairs(session)
        proposals = propose_transitions(emails, pairs, classify_email)
        if not proposals:
            typer.echo("No status changes proposed.")
            raise typer.Exit(code=0)
        for p in proposals:
            typer.echo(f"  {p.label}: {p.current_status} → {p.proposed_status}  ({p.evidence})")
        if apply:
            for p in proposals:
                update_application_status(session, p.application_id, p.proposed_status)
            typer.echo(f"Applied {len(proposals)} transition(s).")
        else:
            typer.echo("Re-run with --apply to apply these transitions.")
```

- [ ] **Step 5: Run test, then the full suite**

Run: `uv run pytest tests/test_cli_sync_status.py -v`
Expected: PASS (1 test).

Run: `uv run pytest -q`
Expected: ALL pass.

Run: `uv run resume-agent sync-status --help`
Expected: help text, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_sync_status.py
git commit -m "feat(gmail): sync-status command (propose + --apply)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.5, Decision #11):** read-only Gmail client — Task 1; rules + cheap-LLM classification — Task 2; email→application matching — Task 3; forward-only transition proposals — Task 4; `sync-status` proposing by default, applying only with `--apply` (human gate; never silent) — Task 5. Canned-email-fixture testing of matching + classification — Tasks 2/3/4 (constructed `EmailMessage`s, no network).

**Placeholder scan:** none — full client, classifier, matcher, proposer, helper, and command. The Gmail I/O is intentionally the one un-CI-tested shell (called out in Task 1), patched in the CLI test.

**Type consistency:** `EmailMessage` fields are constructed identically across Tasks 1–5. `classify_email(email, llm=None) -> str`, `match_email_to_application(email, jobs) -> Job | None`, `propose_transitions(emails, pairs, classify) -> list[Proposal]`, and `application_job_pairs(session) -> list[tuple[Application, Job]]` match every call site. `Proposal` fields match the equality assertions in Task 4 and the print/apply in Task 5.

**Scoping note:** dashboard surfacing of proposals (mentioned in the spec) is satisfied here by the CLI proposal list + explicit `--apply` gate — both are valid human-confirm surfaces. A dashboard panel can be added later as a thin reader of the same `propose_transitions`; not built (YAGNI).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-agent-v2-gmail-auto-status.md`. Execute via **superpowers:subagent-driven-development** or **superpowers:executing-plans**. Independent of Plans 4/6. Last leaf: **Plan 6 (application analytics)**.
