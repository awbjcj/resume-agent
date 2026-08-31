import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.tables import SkillSuggestion


def _payload():
    return {
        "repos": [],
        "resources": [],
        "project": None,
        "bridge": "",
        "citations": [],
    }


def test_skill_suggestion_table_created_by_init_db():
    engine = make_engine("sqlite://")
    init_db(engine)

    with Session(engine) as session:
        session.add(
            SkillSuggestion(
                kind="skill",
                key="Kubernetes",
                payload_json=_payload(),
                fingerprint="abc123",
            )
        )
        session.commit()
        row = session.exec(
            select(SkillSuggestion).where(
                SkillSuggestion.kind == "skill",
                SkillSuggestion.key == "Kubernetes",
            )
        ).one()

    assert row.payload_json["bridge"] == ""
    assert row.generated_at is not None


def test_skill_suggestion_kind_and_key_are_unique():
    engine = make_engine("sqlite://")
    init_db(engine)

    with Session(engine) as session:
        session.add(SkillSuggestion(kind="skill", key="infra", payload_json=_payload()))
        session.commit()
        session.add(SkillSuggestion(kind="skill", key="infra", payload_json=_payload()))
        with pytest.raises(IntegrityError):
            session.commit()


def test_same_key_is_allowed_for_different_kinds():
    engine = make_engine("sqlite://")
    init_db(engine)

    with Session(engine) as session:
        session.add_all(
            [
                SkillSuggestion(kind="skill", key="infra", payload_json=_payload()),
                SkillSuggestion(kind="theme", key="infra", payload_json=_payload()),
            ]
        )
        session.commit()
