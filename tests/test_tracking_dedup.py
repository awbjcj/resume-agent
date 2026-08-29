from resume_agent.tracking.dedup import (
    compute_content_fingerprint,
    compute_dedup_key,
    locations_compatible,
)


def test_abbreviated_titles_collapse_to_same_key():
    assert compute_dedup_key("Acme", "Sr SWE") == compute_dedup_key(
        "Acme", "Software Engineer"
    )
    assert compute_dedup_key("Acme", "Backend Eng") == compute_dedup_key(
        "Acme", "Backend Engineer"
    )


def test_distinct_roles_stay_distinct():
    assert compute_dedup_key("Acme", "Data Scientist") != compute_dedup_key(
        "Acme", "Software Engineer"
    )


def test_fingerprint_ignores_whitespace_and_case():
    a = compute_content_fingerprint("Build  great\nSystems")
    b = compute_content_fingerprint("build great systems")
    assert a is not None and a == b


def test_fingerprint_differs_for_different_text():
    assert compute_content_fingerprint("alpha role") != compute_content_fingerprint(
        "beta role"
    )


def test_fingerprint_none_for_blank():
    assert compute_content_fingerprint("   ") is None
    assert compute_content_fingerprint(None) is None


def test_locations_blank_either_side_is_wildcard():
    assert locations_compatible(None, None)
    assert locations_compatible(None, "Austin, TX")
    assert locations_compatible("Austin, TX", "")
    assert locations_compatible("   ", "Detroit, MI")


def test_locations_same_city_different_spelling_compatible():
    assert locations_compatible("Austin, TX", "Austin, Texas, United States")
    assert locations_compatible("New York", "New York City")
    assert locations_compatible("Austin", "Austin, TX")


def test_locations_different_city_incompatible():
    assert not locations_compatible("Austin, TX", "Detroit, MI")
    assert not locations_compatible("New York City", "Boston, MA")


def test_remote_is_its_own_city():
    assert not locations_compatible("Remote", "Austin, TX")
    assert locations_compatible("Remote", "Remote - US")
