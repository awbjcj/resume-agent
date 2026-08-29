from datetime import datetime, timezone
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.discovery.scraper.recipe import Pagination, ScrapeRecipe
from resume_agent.discovery.scraper.recipe_store import (
    RECIPES_DIR,
    default_recipes_dir,
    host_key,
    load_recipe,
    recipe_path,
    save_recipe,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


def _recipe():
    return ScrapeRecipe(
        learned_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        card_container="li.job",
        jd_container="div.jd",
        title_sel="h3",
        location_sel=".loc",
        url_sel="a",
        detail_mode="link",
        pagination=Pagination(pattern="next", control_sel="a.next"),
    )


def test_host_key_normalizes_url_hostname():
    assert host_key("https://WWW.Acme.com:8443/careers?x=1") == "acme.com"


def test_host_key_rejects_input_without_hostname():
    with pytest.raises(ValueError, match="hostname"):
        host_key("not a URL")


def test_save_then_load_roundtrip(tmp_path):
    save_recipe("acme.com", _recipe(), base_dir=tmp_path)
    assert load_recipe("acme.com", base_dir=tmp_path) == _recipe()


def _context(root: Path) -> UserContext:
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(root),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def test_default_recipes_dir_falls_back_to_flat_path_without_context():
    assert default_recipes_dir() == Path(RECIPES_DIR)


def test_default_recipes_dir_resolves_per_tenant_workspace(tmp_path):
    root = tmp_path / "users" / "abc123def456"
    with use_context(_context(root)):
        assert default_recipes_dir() == root / "scraper_recipes"


def test_save_is_atomic_and_removes_temporary_file(tmp_path):
    save_recipe("acme.com", _recipe(), base_dir=tmp_path)
    assert (
        not recipe_path("acme.com", base_dir=tmp_path).with_suffix(".json.tmp").exists()
    )


def test_load_missing_returns_none(tmp_path):
    assert load_recipe("nope.com", base_dir=tmp_path) is None


def test_schema_version_mismatch_is_cache_miss(tmp_path):
    path = recipe_path("acme.com", base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _recipe().model_copy(update={"schema_version": 999}).model_dump_json(),
        encoding="utf-8",
    )
    assert load_recipe("acme.com", base_dir=tmp_path) is None


def test_corrupt_json_is_cache_miss(tmp_path):
    path = recipe_path("acme.com", base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert load_recipe("acme.com", base_dir=tmp_path) is None


def test_recipe_path_sanitizes_ipv6_hostname(tmp_path):
    path = recipe_path("2001:db8::1", base_dir=tmp_path)
    assert path.parent == tmp_path
    assert path.name == "2001_db8__1.json"
