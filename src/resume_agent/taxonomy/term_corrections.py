"""Append-only, scope-local corrections for UCCM term type decisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
import threading
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.custody import workspace_taxonomy_lock
from resume_agent.taxonomy.term_typing import TermConceptType, TermTypingDecision

CorrectionScope = Literal["global", "tenant", "profile", "proposed_shared"]
CorrectionAction = Literal["set_type"]
DEFAULT_TERM_TYPE_CORRECTIONS_PATH = "data/taxonomy/term_type_corrections.json"


class TermTypeCorrection(ExtensibleModel):
    id: str
    actor_id: str = Field(min_length=1)
    scope: CorrectionScope
    action: CorrectionAction
    subject_decision_id: str = Field(min_length=1)
    prior_type: TermConceptType
    new_type: TermConceptType
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    target_revision: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    sequence: int = Field(default=0, ge=0)

    @classmethod
    def create(
        cls,
        *,
        actor_id: str,
        scope: CorrectionScope,
        action: CorrectionAction,
        subject_decision_id: str,
        prior_type: TermConceptType,
        new_type: TermConceptType,
        rationale: str,
        evidence_refs: list[str],
        target_revision: str,
        timestamp: str,
    ) -> TermTypeCorrection:
        identity = json.dumps(
            {
                "actor_id": actor_id,
                "scope": scope,
                "action": action,
                "subject_decision_id": subject_decision_id,
                "prior_type": prior_type,
                "new_type": new_type,
                "rationale": rationale,
                "evidence_refs": sorted(evidence_refs),
                "target_revision": target_revision,
                "timestamp": timestamp,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return cls(
            id=f"term-correction:{event_id}",
            actor_id=actor_id,
            scope=scope,
            action=action,
            subject_decision_id=subject_decision_id,
            prior_type=prior_type,
            new_type=new_type,
            rationale=rationale,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            target_revision=target_revision,
            timestamp=timestamp,
        )


class TermTypeCorrectionLedger(ExtensibleModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    events: list[TermTypeCorrection] = Field(default_factory=list)


def term_type_corrections_file_path() -> str:
    return DEFAULT_TERM_TYPE_CORRECTIONS_PATH


def term_type_corrections_revision(events: list[TermTypeCorrection]) -> str:
    payload = sorted(
        (
            event.model_dump(mode="json", exclude={"id", "timestamp"})
            for event in events
        ),
        key=lambda value: json.dumps(
            value, sort_keys=True, separators=(",", ":")
        ),
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_term_type_corrections(path: str | Path) -> list[TermTypeCorrection]:
    source = Path(path)
    with term_type_corrections_lock(source):
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        return TermTypeCorrectionLedger.model_validate(payload).events


def term_type_corrections_lock(path: str | Path) -> threading.RLock:
    return workspace_taxonomy_lock(path)


def _event_order(event: TermTypeCorrection) -> tuple[int, int, str, str]:
    if event.sequence:
        return (1, event.sequence, event.timestamp, event.id)
    return (0, 0, event.timestamp, event.id)


def save_term_type_corrections(
    events: list[TermTypeCorrection], path: str | Path
) -> None:
    destination = Path(path)
    with term_type_corrections_lock(destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        ledger = TermTypeCorrectionLedger(events=sorted(events, key=_event_order))
        payload = json.dumps(
            ledger.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = handle.name
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None and os.path.exists(temporary_path):
                os.unlink(temporary_path)


def append_term_type_correction(
    event: TermTypeCorrection,
    path: str | Path,
) -> TermTypeCorrection:
    with term_type_corrections_lock(path):
        events = load_term_type_corrections(path)
        persisted = event.model_copy(
            update={"sequence": max((item.sequence for item in events), default=0) + 1}
        )
        save_term_type_corrections([*events, persisted], path)
        return persisted


def apply_term_type_corrections(
    decisions: list[TermTypingDecision],
    corrections: list[TermTypeCorrection],
) -> list[TermTypingDecision]:
    by_id = {decision.id: decision for decision in decisions}
    for event in sorted(corrections, key=_event_order):
        decision = by_id.get(event.subject_decision_id)
        if decision is None:
            continue
        if event.target_revision != decision.policy_revision:
            raise ValueError(
                f"correction {event.id} targets policy revision "
                f"{event.target_revision!r}, expected {decision.policy_revision!r}"
            )
        if event.prior_type != decision.concept_type:
            raise ValueError(
                f"correction {event.id} expected prior type {event.prior_type!r}, "
                f"found {decision.concept_type!r}"
            )
        by_id[event.subject_decision_id] = decision.model_copy(
            update={
                "concept_type": event.new_type,
                "concept_id": None,
                "confidence": 1.0,
                "decision_source": "correction",
                "reason_code": f"correction:{event.id}",
            }
        )
    return [by_id[decision.id] for decision in decisions]
