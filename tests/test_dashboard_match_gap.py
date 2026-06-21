from resume_agent.dashboard.app import render_match_gap_page
from resume_agent.dashboard.pages import match_gap_table_rows
from resume_agent.tracking.match_gap import GapRow, MatchGapReport


def test_render_match_gap_page_is_importable_and_callable():
    assert callable(render_match_gap_page)


def test_match_gap_table_rows_formats_counts_and_share():
    report = MatchGapReport(
        target_total=3,
        gaps=[
            GapRow(skill="Kubernetes", demand_count=2, target_total=3),
            GapRow(skill="Go", demand_count=1, target_total=3),
        ],
        per_job={},
    )

    assert match_gap_table_rows(report) == [
        {"Skill": "Kubernetes", "Demanded by": "2/3", "Share %": 67},
        {"Skill": "Go", "Demanded by": "1/3", "Share %": 33},
    ]
