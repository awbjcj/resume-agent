"""Append-only, scope-local corrections for UCCM term type decisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.term_typing import TermConceptType, TermTypingDecision

CorrectionScope = Literal["global", "tenant", "profile", "proposed_shared"]
CorrectionAction = Literal["set_type"]


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


def load_term_type_corrections(path: str | Path) -> list[TermTypeCorrection]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return TermTypeCorrectionLedger.model_validate(payload).events


def save_term_type_corrections(
    events: list[TermTypeCorrection], path: str | Path
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ledger = TermTypeCorrectionLedger(
        events=sorted(events, key=lambda event: (event.timestamp, event.id))
    )
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


def apply_term_type_corrections(
    decisions: list[TermTypingDecision],
    corrections: list[TermTypeCorrection],
) -> list[TermTypingDecision]:
    by_id = {decision.id: decision for decision in decisions}
    for event in sorted(corrections, key=lambda item: (item.timestamp, item.id)):
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
