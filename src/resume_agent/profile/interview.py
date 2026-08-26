"""Profile Interview schemas, durable history, tools, and agents (ADR 0005)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.progress import atomic_write_text
from resume_agent.profile.corpus import doc_path, load_manifest

_DOC_READ_CAP = 20_000
_HISTORY_NAME = "interview_history.json"
_HISTORY_LOCK = threading.RLock()


class InterviewQuestion(ExtensibleModel):
    id: str = ""
    gap: str = ""
    why_it_matters: str = ""
    question_text: str = ""
    related_ref: str = ""


class ResearchAction(ExtensibleModel):
    kind: Literal["harvest_repo", "request_url"] = "request_url"
    target: str = ""
    why: str = ""


class InterviewRound(ExtensibleModel):
    questions: list[InterviewQuestion] = Field(default_factory=list)
    research_actions: list[ResearchAction] = Field(default_factory=list)


class _HistoryAnswer(ExtensibleModel):
    question_id: str
    doc_id: str


class _HistoryRound(ExtensibleModel):
    round_id: str
    run_id: str
    asked_at: str
    questions: list[InterviewQuestion] = Field(default_factory=list)
    research_actions: list[ResearchAction] = Field(default_factory=list)
    answers: list[_HistoryAnswer] = Field(default_factory=list)
    submitted_at: str | None = None


class _History(ExtensibleModel):
    rounds: list[_HistoryRound] = Field(default_factory=list)


def _history_path(profile_dir: Path | str) -> Path:
    return Path(profile_dir) / _HISTORY_NAME


def load_history(profile_dir: Path | str) -> dict:
    path = _history_path(profile_dir)
    if not path.exists():
        return {"rounds": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _History.model_validate(raw).model_dump(mode="json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid interview history: {path}") from exc


def _save_history(profile_dir: Path | str, history: dict) -> None:
    validated = _History.model_validate(history)
    atomic_write_text(
        _history_path(profile_dir),
        validated.model_dump_json(indent=2) + "\n",
        root=profile_dir,
    )


def append_round(
    profile_dir: Path | str,
    round_id: str,
    run_id: str,
    round_: InterviewRound,
) -> None:
    with _HISTORY_LOCK:
        history = load_history(profile_dir)
        if any(row["round_id"] == round_id for row in history["rounds"]):
            raise ValueError("round already exists")
        history["rounds"].append(
            {
                "round_id": round_id,
                "run_id": run_id,
                "asked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "questions": [question.model_dump() for question in round_.questions],
                "research_actions": [
                    action.model_dump() for action in round_.research_actions
                ],
                "answers": [],
                "submitted_at": None,
            }
        )
        _save_history(profile_dir, history)


def asked_questions(profile_dir: Path | str) -> list[str]:
    return [
        question["question_text"]
        for row in load_history(profile_dir)["rounds"]
        for question in row["questions"]
        if question.get("question_text")
    ]


def make_corpus_tools(profile_dir: Path | str) -> list[Callable[..., str]]:
    """Create bounded read-only corpus tools; every tool returns an error string."""
    root = Path(profile_dir)

    def list_corpus_documents() -> str:
        """List corpus document ids, filenames, modes, origins, and sizes."""
        try:
            lines = []
            for doc in load_manifest(root).docs:
                path = doc_path(root, doc)
                size = path.stat().st_size if path.exists() else 0
                lines.append(
                    f"{doc.id} | {doc.filename} | mode={doc.mode} | "
                    f"origin={doc.origin} | {size} bytes"
                )
            return "\n".join(lines) or "(corpus is empty)"
        except Exception as exc:  # noqa: BLE001 - tools return bounded errors.
            return f"could not list corpus ({type(exc).__name__})"

    def read_document(doc_id: str) -> str:
        """Read one corpus document by id, capped at 20,000 characters."""
        try:
            doc = next(
                (
                    candidate
                    for candidate in load_manifest(root).docs
                    if candidate.id == doc_id
                ),
                None,
            )
            if doc is None:
                return f"unknown document id: {doc_id}"
            text = doc_path(root, doc).read_text(encoding="utf-8", errors="replace")
            return (
                text
                if len(text) <= _DOC_READ_CAP
                else text[:_DOC_READ_CAP] + "\n…(truncated)"
            )
        except Exception as exc:  # noqa: BLE001 - tools return bounded errors.
            return f"could not read document ({type(exc).__name__})"

    def list_github_sources() -> str:
        """List harvested GitHub source filenames and sizes."""
        try:
            lines = []
            for doc in load_manifest(root).docs:
                if doc.origin != "github":
                    continue
                path = doc_path(root, doc)
                size = path.stat().st_size if path.exists() else 0
                lines.append(f"{doc.id} | {doc.filename} | {size} bytes")
            return "\n".join(lines) or "(no GitHub sources harvested)"
        except Exception as exc:  # noqa: BLE001 - tools return bounded errors.
            return f"could not list GitHub sources ({type(exc).__name__})"

    return [list_corpus_documents, read_document, list_github_sources]
