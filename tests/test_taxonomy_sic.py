from resume_agent.taxonomy import sic


def test_load_table_has_divisions_and_major_groups():
    table = sic.load_sic_table()
    assert table["divisions"]["H"] == "Finance, Insurance & Real Estate"
    assert table["major_groups"]["73"]["label"] == "Business Services"
    assert table["major_groups"]["73"]["division"] == "I"


def test_major_group_label():
    table = sic.load_sic_table()
    assert sic.major_group_label("60", table) == "Depository Institutions"
    assert sic.major_group_label("zz", table) is None


def test_division_for_returns_code_and_label():
    table = sic.load_sic_table()
    assert sic.division_for("80", table) == ("I", "Services")
    assert sic.division_for("zz", table) is None


def test_coerce_code_keeps_valid_drops_invalid():
    table = sic.load_sic_table()
    assert sic.coerce_code("73", table) == "73"
    assert sic.coerce_code("9999", table) is None
    assert sic.coerce_code(None, table) is None
    assert sic.coerce_code("  60 ", table) == "60"


def test_display_label_falls_back_to_unclassified():
    table = sic.load_sic_table()
    assert sic.display_label("73", table) == "Business Services"
    assert sic.display_label(None, table) == sic.UNCLASSIFIED
