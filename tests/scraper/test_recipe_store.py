from datetime import datetime, timezone

import pytest

from resume_agent.discovery.scraper.recipe import Pagination, ScrapeRecipe
from resume_agent.discovery.scraper.recipe_store import (
    host_key,
    load_recipe,
    recipe_path,
    save_recipe,
)


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


def test_save_is_atomic_and_removes_temporary_file(tmp_path):
    save_recipe("acme.com", _recipe(), base_dir=tmp_path)
    assert not recipe_path("acme.com", base_dir=tmp_path).with_suffix(".json.tmp").exists()


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
