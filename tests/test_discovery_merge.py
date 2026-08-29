from datetime import datetime, timezone
from typing import Any

from resume_agent.discovery.merge import (
    IncomingJob,
    Insert,
    Rebase,
    RefreshText,
    Skip,
    UpgradeUrlOnly,
    decide,
)
from resume_agent.tracking.tables import Job, JobStatus


def _incoming(**over) -> IncomingJob:
    base: dict[str, Any] = dict(
        source="workday",
        jd_text="full jd",
        url="http://wd/1",
        company="Acme Corp",
        title="Backend Engineer",
        location="Remote",
        posted_at=None,
    )
    base.update(over)
    return IncomingJob.clean(**base)


def _existing(**over) -> Job:
    base: dict[str, Any] = dict(
        source="adzuna",
        jd_text="thin",
        url="http://adz/1",
        company="Acme Corp",
        title="Backend Engineer",
        status=JobStatus.raw.value,
    )
    base.update(over)
    return Job(**base)


def test_decide_inserts_when_no_existing():
    assert decide(None, _incoming()) == Insert()


def test_decide_skips_lower_tier():
    assert decide(_existing(source="workday"), _incoming(source="adzuna")) == Skip()


def test_decide_skips_equal_tier_first_seen_wins():
    assert decide(_existing(source="greenhouse"), _incoming(source="workday")) == Skip()


def test_decide_treats_same_source_different_url_as_distinct():
    existing = _existing(source="workday", url="http://wd/nyc")
    incoming = _incoming(source="workday", url="http://wd/sf")
    assert decide(existing, incoming) == Insert()


def test_decide_post_raw_higher_tier_with_url_upgrades_url_only():
    existing = _existing(
        source="adzuna", status=JobStatus.tailored.value, url="http://adz/1"
    )
    action = decide(existing, _incoming(source="workday", url="http://wd/1"))
    assert action == UpgradeUrlOnly(url="http://wd/1", source="workday")


def test_decide_post_raw_higher_tier_without_url_skips():
    existing = _existing(source="adzuna", status=JobStatus.tailored.value)
    assert decide(existing, _incoming(source="workday", url=None)) == Skip()


def test_decide_raw_rebase_merges_and_recomputes_dedup_key():
    existing = _existing(source="adzuna", status=JobStatus.raw.value)
    action = decide(
        existing,
        _incoming(
            source="workday",
            jd_text="full canonical jd",
            url="http://wd/1",
            company="Acme Corp",
            title="Senior Backend Engineer",
            location="Austin",
        ),
    )
    assert isinstance(action, Rebase)
    assert action.updates["source"] == "workday"
    assert action.updates["jd_text"] == "full canonical jd"
    assert action.updates["url"] == "http://wd/1"
    assert action.updates["title"] == "Senior Backend Engineer"
    assert action.updates["location"] == "Austin"
    # dedup_key recomputed from the merged company + title (seniority stripped).
    assert action.updates["dedup_key"] == "acme corp|backend engineer"


def test_decide_rebase_omits_absent_optionals_and_keeps_existing_for_dedup():
    existing = _existing(source="adzuna", status=JobStatus.raw.value)
    action = decide(
        existing,
        _incoming(source="workday", url=None, company=None, title=None, location=None),
    )
    assert isinstance(action, Rebase)
    assert "url" not in action.updates
    assert "company" not in action.updates
    assert "title" not in action.updates
    # dedup_key falls back to the existing company + title the incoming omitted.
    assert action.updates["dedup_key"] == "acme corp|backend engineer"


def test_decide_rebase_threads_posted_at():
    existing = _existing(status=JobStatus.raw.value, source="adzuna")
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    action = decide(existing, _incoming(source="workday", posted_at=when))
    assert isinstance(action, Rebase)
    assert action.updates["posted_at"] == when


def test_decide_refreshes_same_source_url_when_text_is_richer():
    existing = _existing(source="adzuna", jd_text="thin preview", url="http://adz/1")
    incoming = _incoming(
        source="adzuna",
        url="http://adz/1",
        jd_text=" ".join(f"full{i}" for i in range(70)),
        title="Senior Backend Engineer",
        location="Remote",
    )
    action = decide(existing, incoming)
    assert isinstance(action, RefreshText)
    assert "full69" in action.updates["jd_text"]
    assert action.updates["title"] == "Senior Backend Engineer"
    assert action.updates["location"] == "Remote"


def test_decide_does_not_refresh_text_after_rendering():
    existing = _existing(
        source="adzuna",
        status=JobStatus.rendered.value,
        jd_text="thin preview",
        url="http://adz/1",
    )
    incoming = _incoming(
        source="adzuna",
        url="http://adz/1",
        jd_text=" ".join(f"full{i}" for i in range(70)),
    )
    assert decide(existing, incoming) == Skip()


def test_incoming_clean_strips_and_blanks_to_none():
    inc = IncomingJob.clean(
        source="manual",
        jd_text="  hi  ",
        company="  Acme ",
        title="  ",
        url=None,
        location="",
        posted_at=None,
    )
    assert inc.jd_text == "hi"
    assert inc.company == "Acme"
    assert inc.title is None
    assert inc.location is None
    assert inc.dedup_key is None
