import json
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.gmail import auth
from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import workspace_paths


def _context(tmp_path: Path) -> UserContext:
    paths = workspace_paths(tmp_path, "u1")
    paths.root.mkdir(parents=True, exist_ok=True)
    return UserContext(
        user_id="u1",
        username="u1",
        role="member",
        paths=paths,
        settings=Settings(_env_file=None),
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def _token_payload(scopes: list[str]) -> str:
    return json.dumps(
        {
            "token": "ya29.fake",
            "refresh_token": "refresh",
            "client_id": "cid",
            "client_secret": "csecret",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": scopes,
            "expiry": "2099-01-01T00:00:00Z",
        }
    )


def test_token_path_prefers_context_then_data_dir(tmp_path: Path):
    with use_context(_context(tmp_path)):
        assert auth.token_path() == tmp_path / "users" / "u1" / "gmail_token.json"
    assert auth.token_path(tmp_path) == tmp_path / "gmail_token.json"
    assert auth.token_path() == Path("data/gmail_token.json")


def test_load_credentials_absent_returns_none(tmp_path: Path):
    assert auth.load_credentials(tmp_path) is None


def test_load_and_scope_check_round_trip(tmp_path: Path):
    auth.save_token_json(_token_payload(auth.GMAIL_SCOPES), tmp_path)
    creds = auth.load_credentials(tmp_path)
    assert creds is not None
    assert auth.has_compose(creds)

    auth.save_token_json(_token_payload([auth.SCOPE_READONLY]), tmp_path)
    creds = auth.load_credentials(tmp_path)
    assert creds is not None
    assert not auth.has_compose(creds)


def test_delete_token(tmp_path: Path):
    auth.save_token_json(_token_payload(auth.GMAIL_SCOPES), tmp_path)
    assert auth.delete_token(tmp_path) is True
    assert auth.delete_token(tmp_path) is False


def test_build_service_raises_when_disconnected(tmp_path: Path):
    with pytest.raises(GmailNotConnected):
        auth.build_service(tmp_path)
