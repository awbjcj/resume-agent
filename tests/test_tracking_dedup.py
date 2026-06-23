from resume_agent.tracking.dedup import compute_dedup_key


def test_abbreviated_titles_collapse_to_same_key():
    assert compute_dedup_key("Acme", "Sr SWE") == compute_dedup_key("Acme", "Software Engineer")
    assert compute_dedup_key("Acme", "Backend Eng") == compute_dedup_key("Acme", "Backend Engineer")


def test_distinct_roles_stay_distinct():
    assert compute_dedup_key("Acme", "Data Scientist") != compute_dedup_key("Acme", "Software Engineer")
