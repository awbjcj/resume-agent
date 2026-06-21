from resume_agent.taxonomy import company_size


def test_snap_canonical_passthrough():
    assert company_size.snap("startup") == "startup"
    assert company_size.snap("Enterprise") == "enterprise"


def test_snap_variants():
    assert company_size.snap("Series A") == "startup"
    assert company_size.snap("seed stage") == "startup"
    assert company_size.snap("Series C, growth stage") == "scaleup"
    assert company_size.snap("Fortune 500") == "enterprise"
    assert company_size.snap("publicly traded") == "enterprise"


def test_snap_employee_counts():
    assert company_size.snap("1-50 employees") == "startup"
    assert company_size.snap("250 employees") == "scaleup"
    assert company_size.snap("10,000+ employees") == "enterprise"


def test_snap_unmappable_is_none():
    assert company_size.snap("we are a vibe") is None
    assert company_size.snap(None) is None
    assert company_size.snap("") is None
