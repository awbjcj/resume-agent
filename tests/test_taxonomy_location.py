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


def test_normalize_country_covers_the_whole_iso_3166_standard():
    """The table was a ~45-country hand list, so most of the world was unresolvable.

    An unresolved country makes `build_location` drop the region too, which is
    how "Colombo, Western Province, Sri Lanka" reached the board as "Colombo".
    """
    assert location.normalize_country("Sri Lanka") == "LK"
    assert location.normalize_country("lk") == "LK"
    assert location.normalize_country("Kenya") == "KE"
    assert location.normalize_country("Egypt") == "EG"
    assert location.normalize_country("Peru") == "PE"
    # Accented official names also resolve as an ASCII-folded variant.
    assert location.normalize_country("Turkiye") == "TR"
    assert location.normalize_country("Türkiye") == "TR"
    assert location.normalize_country("Curacao") == "CW"
    # Colloquial names the standard does not carry.
    assert location.normalize_country("Turkey") == "TR"
    assert location.normalize_country("Russia") == "RU"
    assert location.normalize_country("Netherlands") == "NL"


def test_full_country_table_does_not_capture_us_state_codes():
    """17 ISO alpha-2 codes double as USPS codes; "Georgia" is both, too.

    With only two parts there is no country slot to disambiguate, so the
    US-state reading wins -- otherwise completing the country table would have
    turned every "Atlanta, GA" into Gabon.
    """
    for raw, region in (
        ("Atlanta, GA", "GA"),      # GA is also Gabon
        ("Atlanta, Georgia", "GA"),  # Georgia is also a country
        ("Boston, MA", "MA"),       # MA is also Morocco
        ("New Orleans, LA", "LA"),  # LA is also Laos
        ("Philadelphia, PA", "PA"),  # PA is also Panama
        ("Richmond, VA", "VA"),     # VA is also the Holy See
        ("Birmingham, Ala", "AL"),  # ALA is also the Aland Islands
    ):
        parsed = location._parse_location(raw)
        assert (parsed.region, parsed.country) == (region, "US"), raw


def test_two_part_us_state_no_longer_reads_as_a_foreign_country():
    """Regression: "San Francisco, CA" resolved to Canada, losing the state."""
    parsed = location._parse_location("San Francisco, CA")

    assert (parsed.city, parsed.region, parsed.country) == ("San Francisco", "CA", "US")


def test_three_parts_still_put_the_trailing_token_in_the_country_slot():
    parsed = location._parse_location("Toronto, ON, CA")

    assert (parsed.city, parsed.region, parsed.country) == ("Toronto", "ON", "CA")


def test_build_location_keeps_region_for_a_country_outside_the_legacy_table():
    """The reported bug, at the seam the fit agent actually feeds."""
    loc = location.build_location("Colombo", "Western Province", "Sri Lanka")

    assert (loc.city, loc.region, loc.country, loc.is_us) == (
        "Colombo", "Western Province", "LK", False
    )


def test_parse_location_recovers_a_two_part_foreign_country():
    """"Colombo, Sri Lanka" used to yield city-only: the country was unresolved,
    so the trailing part stayed in the region slot and was then discarded."""
    parsed = location._parse_location("Colombo, Sri Lanka")

    assert (parsed.city, parsed.region, parsed.country) == ("Colombo", None, "LK")


def test_parse_location_matches_a_comma_bearing_country_suffix():
    parsed = location._parse_location(
        "Kralendijk, Bonaire, Sint Eustatius and Saba"
    )

    assert (parsed.city, parsed.region, parsed.country) == (
        "Kralendijk",
        None,
        "BQ",
    )


def test_parse_location_matches_a_comma_bearing_country_without_a_city():
    parsed = location._parse_location("Korea, Republic of")

    assert (parsed.city, parsed.region, parsed.country) == (None, None, "KR")


