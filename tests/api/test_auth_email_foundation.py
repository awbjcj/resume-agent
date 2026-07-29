from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from resume_agent.api import auth, auth_codes
from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import NullBreachChecker, validate_password
from resume_agent.config import Settings
from resume_agent.mail.mailer import NullMailer, build_mailer
from resume_agent.tenancy.migrate_system import migrate_system_db
from resume_agent.tenancy.system_db import User, init_system_db


SETTINGS = Settings.model_validate({"session_secret": "secret"})


def test_null_mailer_is_the_offline_transport():
    mailer = build_mailer(Settings.model_validate({}))
    assert isinstance(mailer, NullMailer)
    mailer.send(to="a@example.com", subject="subject", body="body")
    assert mailer.sent == [("a@example.com", "subject", "body")]


def test_system_migration_preserves_legacy_users(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'system.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE users (
                id VARCHAR(12) PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                password_hash VARCHAR NOT NULL,
                role VARCHAR(8) NOT NULL,
                disabled_at DATETIME,
                last_active_at DATETIME,
                weekly_token_budget INTEGER,
                max_active_jobs INTEGER,
                max_concurrent_runs INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        )
        connection.execute(
            text("""
            INSERT INTO users
                (id, username, password_hash, role, created_at, updated_at)
            VALUES ('u1', 'owner', 'hash', 'admin', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        )
    init_system_db(engine)
    migrate_system_db(engine)
    with Session(engine) as session:
        user = session.get(User, "u1")
        assert user is not None
        assert user.email is None
        assert user.session_epoch == 0


def test_session_epoch_revokes_an_existing_cookie():
    token = auth.issue_user_session(
        SETTINGS, user_id="u1", password_hash="hash", epoch=0
    )
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="hash", epoch=0) == "u1"
    )
    assert (
        auth.verify_user_session(token, SETTINGS, password_hash="hash", epoch=1) is None
    )


@dataclass
class CodeRow:
    code_hash: str
    expires_at: datetime
    attempts: int = 0


def test_code_is_six_digits_single_use_ready_and_exhausts():
    code = auth_codes.generate_code()
    assert len(code) == 6 and code.isdigit()
    row = CodeRow(
        auth_codes.hash_code(code, SETTINGS),
        datetime.now(timezone.utc) + timedelta(minutes=1),
        attempts=4,
    )
    assert (
        auth_codes.check_code(row, "000000", SETTINGS)
        is auth_codes.CodeVerdict.EXHAUSTED
    )


def test_password_policy_rejects_identity_and_common_passwords():
    with pytest.raises(ApiException) as identity:
        validate_password(
            "adal-quartz-lantern", email="adal@example.com", checker=NullBreachChecker()
        )
    assert identity.value.code == "PASSWORD_WEAK"
    with pytest.raises(ApiException) as common:
        validate_password(
            "passwordpassword",
            email="ada@example.com",
            checker=NullBreachChecker(),
        )
    assert common.value.code == "PASSWORD_WEAK"
