"""Every shipped config key must survive a settings-page save.

`YamlConfigStore.put` used to serialize its DTO *over the whole file*, so a key
the DTO did not declare was deleted the first time anything on that page was
saved. Three real settings were being destroyed that way: the review roster's
`early_stop_on_regression`, the renderer's `template_path`/`output_dir`, and
the wizard-written `resume_path`.

Only the first of those belongs on the wire. Rendering is template-id based by
design (`render/CLAUDE.md`) and `resume_path` is wizard/CLI state, so the fix
is not "declare every key" — it is that `put` merges over the file's existing
keys and leaves alone what it does not own.

These tests run against the shipped `.example` files rather than asserting
`DTO fields == domain fields`, because the two legitimately diverge
(`SearchConfigDoc` has no domain twin; `ReviewConfigDoc` will never carry the
deprecated `match_plan_enabled` alias). What matters is the failure mode —
silent data loss — so that is what is asserted.
"""

from pathlib import Path

import pytest
import yaml

from resume_tailor_harness.api.schemas.config import DOMAIN_SCHEMAS, ReviewConfigDoc
from resume_tailor_harness.services.config_store import _FILES, YamlConfigStore
from resume_tailor_harness.tailor.review_config import ReviewConfig

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"

# domain -> the shipped example whose keys must survive a round-trip. Every
# YAML-backed domain in `_FILES` is covered; `style_guide` is plain markdown
# and has no key set to lose.
EXAMPLES = {
    domain: filename + ".example"
    for domain, filename in _FILES.items()
    if domain != "style_guide"
}


def _losses(original: object, saved: object, path: str = "") -> list[str]:
    """Report everything `original` stated that `saved` no longer states.

    A *subset* check, not equality: `put` serializes the full model, so a key
    the file omitted comes back written out at its default (the example rosters
    omit `score_bands` on the `fact-check` row, which returns as an explicit
    `false`). Materializing a default is not data loss. Dropping a key, or
    coming back with a different value, is — and that is all this reports.
    """
    if isinstance(original, dict):
        if not isinstance(saved, dict):
            return [f"{path or '<root>'}: mapping replaced by {type(saved).__name__}"]
        found: list[str] = []
        for key, value in original.items():
            where = f"{path}.{key}" if path else str(key)
            if key not in saved:
                found.append(f"{where}: deleted")
            else:
                found.extend(_losses(value, saved[key], where))
        return found
    if isinstance(original, list):
        if not isinstance(saved, list) or len(saved) != len(original):
            return [f"{path or '<root>'}: sequence changed shape"]
        return [
            loss
            for index, item in enumerate(original)
            for loss in _losses(item, saved[index], f"{path}[{index}]")
        ]
    if original != saved:
        return [f"{path or '<root>'}: {original!r} -> {saved!r}"]
    return []


@pytest.mark.parametrize("domain", sorted(EXAMPLES))
def test_example_settings_survive_get_then_put(domain, tmp_path):
    source = REPO_CONFIG / EXAMPLES[domain]
    if not source.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"no shipped example for {domain}")
    original = yaml.safe_load(source.read_text(encoding="utf-8")) or {}

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / _FILES[domain]
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    store = YamlConfigStore(config_dir)
    store.put(domain, store.get(domain))
    saved = yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    losses = _losses(original, saved)
    assert not losses, f"{EXAMPLES[domain]} lost settings on save: {losses}"


def test_the_subset_check_actually_catches_a_dropped_key():
    """Guard the guard: a subset check that never fails proves nothing."""
    assert _losses({"a": 1, "b": 2}, {"a": 1}) == ["b: deleted"]
    assert _losses({"a": 1}, {"a": 2}) == ["a: 1 -> 2"]
    assert _losses({"r": [{"x": 1}]}, {"r": [{"x": 1, "y": 0}]}) == []
    assert _losses({"r": [{"x": 1}]}, {"r": [{"y": 0}]}) == ["r[0].x: deleted"]


