from resume_agent.taxonomy import location


def test_normalize_country_variants_to_iso2():
    assert location.normalize_country("United States") == "US"
    assert location.normalize_country("USA") == "US"
    assert location.normalize_country("us") == "US"
    assert location.normalize_country("United Kingdom") == "GB"
    assert location.normalize_country("UK") == "GB"
    assert location.normalize_country("Taiwan") == "TW"
    assert location.normalize_country("South Korea") == "KR"
    assert location.normalize_country("Republic of Korea") == "KR"
    assert location.normalize_country("UAE") == "AE"
    assert location.normalize_country("United Arab Emirates") == "AE"
    assert location.normalize_country("Czechia") == "CZ"
    assert location.normalize_country("Czech Republic") == "CZ"
    assert location.normalize_country("Atlantis") is None
    assert location.normalize_country(None) is None


def test_normalize_region_us_and_pass_through():
    assert location.normalize_region("California", "US") == "CA"
    assert location.normalize_region("CA", "US") == "CA"
    assert location.normalize_region(None, "US") is None
    assert location.normalize_region("Ontario", "CA") == "Ontario"  # non-US -> pass-through
    assert location.normalize_region("New Taipei City", "TW") == "New Taipei City"
    assert location.normalize_region("Some Province", None) is None  # country unresolved


def test_clean_region_collapses_whitespace_and_strips_zip():
    assert location._clean_region("  New   Taipei  City ") == "New Taipei City"
    assert location._clean_region("Ontario 12345") == "Ontario"
    assert location._clean_region("   ") is None
    assert location._clean_region(None) is None


def test_build_location_us():
    loc = location.build_location("Mountain View", "CA", "USA", raw="Mountain View, CA, USA")
    assert loc.city == "Mountain View"
    assert loc.region == "CA"
    assert loc.country == "US"
    assert loc.is_us is True
    assert loc.raw == "Mountain View, CA, USA"


def test_build_location_foreign_region_pass_through():
    loc = location.build_location("London", "Greater London", "United Kingdom")
    assert loc.country == "GB"
    assert loc.region == "Greater London"
    assert loc.is_us is False


def test_build_location_taiwan_end_to_end():
    loc = location.build_location(
        "Banqiao District", "New Taipei City", "Taiwan",
        raw="New Taipei, Banqiao District, New Taipei City, Taiwan",
    )
    assert loc.city == "Banqiao District"
    assert loc.region == "New Taipei City"
    assert loc.country == "TW"
    assert loc.is_us is False
    assert loc.raw == "New Taipei, Banqiao District, New Taipei City, Taiwan"


def test_build_location_bare_region_without_country_stays_unresolved():
    loc = location.build_location("Somewhere", "Some Province", None)
    assert loc.country is None
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


def test_infers_us_from_state_when_country_absent():
    # The dominant US posting shape: "San Francisco, CA" with no country written.
    loc = location.build_location("San Francisco", "CA", None)
    assert loc.country == "US"
    assert loc.region == "CA"
    assert loc.is_us is True


def test_does_not_infer_us_from_bare_city():
    loc = location.build_location("Boston", None, None)
    assert loc.country is None
    assert loc.region is None
    assert loc.is_us is False


def test_region_state_abbreviation_variants():
    assert location.normalize_region("Calif.", "US") == "CA"
    assert location.normalize_region("Mass.", "US") == "MA"
    assert location.normalize_region("Tex.", "US") == "TX"
    assert location.normalize_region("Wash.", "US") == "WA"
    assert location.normalize_region("Fla.", "US") == "FL"
    # Two-letter forms that double as USPS codes still resolve after a period.
    assert location.normalize_region("Ga.", "US") == "GA"


def test_splits_city_state_leaked_into_city_field():
    loc = location.build_location("San Francisco, CA", None, None)
    assert loc.city == "San Francisco"
    assert loc.region == "CA"
    assert loc.country == "US"


def test_strips_trailing_zip_from_region():
    loc = location.build_location("Austin", "TX 78701", None)
    assert loc.region == "TX"
    assert loc.country == "US"


def test_infers_us_from_curated_metro_nyc():
    loc = location.build_location("NYC", None, None)
    assert loc.city == "New York"
    assert loc.region == "NY"
    assert loc.country == "US"
    assert loc.is_us is True


def test_infers_us_from_bay_area_metro():
    loc = location.build_location("Bay Area", None, None)
    assert loc.region == "CA"
    assert loc.country == "US"
    assert loc.is_us is True


def test_la_is_louisiana_never_los_angeles():
    # "LA" is the USPS code for Louisiana; it must never expand to Los Angeles/CA.
    loc = location.build_location("New Orleans", "LA", None)
    assert loc.region == "LA"
    assert loc.country == "US"
    # "LA" as a bare city is not a state and is not a curated metro: no inference.
    bare = location.build_location("LA", None, None)
    assert bare.region is None
    assert bare.country is None


def test_foreign_country_region_not_reinterpreted_as_us_state():
    # A resolved non-US country must not trigger US inference from a stray token,
    # and the region is passed through verbatim rather than expanded via the US table.
    loc = location.build_location("Ontario", "CA", "Canada")
    assert loc.country == "CA"
    assert loc.region == "CA"
    assert loc.is_us is False
