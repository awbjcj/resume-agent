from resume_agent.setup.env_writer import format_env, merge_env, parse_env


def test_parse_env_ignores_comments_and_blanks():
    assert parse_env("# comment\n\nA=1\nB = two\n") == {"A": "1", "B": "two"}


def test_merge_preserves_unmanaged_keys():
    existing = {"OPENAI_API_KEY": "keep-me", "ANTHROPIC_API_KEY": "old"}
    merged = merge_env(existing, {"ANTHROPIC_API_KEY": "new"})
    assert merged["OPENAI_API_KEY"] == "keep-me"   # untouched
    assert merged["ANTHROPIC_API_KEY"] == "new"     # overwritten


def test_format_quotes_values_with_spaces():
    out = format_env({"A": "no_spaces", "B": "has spaces"})
    assert "A=no_spaces\n" in out
    assert 'B="has spaces"\n' in out


def test_round_trip_parse_format():
    data = {"A": "1", "B": "two words"}
    assert parse_env(format_env(data)) == {"A": "1", "B": "two words"}
