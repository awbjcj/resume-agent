from resume_agent.taxonomy import location


def test_normalize_country_variants_to_iso2():
    assert location.normalize_country("United States") == "US"
    assert location.normalize_country("USA") == "US"
    assert location.normalize_country("us") == "US"
    assert location.normalize_country("United Kingdom") == "GB"
    assert location.normalize_country("UK") == "GB"
    assert location.normalize_country("Atlantis") is None
    assert location.normalize_country(None) is None


def test_normalize_region_us_only():
    assert location.normalize_region("California", "US") == "CA"
    assert location.normalize_region("CA", "US") == "CA"
    assert location.normalize_region("Ontario", "CA") is None  # non-US -> None
    assert location.normalize_region(None, "US") is None


def test_build_location_us():
    loc = location.build_location("Mountain View", "CA", "USA", raw="Mountain View, CA, USA")
    assert loc.city == "Mountain View"
    assert loc.region == "CA"
    assert loc.country == "US"
    assert loc.is_us is True
    assert loc.raw == "Mountain View, CA, USA"


def test_build_location_foreign_has_no_region():
    loc = location.build_location("London", "Greater London", "United Kingdom")
    assert loc.country == "GB"
    assert loc.region is None
    assert loc.is_us is False


def test_build_location_unparseable_country():
    loc = location.build_location(None, None, None, raw="2 Locations")
    assert loc.city is None
    assert loc.region is None
    assert loc.country is None
    assert loc.is_us is False
    assert loc.raw == "2 Locations"


def test_as_dict_roundtrips():
    loc = location.build_location("Austin", "Texas", "US")
    assert loc.as_dict() == {
        "city": "Austin", "region": "TX", "country": "US", "is_us": True, "raw": None
    }
