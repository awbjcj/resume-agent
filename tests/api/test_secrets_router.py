"""Secrets are write-only: GET exposes status+hint, never values."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text('ANTHROPIC_API_KEY=sk-ant-test-abcd1234\nUNMANAGED=keepme\n', encoding="utf-8")
    return p


@pytest.fixture()
def client(tmp_path, env_file):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config", env_path=env_file)
    with TestClient(app) as c:
        yield c


def test_get_secrets_returns_status_not_values(client):
    body = client.get("/api/secrets").json()
    by_key = {row["key"]: row for row in body}
    assert by_key["anthropicApiKey"]["isSet"] is True
    assert by_key["anthropicApiKey"]["hint"] == "1234"
    assert by_key["openaiApiKey"]["isSet"] is False
    assert by_key["openaiApiKey"]["hint"] is None
    dumped = str(body)
    assert "sk-ant-test-abcd1234" not in dumped


def test_put_writes_only_provided_keys(client, env_file):
    resp = client.put("/api/secrets", json={"openaiApiKey": "sk-oai-xyz98765"})
    assert resp.status_code == 200
    text = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-oai-xyz98765" in text
    assert "ANTHROPIC_API_KEY=sk-ant-test-abcd1234" in text  # untouched
    assert "UNMANAGED=keepme" in text  # unmanaged keys survive


def test_put_null_clears_key(client, env_file):
    client.put("/api/secrets", json={"anthropicApiKey": None})
    body = client.get("/api/secrets").json()
    by_key = {row["key"]: row for row in body}
    assert by_key["anthropicApiKey"]["isSet"] is False


def test_models_config_readable_round_trip(client):
    body = client.get("/api/config/models").json()
    assert "cheapModel" in body and body["cheapModel"]  # defaults visible
    put = client.put("/api/config/models", json={
        "cheapModel": "claude-haiku-4-5-20251001",
        "midModel": "claude-sonnet-5",
        "premiumModel": "claude-opus-4-8",
    })
    assert put.status_code == 200
    assert client.get("/api/config/models").json()["midModel"] == "claude-sonnet-5"


def test_put_secret_does_not_clear_unrelated_empty_valued_key(client, env_file):
    env_file.write_text(
        'ANTHROPIC_API_KEY=sk-ant-test-abcd1234\nUNMANAGED=keepme\nSOME_FLAG=\n',
        encoding="utf-8",
    )
    resp = client.put("/api/secrets", json={"openaiApiKey": "sk-oai-xyz98765"})
    assert resp.status_code == 200
    assert "SOME_FLAG=" in env_file.read_text(encoding="utf-8")


def test_put_models_partial_update_preserves_other_fields(client):
    client.put("/api/config/models", json={
        "cheapModel": "custom-cheap-non-default",
        "midModel": "openai:gpt-4.1",
        "premiumModel": "custom-premium-non-default",
    })
    put = client.put("/api/config/models", json={"midModel": "gemini:custom"})
    assert put.status_code == 200
    body = client.get("/api/config/models").json()
    assert body["midModel"] == "gemini:custom"
    assert body["cheapModel"] == "custom-cheap-non-default"  # untouched by the partial PUT
    assert body["premiumModel"] == "custom-premium-non-default"  # untouched by the partial PUT


def test_model_catalog_flags_keyed_providers(client):
    body = client.get("/api/config/models/catalog").json()
    by_provider = {row["provider"]: row for row in body}
    assert by_provider["anthropic"]["hasKey"] is True  # env_file sets this key
    assert by_provider["openai"]["hasKey"] is False
    assert {"anthropic", "openai", "gemini", "deepseek"} == set(by_provider)


def test_model_catalog_entries_carry_id_label_and_capability_flags(client):
    body = client.get("/api/config/models/catalog").json()
    anthropic = next(row for row in body if row["provider"] == "anthropic")
    haiku = next(m for m in anthropic["models"] if "haiku" in m["id"])
    opus = next(m for m in anthropic["models"] if "opus" in m["id"])
    assert haiku["label"] and haiku["supportsReasoning"] is False
    assert opus["supportsReasoning"] is True
    assert haiku["supportsNativeSearch"] is True  # anthropic has native search

    deepseek = next(row for row in body if row["provider"] == "deepseek")
    assert deepseek["models"][0]["supportsNativeSearch"] is False


def test_put_secret_refreshes_app_settings(client):
    client.put("/api/secrets", json={"anthropicApiKey": "sk-ant-new-key-5678"})
    # settings served to routes must see the new value without an app restart
    from resume_agent.api.deps import get_settings_dep  # noqa: PLC0415
    app = client.app
    assert app.dependency_overrides[get_settings_dep]().anthropic_api_key == "sk-ant-new-key-5678"
