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


def test_peak_and_off_peak_rates_coexist_but_same_period_still_overlaps(
    mu_app, mu_client
):
    assert _login(mu_client).status_code == 200
    effective_from = "2027-02-01T00:00:00Z"

    def _create(rate_period, input_micros):
        return mu_client.post(
            "/api/admin/llm-rates",
            json={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "contextMinTokens": 0,
                "ratePeriod": rate_period,
                "effectiveFrom": effective_from,
                "inputMicrosPerMillion": input_micros,
                "cacheReadMicrosPerMillion": 7_000,
                "outputMicrosPerMillion": 660_000,
                "sourceUrl": "https://api-docs.deepseek.com/quick_start/pricing",
                "reason": "peak/off-peak overlap test",
            },
        )

    off_peak = _create("off_peak", 220_000)
    assert off_peak.status_code == 201, off_peak.text
    peak = _create("peak", 440_000)
    assert peak.status_code == 201, peak.text

    duplicate_peak = _create("peak", 450_000)
    assert duplicate_peak.status_code == 409
    assert duplicate_peak.json()["error"]["code"] == "RATE_RANGE_OVERLAP"

    with Session(mu_app.state.system_engine) as session:
        rows = (
            session.execute(
                select(LlmRate).where(
                    LlmRate.provider == "deepseek",
                    LlmRate.model == "deepseek-v4-flash",
                    LlmRate.effective_from == datetime(2027, 2, 1),
                )
            )
            .scalars()
            .all()
        )
    assert {row.rate_period for row in rows} == {"peak", "off_peak"}
    assert len(rows) == 2


def test_period_rate_rejected_while_a_flat_rate_still_covers_the_window(
    mu_app, mu_client
):
    # claude-haiku-4-5 has an open-ended (effective_to=None) flat rate from
    # the initial seed. A "peak"-only rate would leave off-peak hours with no
    # active rate if it silently superseded that flat row, so it must be
    # rejected rather than coexist ambiguously.
    assert _login(mu_client).status_code == 200
    response = mu_client.post(
        "/api/admin/llm-rates",
        json={
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "contextMinTokens": 0,
            "ratePeriod": "peak",
            "effectiveFrom": "2027-03-01T00:00:00Z",
            "inputMicrosPerMillion": 1_000_000,
            "outputMicrosPerMillion": 5_000_000,
            "sourceUrl": "https://platform.claude.com/docs/en/about-claude/pricing",
            "reason": "should be rejected: flat rate still open",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RATE_RANGE_OVERLAP"
