from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.tenancy.system_db import LlmRate, User


def _login(client, username="owner", password="owner-password"):
    return client.post(
        "/api/auth/login", json={"identifier": username, "password": password}
    )


def _member(app, username="alice", *, disabled=False):
    user_id = f"{username:0<12}"[:12]
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username=username,
                password_hash=hash_password("member-password"),
                role="user",
                disabled_at=datetime.now(timezone.utc) if disabled else None,
            )
        )
        session.commit()
    return user_id


def test_quota_console_manages_tiers_accounts_and_audited_operations(mu_app, mu_client):
    alice = _member(mu_app)
    _member(mu_app, "disabled", disabled=True)
    assert _login(mu_client).status_code == 200

    tiers = mu_client.get("/api/admin/quota-tiers").json()["data"]
    assert {tier["id"] for tier in tiers} >= {"FREE", "SUBSCRIBER"}
    assert (
        mu_client.patch(
            "/api/admin/quota-tiers/FREE",
            json={"archived": True, "reason": "must remain default"},
        ).status_code
        == 409
    )

    account = mu_client.get(f"/api/admin/quota-accounts/{alice}").json()
    assert account["tierId"] == "FREE"
    assert account["allowanceMicros"] == 1_000_000
    updated = mu_client.patch(
        f"/api/admin/quota-accounts/{alice}",
        json={"tierId": "SUBSCRIBER", "reason": "paid plan activated"},
    )
    assert updated.status_code == 200
    assert updated.json()["allowanceMicros"] == 20_000_000

    preview = mu_client.post(
        "/api/admin/quota-operation-previews",
        json={
            "targetType": "ALL_MEMBERS",
            "actionType": "GRANT_CREDIT",
            "amountMicros": 250_000,
        },
    )
    assert preview.status_code == 201
    assert preview.json()["affectedCount"] == 2
    assert preview.json()["expiresAt"].endswith("Z")
    commit_body = {
        "previewId": preview.json()["id"],
        "reason": "service recovery grant",
        "idempotencyKey": "recovery-2026-07-30",
    }
    committed = mu_client.post("/api/admin/quota-operations", json=commit_body)
    repeated = mu_client.post("/api/admin/quota-operations", json=commit_body)
    assert committed.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == committed.json()["id"]
    assert (
        mu_client.get(f"/api/admin/quota-accounts/{alice}").json()[
            "creditBalanceMicros"
        ]
        == 250_000
    )


def test_member_usage_exposes_cost_quota_and_separate_token_totals(mu_app, mu_client):
    _member(mu_app)
    assert _login(mu_client, "alice", "member-password").status_code == 200

    usage = mu_client.get("/api/account/usage")

    assert usage.status_code == 200
    body = usage.json()
    assert body["quota"]["tierId"] == "FREE"
    assert body["costs"]["sharedQuotaCostMicros"] == 0
    assert body["sharedTokens"]["totalTokens"] == 0
    assert body["byokTokens"]["totalTokens"] == 0


def test_future_rate_version_closes_matching_open_version(mu_app, mu_client):
    assert _login(mu_client).status_code == 200
    effective_from = "2027-01-01T00:00:00Z"

    created = mu_client.post(
        "/api/admin/llm-rates",
        json={
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "contextMinTokens": 0,
            "effectiveFrom": effective_from,
            "inputMicrosPerMillion": 1_100_000,
            "cacheReadMicrosPerMillion": 110_000,
            "cacheWriteMicrosPerMillion": 1_375_000,
            "outputMicrosPerMillion": 5_500_000,
            "toolMicrosPerUnit": 10_000,
            "sourceUrl": "https://platform.claude.com/docs/en/about-claude/pricing",
            "reason": "scheduled provider price update",
        },
    )

    assert created.status_code == 201, created.text
    with Session(mu_app.state.system_engine) as session:
        versions = (
            session.execute(
                select(LlmRate)
                .where(
                    LlmRate.provider == "anthropic",
                    LlmRate.model == "claude-haiku-4-5",
                    LlmRate.context_min_tokens == 0,
                    LlmRate.context_max_tokens.is_(None),
                )
                .order_by(LlmRate.effective_from)
            )
            .scalars()
            .all()
        )
    assert len(versions) == 2
    assert versions[0].effective_to == datetime(2027, 1, 1)
    assert versions[1].effective_to is None
