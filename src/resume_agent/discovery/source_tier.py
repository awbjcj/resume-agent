"""Fixed source priority: a job's canonical (direct/ATS) copy beats an aggregator copy.

Lower rank == higher priority. Calibration is a tier label, not a per-source number.
"""

_CANONICAL = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "tesla",
    "google",
    "companies",
    "url",
    "manual",
    "smartrecruiters",
    "workable",
    "recruitee",
    "personio",
    "breezy",
    "jazzhr",
    "bamboohr",
    "scrape",
}

_DIRECT = 0
_AGGREGATOR = 1


def source_rank(source: str) -> int:
    """0 for direct/ATS sources, 1 for aggregators and anything unknown."""
    return _DIRECT if source in _CANONICAL else _AGGREGATOR
