from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key


def test_abbreviated_titles_collapse_to_same_key():
    assert compute_dedup_key("Acme", "Sr SWE") == compute_dedup_key("Acme", "Software Engineer")
    assert compute_dedup_key("Acme", "Backend Eng") == compute_dedup_key("Acme", "Backend Engineer")


def test_distinct_roles_stay_distinct():
    assert compute_dedup_key("Acme", "Data Scientist") != compute_dedup_key("Acme", "Software Engineer")


def test_fingerprint_ignores_whitespace_and_case():
    a = compute_content_fingerprint("Build  great\nSystems")
    b = compute_content_fingerprint("build great systems")
    assert a is not None and a == b


def test_fingerprint_differs_for_different_text():
    assert compute_content_fingerprint("alpha role") != compute_content_fingerprint("beta role")


def test_fingerprint_none_for_blank():
    assert compute_content_fingerprint("   ") is None
    assert compute_content_fingerprint(None) is None
