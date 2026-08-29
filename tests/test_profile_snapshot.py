import json

from resume_agent.profile.snapshot import profile_snapshot, snapshot_diff


def _write_profile(
    profile_dir, *, metric_text: str, evidence: int, extra_project=False
):
    profile_dir.mkdir(parents=True, exist_ok=True)
    facts = {
        "contact": {"name": "A"},
        "experience": [
            {
                "id": "e1",
                "company": "Acme",
                "title": "Eng",
                "bullets": [
                    {"id": "b1", "text": metric_text},
                    {"id": "b2", "text": "Led platform."},
                ],
            }
        ],
        "education": [{"id": "edu1", "institution": "State"}],
        "projects": ([{"id": "p1", "name": "Tool"}] if extra_project else []),
    }
    (profile_dir / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    matrix = {
        "rows": [
            {
                "key": "python",
                "display": "Python",
                "evidence_fact_ids": [f"f{i}" for i in range(evidence)],
            }
        ]
    }
    (profile_dir / "matrix.json").write_text(json.dumps(matrix), encoding="utf-8")


def test_snapshot_collects_nested_and_non_experience_fact_ids(tmp_path):
    _write_profile(tmp_path, metric_text="Cut costs 30%.", evidence=2)
    snapshot = profile_snapshot(tmp_path)
    assert snapshot["factIds"] == ["b1", "b2", "e1", "edu1"]
    assert snapshot["bullets"]["e1"] == {"total": 2, "withMetrics": 1}


def test_diff_is_deterministic_and_reports_gains(tmp_path):
    before_dir, after_dir = tmp_path / "before", tmp_path / "after"
    _write_profile(before_dir, metric_text="Led migrations.", evidence=1)
    _write_profile(
        after_dir, metric_text="Cut deploy time 40%.", evidence=3, extra_project=True
    )
    diff = snapshot_diff(profile_snapshot(before_dir), profile_snapshot(after_dir))
    assert diff["newFactIds"] == ["p1"]
    assert diff["bulletsGainedMetrics"] == [
        {"experienceId": "e1", "before": 0, "after": 1}
    ]
    assert diff["skillsGainedEvidence"] == [
        {"skill": "python", "before": 1, "after": 3}
    ]
