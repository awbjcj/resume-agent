from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import (
    ApiToken,
    InviteCode,
    SystemSetting,
    UsageEvent,
    init_system_db,
    make_system_engine,
)


def test_secret_helpers_and_system_tables_roundtrip(tmp_path):
    invite = mint_secret("inv_")
    token = mint_secret("rat_")
    assert invite.startswith("inv_") and token.startswith("rat_")
    assert invite != mint_secret("inv_")
    assert len(hash_secret(invite)) == 64

    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            InviteCode(
                id="invite000001",
                code_hash=hash_secret(invite),
                created_by="admin000001",
                expires_at=now + timedelta(days=14),
            )
        )
        session.add(
            ApiToken(
                id="token0000001",
                user_id="admin000001",
                name="cli",
                token_hash=hash_secret(token),
            )
        )
        session.add(
            UsageEvent(
                user_id="admin000001",
                provider="anthropic",
                model="claude",
                input_tokens=10,
                output_tokens=5,
                weighted_total=25,
            )
        )
        session.add(SystemSetting(key="max_concurrent_runs", value="2"))
        session.commit()
    with Session(engine) as session:
        assert session.execute(select(InviteCode)).scalar_one().used_at is None
        assert session.execute(select(ApiToken)).scalar_one().revoked_at is None
        assert session.execute(select(UsageEvent)).scalar_one().weighted_total == 25
        setting = session.get(SystemSetting, "max_concurrent_runs")
        assert setting is not None
        assert setting.value == "2"
    engine.dispose()
