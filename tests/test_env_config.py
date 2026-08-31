from __future__ import annotations

from resume_tailor_harness.services.env_config import write_env_updates


def test_write_env_updates_preserves_symlink_and_updates_target(tmp_path):
    target = tmp_path / "data" / ".env"
    target.parent.mkdir()
    target.write_text("EXISTING=value\n", encoding="utf-8")
    link = tmp_path / ".env"
    link.symlink_to(target)

    settings = write_env_updates({"SUB2API_BASE_URL": "https://gateway.example"}, link)

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == (
        "EXISTING=value\nSUB2API_BASE_URL=https://gateway.example\n"
    )
    assert settings.sub2api_base_url == "https://gateway.example"
