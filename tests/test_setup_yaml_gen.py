from resume_agent.setup.yaml_gen import parse_greenhouse_boards


def test_parses_token_and_company():
    boards = parse_greenhouse_boards("stripe, Stripe\nairbnb, Airbnb")
    assert boards == [
        {"token": "stripe", "company": "Stripe"},
        {"token": "airbnb", "company": "Airbnb"},
    ]


def test_token_only_defaults_company_to_titlecased_token():
    assert parse_greenhouse_boards("datadog") == [{"token": "datadog", "company": "Datadog"}]


def test_skips_blank_lines_and_trims():
    assert parse_greenhouse_boards("\n  stripe ,  Stripe \n\n") == [
        {"token": "stripe", "company": "Stripe"}
    ]


def test_empty_input_is_empty_list():
    assert parse_greenhouse_boards("") == []
