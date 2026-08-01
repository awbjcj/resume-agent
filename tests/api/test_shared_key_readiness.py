import io

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resume_agent.api.auth import hash_password
from resume_agent.services import profile_build
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.quotas import (
    FREE_ALLOWANCE_MICROS,
    assign_new_member,
    charge_shared_cost,
)
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import provision_workspace


def _add_member(app) -> tuple[str, str]:
    user_id = new_user_id()
    password = "member-password"
    with Session(app.state.system_engine) as session:
        session.add(
            User(
                id=user_id,
                username="member",
                password_hash=hash_password(password, iterations=1000),
                role="user",
            )
        )
        assign_new_member(session, user_id)
        session.commit()
    provision_workspace(app.state.data_dir, user_id)
    return user_id, password


def test_shared_balance_opens_profile_build_and_model_selection_until_exhausted(
    mu_app, monkeypatch
):
    mu_app.state.settings = mu_app.state.settings.model_copy(
        update={
            "anthropic_api_key": "railway-anthropic-key",
            "cost_quota_enforcement": "enforce",
        }
    )
    monkeypatch.setattr(
        profile_build,
        "run_corpus_build",
        lambda reporter, **kwargs: {
            "experiences": 1,
            "projects": 0,
            "warnings": [],
        },
    )

    with TestClient(mu_app, base_url="https://testserver") as client:
        user_id, password = _add_member(mu_app)
        login = client.post(
            "/api/auth/login",
            json={"identifier": "member", "password": password},
        )
        assert login.status_code == 200

        setup = client.get("/api/setup/status").json()
        assert setup["secrets"]["anthropicKey"] is True
        assert setup["secrets"]["anyLlmKey"] is True

        catalog = client.get("/api/config/models/catalog").json()
        anthropic = next(row for row in catalog if row["provider"] == "anthropic")
        assert anthropic["hasKey"] is True

        client.post(
            "/api/profile/documents",
            files={
                "file": (
                    "resume.txt",
                    io.BytesIO(b"experience"),
                    "text/plain",
                )
            },
            data={"docType": "resume"},
        )
        assert client.post("/api/profile/build").status_code == 202

        charge_shared_cost(
            mu_app.state.system_engine,
            user_id,
            FREE_ALLOWANCE_MICROS,
        )

        exhausted_setup = client.get("/api/setup/status").json()
        assert exhausted_setup["secrets"]["anthropicKey"] is False
        assert exhausted_setup["secrets"]["anyLlmKey"] is False

        exhausted_catalog = client.get("/api/config/models/catalog").json()
        exhausted_anthropic = next(
            row for row in exhausted_catalog if row["provider"] == "anthropic"
        )
        assert exhausted_anthropic["hasKey"] is False
        assert client.post("/api/profile/build").status_code == 400

        client.put(
            "/api/secrets",
            json={"anthropicApiKey": "member-anthropic-key"},
        )
        fallback_setup = client.get("/api/setup/status").json()
        assert fallback_setup["secrets"]["anthropicKey"] is True
        fallback_catalog = client.get("/api/config/models/catalog").json()
        fallback_anthropic = next(
            row for row in fallback_catalog if row["provider"] == "anthropic"
        )
        assert fallback_anthropic["hasKey"] is True
        assert client.post("/api/profile/build").status_code == 202
