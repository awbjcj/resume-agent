from resume_agent.discovery.source_tier import source_rank


def test_direct_sources_outrank_aggregators():
    for direct in (
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "tesla",
        "google",
        "companies",
        "url",
    ):
        for aggregator in ("adzuna", "remoteok", "linkedin"):
            assert source_rank(direct) < source_rank(aggregator)


def test_equal_tier_sources_tie():
    assert source_rank("greenhouse") == source_rank("workday")
    assert source_rank("adzuna") == source_rank("remoteok")


def test_unknown_source_defaults_to_aggregator_tier():
    assert source_rank("mystery") == source_rank("adzuna")


def test_manual_source_is_direct_tier():
    assert source_rank("manual") < source_rank("adzuna")


def test_expanded_ats_sources_are_direct_tier():
    sources = (
        "smartrecruiters",
        "workable",
        "recruitee",
        "personio",
        "breezy",
        "jazzhr",
        "bamboohr",
    )

    assert all(source_rank(source) < source_rank("adzuna") for source in sources)


def test_scrape_source_is_canonical():
    assert source_rank("scrape") == 0
