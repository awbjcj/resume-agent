from resume_agent.tracking.dedup import compute_dedup_key


def test_dedup_key_ignores_case_punctuation_and_seniority():
    a = compute_dedup_key("Acme, Inc.", "Senior Backend Engineer")
    b = compute_dedup_key("acme inc", "Backend Engineer")
    assert a == b == "acme inc|backend engineer"


def test_dedup_key_strips_various_seniority_prefixes():
    base = compute_dedup_key("Acme", "Engineer")
    assert compute_dedup_key("Acme", "Sr. Engineer") == base
    assert compute_dedup_key("Acme", "Staff Engineer") == base
    assert compute_dedup_key("Acme", "Senior Staff Engineer") == base
    assert compute_dedup_key("Acme", "Junior Engineer") == base


def test_dedup_key_none_when_a_side_is_missing():
    assert compute_dedup_key(None, "Engineer") is None
    assert compute_dedup_key("Acme", None) is None
    assert compute_dedup_key("Acme", "   ") is None
