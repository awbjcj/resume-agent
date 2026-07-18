import json

from resume_agent.profile.group_corrections import (
    GroupCorrection,
    GroupCorrections,
    corrections_path,
    load_group_corrections,
    save_group_corrections,
)


def test_corrections_path_is_profile_scoped(tmp_path):
    assert corrections_path(tmp_path) == tmp_path / "group_corrections.json"


def test_missing_file_loads_empty(tmp_path):
    assert load_group_corrections(tmp_path / "group_corrections.json").corrections == {}


def test_corrupt_file_loads_empty(tmp_path):
    path = tmp_path / "group_corrections.json"
    path.write_text("{not json", encoding="utf-8")

    assert load_group_corrections(path).corrections == {}


def test_round_trip_normalizes_tokens_and_drops_invalid_entries(tmp_path):
    path = corrections_path(tmp_path)
    ledger = GroupCorrections(
        corrections={
            "  DBT  ": GroupCorrection(
                group="ai-ml", corrected_at="2026-07-16T00:00:00+00:00"
            ),
            "mystery": GroupCorrection(group="not-a-real-group"),
            "   ": GroupCorrection(group="other"),
        }
    )

    save_group_corrections(ledger, path)
    loaded = load_group_corrections(path)

    assert loaded.as_map() == {"dbt": "ai-ml"}
    assert loaded.corrections["dbt"].corrected_at == "2026-07-16T00:00:00+00:00"


def test_save_writes_valid_json_without_abandoned_temp_files(tmp_path):
    path = corrections_path(tmp_path)
    ledger = GroupCorrections(
        corrections={"python": GroupCorrection(group="languages")}
    )

    save_group_corrections(ledger, path)

    assert json.loads(path.read_text(encoding="utf-8"))["corrections"]["python"][
        "group"
    ] == "languages"
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_load_remaps_legacy_slugs_and_drops_dead_ones(tmp_path):
    path = tmp_path / "group_corrections.json"
    path.write_text(
        json.dumps(
            {
                "corrections": {
                    "python": {"group": "languages", "corrected_at": "2026-01-01"},
                    "owasp": {"group": "security", "corrected_at": "2026-01-01"},
                    "react": {"group": "frameworks", "corrected_at": "2026-01-01"},
                }
            }
        ),
        encoding="utf-8",
    )

    ledger = load_group_corrections(path)

    assert ledger.corrections["python"].group == "languages"
    assert ledger.corrections["owasp"].group == "security-compliance"
    assert "react" not in ledger.corrections