def test_workplace_type_suffix_does_not_swallow_the_locality():
    """Boards glue the workplace type onto the label ("Ann Arbor, MI - Hybrid").

    The suffix left the trailing part unresolvable as a state or a country, and
    an unresolved country drops the region too, so the whole value collapsed to
    a bare city.
    """
    for raw, expected in (
        ("Ann Arbor, MI - Hybrid", ("Ann Arbor", "MI", "US")),
        ("Seattle, WA (Hybrid)", ("Seattle", "WA", "US")),
        ("New York, NY - Onsite", ("New York", "NY", "US")),
        ("New York, NY - On-site", ("New York", "NY", "US")),
        ("Ann Arbor, MI - In-Office", ("Ann Arbor", "MI", "US")),
        ("London, UK - Hybrid", ("London", None, "GB")),
        ("Singapore (Hybrid)", ("Singapore", None, "SG")),
        # A trailing "Remote" is a workplace tag like any other when a real
        # locality precedes it; this used to yield an empty location.
        ("Austin, TX - Remote", ("Austin", "TX", "US")),
    ):
        parsed = location._parse_location(raw)
        assert (parsed.city, parsed.region, parsed.country) == expected, raw
        assert parsed.raw == raw, "the provider's original string is preserved"


def test_a_purely_remote_location_is_still_country_only():
    """Regression guard: stripping workplace tags must not eat these shapes."""
    for raw, country in (("Remote", None), ("Remote - US", "US"), ("Remote, US", "US")):
        parsed = location._parse_location(raw)
        assert (parsed.city, parsed.region, parsed.country) == (None, None, country), raw


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


def test_infers_country_from_city_state_city():
    loc = location.build_location("Singapore", None, None, raw="Singapore")
    assert loc.city == "Singapore"
    assert loc.region is None
    assert loc.country == "SG"
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


def test_format_free_location_canonicalizes_comma_separated():
    assert location.format_free_location("Austin, tex.") == "Austin, TX"
    assert location.format_free_location(" Seattle , wa ") == "Seattle, WA"


def test_format_free_location_canonicalizes_space_separated():
    # The settings form's own placeholder text uses this shape ("Austin TX").
    assert location.format_free_location("Austin TX") == "Austin, TX"
    assert location.format_free_location("New York NY") == "New York, NY"


def test_format_free_location_expands_metro_alias():
    assert location.format_free_location("nyc") == "New York, NY"


def test_format_free_location_passes_through_unparseable():
    assert location.format_free_location("Remote") == "Remote"
    assert location.format_free_location("Somewhere, Nowhere") == "Somewhere, Nowhere"


def test_format_free_location_collapses_whitespace_and_empties():
    assert location.format_free_location("  Boston   ") == "Boston"
    assert location.format_free_location("   ") == ""


def test_build_locations_preserves_order_dedupes_and_structures_each_instance():
    locations = location.build_locations(
        "Austin, TX, US | Toronto, Ontario, Canada | Austin, TX, US"
    )

    assert [item.raw for item in locations] == [
        "Austin, TX, US",
        "Toronto, Ontario, Canada",
    ]
    assert locations[0].as_dict() == {
        "city": "Austin",
        "region": "TX",
        "country": "US",
        "is_us": True,
        "raw": "Austin, TX, US",
    }
    assert locations[1].city == "Toronto"
    assert locations[1].region == "Ontario"
    assert locations[1].country == "CA"


def test_build_locations_uses_primary_hint_without_losing_other_locations():
    locations = location.build_locations(
        "Toronto, ON | Remote - US",
        primary=location.StructuredLocation(
            city="Toronto", region="Ontario", country="CA", is_us=False
        ),
    )

    assert [(item.city, item.region, item.country, item.raw) for item in locations] == [
        ("Toronto", "Ontario", "CA", "Toronto, ON"),
        (None, None, "US", "Remote - US"),
    ]


def test_build_locations_treats_bare_singapore_as_city_and_country():
    [loc] = location.build_locations("Singapore")

    assert loc.city == "Singapore"
    assert loc.region is None
    assert loc.country == "SG"


def test_build_locations_treats_bare_non_city_state_as_country_only():
    [loc] = location.build_locations("Germany")

    assert loc.city is None
    assert loc.region is None
    assert loc.country == "DE"


def test_location_instances_from_criteria_falls_back_to_legacy_shape():
    legacy = {
        "location_parts": {
            "city": "Boston",
            "region": "MA",
            "country": "US",
            "is_us": True,
            "raw": "Boston, MA",
        }
    }

    assert location.location_instances_from_criteria(legacy)[0].city == "Boston"


def test_location_instances_normalize_legacy_city_state_without_country():
    legacy = {
        "location_parts": {
            "city": "Singapore",
            "region": None,
            "country": None,
            "is_us": False,
            "raw": "Singapore",
        }
    }

    [loc] = location.location_instances_from_criteria(legacy)
    assert (loc.city, loc.region, loc.country) == ("Singapore", None, "SG")
