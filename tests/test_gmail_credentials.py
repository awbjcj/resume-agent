from pathlib import Path

from resume_tailor_harness.api.schemas.secrets import SECRET_FIELDS
from resume_tailor_harness.config import Settings
from resume_tailor_harness.tenancy.workspace import (
    effective_settings,
    workspace_paths,
)


def test_settings_have_gmail_fields():
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.google_oauth_client_id == ""
    assert s.google_oauth_client_secret == ""
    assert s.gmail_sync_interval_hours == 6
    assert s.follow_up_days == 14
    assert s.gmail_max_messages == 50


def test_workspace_gmail_token_path(tmp_path: Path):
    paths = workspace_paths(tmp_path, "u1")
    assert paths.gmail_token == tmp_path / "users" / "u1" / "gmail_token.json"


def test_google_client_overlays_from_secrets_env(tmp_path: Path):
    paths = workspace_paths(tmp_path, "u1")
    paths.root.mkdir(parents=True)
    paths.secrets_env.write_text(
        "GOOGLE_OAUTH_CLIENT_ID=own-client\nGOOGLE_OAUTH_CLIENT_SECRET=own-secret\n",
        encoding="utf-8",
    )
    base = Settings(_env_file=None, google_oauth_client_id="platform-client")  # type: ignore[call-arg]
    overlay = effective_settings(base, paths)
    assert overlay.settings.google_oauth_client_id == "own-client"
    assert overlay.settings.google_oauth_client_secret == "own-secret"


def test_secret_fields_include_google_client():
    assert SECRET_FIELDS["google_oauth_client_id"] == "GOOGLE_OAUTH_CLIENT_ID"
    assert SECRET_FIELDS["google_oauth_client_secret"] == "GOOGLE_OAUTH_CLIENT_SECRET"
