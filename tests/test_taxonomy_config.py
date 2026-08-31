from resume_tailor_harness.config import Settings


def test_taxonomy_soft_target_accepts_the_legacy_cap_environment_alias(monkeypatch):
    monkeypatch.delenv("DOMAINS_PER_CATEGORY_TARGET", raising=False)
    monkeypatch.setenv("DOMAINS_PER_CATEGORY_CAP", "17")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.domains_per_category_target == 17
    assert settings.domains_per_category_cap == 17
    assert settings.skill_embedding_model == "openai:text-embedding-3-small"
