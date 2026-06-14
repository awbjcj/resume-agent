import os

import pytest

from resume_agent.discovery.search_config import load_search_config
from resume_agent.setup.state import WizardState
from resume_agent.setup.writer import atomic_write_all


def _seed_examples(root):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "review.yaml.example").write_text(
        "max_rounds: 3\nscore_threshold: 85\nreviewers: []\n", encoding="utf-8"
    )
    (root / "config" / "render.yaml.example").write_text(
        "template_path: templates/resume.typ\noutput_dir: output\n", encoding="utf-8"
    )


def test_atomic_write_all_writes_every_file(tmp_path):
    _seed_examples(tmp_path)
    state = WizardState(anthropic_api_key="sk-test", keywords=["python"], remote_policy="remote")
    report = atomic_write_all(state, root=tmp_path)

    assert (tmp_path / ".env").exists()
    assert (tmp_path / "config" / "search.yaml").exists()
    cfg = load_search_config(tmp_path / "config" / "search.yaml")
    assert cfg.keywords == ["python"]
    assert all(status == "written" for status in report.values())
    # no temp litter
    assert not list(tmp_path.rglob("*.tmp"))


def test_partial_failure_leaves_no_tmp_litter(tmp_path, monkeypatch):
    _seed_examples(tmp_path)
    state = WizardState(anthropic_api_key="sk-test")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:                     # fail on the 2nd file
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr("resume_agent.setup.writer.os.replace", flaky_replace)
    report = atomic_write_all(state, root=tmp_path)

    assert any(status.startswith("error") for status in report.values())
    assert not list(tmp_path.rglob("*.tmp"))     # tmp cleaned up even on failure


from resume_agent.setup.writer import load_existing_state


def test_load_existing_state_round_trips_what_was_written(tmp_path):
    _seed_examples(tmp_path)
    written = WizardState(
        anthropic_api_key="sk-rt", keywords=["go"], remote_policy="hybrid",
        greenhouse_enabled=True, greenhouse_boards=[{"token": "stripe", "company": "Stripe"}],
    )
    atomic_write_all(written, root=tmp_path)
    reloaded = load_existing_state(root=tmp_path)
    assert reloaded.anthropic_api_key == "sk-rt"
    assert reloaded.keywords == ["go"]
    assert reloaded.remote_policy == "hybrid"
    assert reloaded.greenhouse_enabled is True
    assert reloaded.greenhouse_boards == [{"token": "stripe", "company": "Stripe"}]


def test_load_existing_state_restores_custom_models(tmp_path):
    # managed_env writes the model keys, so a re-run must read them back or it
    # would clobber a customized model with the WizardState default.
    _seed_examples(tmp_path)
    atomic_write_all(WizardState(premium_model="claude-custom-prem"), root=tmp_path)
    reloaded = load_existing_state(root=tmp_path)
    assert reloaded.premium_model == "claude-custom-prem"


def test_missing_example_degrades_to_error_status_not_crash(tmp_path):
    # No .example files seeded → render_from_example raises FileNotFoundError.
    # atomic_write_all must report it per-file, not crash, and still write the rest.
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    report = atomic_write_all(WizardState(anthropic_api_key="sk-test"), root=tmp_path)

    review = str(tmp_path / "config" / "review.yaml")
    assert report[review].startswith("error")          # missing example → error status
    assert report[str(tmp_path / "config" / "search.yaml")] == "written"  # others still written
    assert (tmp_path / "config" / "search.yaml").exists()
    assert not list(tmp_path.rglob("*.tmp"))            # no litter
