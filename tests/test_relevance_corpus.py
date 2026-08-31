import json
from pathlib import Path

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.text import relevance_gate
from resume_tailor_harness.discovery.search_config import SearchConfig

_FIXTURE = Path(__file__).parent / "fixtures" / "relevance" / "labeled.json"
_ANCHORS = ["engineer", "ai", "ml", "machine learning", "applied scientist", "llm"]
_EXCLUDES = ["driver", "cdl", "nurse", "sales", "recruiter", "creative"]


def test_tier1_gate_matches_labels():
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    cfg = SearchConfig(role_anchors=_ANCHORS, exclude_terms=_EXCLUDES)
    misses = []
    for case in cases:
        job = RawJob(
            source="fixture",
            url=None,
            company=None,
            title=case["title"],
            location=None,
            jd_text=case["jd_text"],
        )
        kept = bool(relevance_gate([job], cfg))
        if kept != case["tier1_keep"]:
            misses.append((case["title"], kept, case["tier1_keep"]))
    assert not misses, f"gate disagreed with labels: {misses}"
