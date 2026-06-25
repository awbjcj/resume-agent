from resume_agent.dashboard import pages

FORBIDDEN = [
    "save_job",
    "archive_job",
    "restore_job",
    "delete_job",
    "save_application",
    "update_application_status",
]


def test_dashboard_holds_no_repository_mutations():
    leaked = [name for name in FORBIDDEN if hasattr(pages, name)]
    assert leaked == [], f"dashboard bypasses the board seam: {leaked}"