def test_saved_review_roster_still_loads_as_a_domain_config(tmp_path):
    """The written file must satisfy `ReviewConfig`, not just round-trip."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / "review.yaml"
    target.write_text(
        (REPO_CONFIG / "review.yaml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    store = YamlConfigStore(config_dir)
    store.put("review", store.get("review"))

    loaded = ReviewConfig.model_validate(
        yaml.safe_load(target.read_text(encoding="utf-8"))
    )
    assert loaded.early_stop_on_regression is True
    assert loaded.length_budget.target_skills == 40
    assert loaded.length_budget.max_skills_per_category == 12


def test_null_length_budget_is_healed_rather_than_served():
    """A workspace broken by the removed on/off switch repairs itself.

    The old "Enforce a length budget" switch wrote `length_budget: null`, which
    `ReviewConfig` rejects outright — so such a file broke every tailor run at
    config load. Those files exist on disk, and reading one must not 500.
    """
    doc = ReviewConfigDoc.model_validate({"lengthBudget": None})
    assert doc.length_budget.target_skills == 40
    # And the healed document is loadable by the domain model it feeds.
    assert ReviewConfig.model_validate(doc.model_dump()).length_budget.page_target == 2


def test_put_preserves_keys_the_dto_does_not_own(tmp_path):
    """Render keeps its CLI-only fields through a settings-page save.

    These are deliberately absent from `RenderConfigDoc` — the web contract is
    template-id based — so preservation, not exposure, is what protects them.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "render.yaml").write_text(
        "template: classic\n"
        "fit_one_page: true\n"
        "template_path: templates/resume.typ\n"
        "output_dir: /srv/custom-output\n",
        encoding="utf-8",
    )

    store = YamlConfigStore(config_dir)
    doc = store.get("render")
    store.put("render", doc.model_copy(update={"fit_one_page": False}))

    saved = yaml.safe_load((config_dir / "render.yaml").read_text(encoding="utf-8"))
    assert saved["template_path"] == "templates/resume.typ"
    assert saved["output_dir"] == "/srv/custom-output"
    assert saved["fit_one_page"] is False


def test_put_drops_a_superseded_key_rather_than_preserving_a_contradiction(tmp_path):
    """`match_plan_enabled` must not survive a toggle of its replacement.

    `ReviewConfig` rejects a file where the deprecated flag disagrees with
    `evidence_portfolio_enabled`, so blindly preserving it would turn a UI
    toggle into a config the next tailor run cannot load.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / "review.yaml"
    target.write_text(
        "max_rounds: 2\nmatch_plan_enabled: false\n",
        encoding="utf-8",
    )

    store = YamlConfigStore(config_dir)
    doc = store.get("review")
    store.put("review", doc.model_copy(update={"evidence_portfolio_enabled": True}))

    saved = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "match_plan_enabled" not in saved
    # The decisive assertion: the written file still loads.
    assert ReviewConfig.model_validate(saved).portfolio_enabled is True


def test_put_still_removes_an_item_the_user_deleted(tmp_path):
    """Merging must not resurrect list entries — DTO-owned keys replace."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / "search.yaml"
    target.write_text("keywords:\n- python\n- rust\n", encoding="utf-8")

    store = YamlConfigStore(config_dir)
    doc = store.get("search")
    store.put("search", doc.model_copy(update={"keywords": ["python"]}))

    saved = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert saved["keywords"] == ["python"]


def test_length_budget_is_not_nullable_on_the_wire():
    """`ReviewConfig.length_budget` is non-optional; the DTO must agree."""
    assert DOMAIN_SCHEMAS["review"].model_fields["length_budget"].is_required() is False
    annotation = DOMAIN_SCHEMAS["review"].model_fields["length_budget"].annotation
    assert annotation is not None
    assert "NoneType" not in str(annotation)
