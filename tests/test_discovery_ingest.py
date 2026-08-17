from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.ingest import (
    IngestOutcome,
    add_job,
    ingest_jobs_with_outcomes,
    save_or_upgrade,
)
from resume_agent.tracking.repository import (
    application_for_job,
    archive_job,
    get_cover_letter,
    jobs_by_status,
    resume_versions_for_job,
    save_cover_letter,
    save_resume_version,
)
from resume_agent.tracking.tables import (
    Application,
    ApplicationStatus,
    CoverLetter,
    JobStatus,
    ResumeVersion,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_add_job_inserts_raw_and_strips_fields():
    with _session() as s:
        job = add_job(
            s, source="manual", jd_text="  hello  ", company="  Acme ", title=" Eng "
        )
        assert job is not None
        assert job.status == JobStatus.raw.value
        assert job.jd_text == "hello"
        assert job.company == "Acme"
        assert job.title == "Eng"


def test_add_job_normalizes_provider_location_separators():
    with _session() as s:
        job = add_job(
            s,
            source="personio",
            jd_text="hello",
            location="Berlin // Remote; Berlin",
        )

        assert job is not None
        assert job.location == "Berlin | Remote"


def test_add_job_dedupes_identical_jd():
    with _session() as s:
        first = add_job(s, source="manual", jd_text="same text")
        dup = add_job(s, source="manual", jd_text="same text")
        assert first is not None
        assert dup is None


def test_add_job_dedupes_by_url():
    with _session() as s:
        add_job(s, source="manual", jd_text="a", url="http://x/1")
        dup = add_job(s, source="manual", jd_text="b", url="http://x/1")
        assert dup is None


def test_add_job_dedupes_same_company_title_across_sources():
    with _session() as s:
        first = add_job(
            s,
            source="greenhouse",
            jd_text="full canonical jd",
            url="http://gh/1",
            company="Acme Corp",
            title="Senior Backend Engineer",
        )
        dup = add_job(
            s,
            source="adzuna",
            jd_text="truncated jd...",
            url="http://adz/2",
            company="acme corp",
            title="Backend Engineer",
        )
        assert first is not None
        assert dup is None


def test_add_job_keeps_distinct_when_company_or_title_missing():
    with _session() as s:
        a = add_job(s, source="manual", jd_text="text one")
        b = add_job(s, source="manual", jd_text="text two")
        assert a is not None and b is not None


def test_save_or_upgrade_inserts_new():
    with _session() as s:
        job, outcome = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="jd",
            url="http://a/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert outcome is IngestOutcome.inserted
        assert job is not None and job.source == "adzuna"


def test_same_source_richer_text_refreshes_existing_row():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin preview",
            url="http://adz/1",
            company="Acme",
            title="Backend Engineer",
        )
        richer, outcome = save_or_upgrade(
            s,
            source="adzuna",
            jd_text=" ".join(f"full{i}" for i in range(70)),
            url="http://adz/1",
            company="Acme",
            title="Senior Backend Engineer",
            location="Remote",
        )
        assert first is not None
        assert richer is not None
        assert outcome is IngestOutcome.upgraded
        assert richer.id == first.id
        assert "full69" in richer.jd_text
        assert richer.title == "Senior Backend Engineer"
        assert richer.location == "Remote"


def test_higher_tier_upgrades_lower_tier_in_place():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin jd",
            url="http://adz/1",
            company="Acme Corp",
            title="Backend Engineer",
        )
        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full canonical jd",
            url="http://workday/1",
            company="Acme Corp",
            title="Senior Backend Engineer",
        )
        assert first is not None
        assert upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.source == "workday"
        assert upgraded.url == "http://workday/1"
        assert upgraded.jd_text == "full canonical jd"


def test_raw_upgrade_does_not_clobber_existing_fields_with_missing_values():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin jd",
            url="http://adz/1",
            company="Acme Corp",
            title="Backend Engineer",
            location="Remote",
        )
        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full canonical jd",
            url=None,
            company="Acme Corp",
            title="Backend Engineer",
            location=None,
        )
        assert first is not None
        assert upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.url == "http://adz/1"
        assert upgraded.location == "Remote"


def test_raw_upgrade_keeps_company_and_title_when_incoming_missing():
    # Matched by URL so a higher-tier source that omits company/title still upgrades
    # the row — but those omitted fields must not clobber what we already learned.
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin jd",
            url="http://x/1",
            company="Acme Corp",
            title="Backend Engineer",
        )
        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full canonical jd",
            url="http://x/1",
            company=None,
            title=None,
        )
        assert first is not None
        assert upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.company == "Acme Corp"
        assert upgraded.title == "Backend Engineer"


def test_lower_tier_does_not_overwrite_higher_tier():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="workday",
            jd_text="canonical",
            url="http://wd/1",
            company="Acme",
            title="Backend Engineer",
        )
        job, outcome = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin",
            url="http://adz/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert first is not None
        assert outcome is IngestOutcome.skipped
        assert job is None
        assert first.source == "workday" and first.url == "http://wd/1"


def test_equal_tier_keeps_first_seen():
    with _session() as s:
        save_or_upgrade(
            s,
            source="greenhouse",
            jd_text="gh jd",
            url="http://gh/1",
            company="Acme",
            title="Backend Engineer",
        )
        job, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="wd jd",
            url="http://wd/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert outcome is IngestOutcome.skipped
        assert job is None


def test_direct_url_refreshes_richer_greenhouse_copy():
    with _session() as session:
        existing, _ = save_or_upgrade(
            session,
            source="greenhouse",
            jd_text="Who we are\nBuild SDKs.",
            url="https://stripe.com/jobs/search?gh_jid=7557899",
            company="Stripe",
            title="Backend Engineer, Developer SDKs (Golang)",
        )
        refreshed, outcome = save_or_upgrade(
            session,
            source="url",
            jd_text=" ".join(
                [
                    "Who we are. Build SDKs.",
                    "In-office expectations: spend at least 50% of each month in the office.",
                    "Pay and benefits: CA$135,200 - CA$258,000 plus health benefits.",
                ]
                * 8
            ),
            url=(
                "https://stripe.com/careers/listing/"
                "backend-engineer-developer-sdks-golang/7557899?gh_jid=7557899"
            ),
            company="Stripe",
            title="Backend Engineer, Developer SDKs (Golang)",
            location="Toronto, CA",
        )

        assert existing is not None
        assert outcome is IngestOutcome.upgraded
        assert refreshed is not None and refreshed.id == existing.id
        assert refreshed.location == "Toronto, CA"
        assert "Pay and benefits" in refreshed.jd_text


def test_richer_direct_url_refresh_requeues_stale_analysis():
    with _session() as session:
        existing, _ = save_or_upgrade(
            session,
            source="greenhouse",
            jd_text="Who we are\nBuild SDKs.",
            url="https://stripe.com/jobs/search?gh_jid=7557899",
            company="Stripe",
            title="Backend Engineer, Developer SDKs (Golang)",
        )
        assert existing is not None and existing.id is not None
        existing.status = JobStatus.shortlisted.value
        existing.criteria_json = {"employment_type": None, "salary_range": None}
        existing.analysis_meta_json = {"criteria": {"model": "stale"}}
        existing.fit_score = 82
        existing.fit_rationale = "Based on the incomplete description."
        session.add(existing)
        session.commit()

        richer = " ".join(
            [
                "Who we are. Build SDKs.",
                "In-office expectations: spend at least 50% of each month in the office.",
                "Pay and benefits: CA$135,200 - CA$258,000 plus health benefits.",
            ]
            * 8
        )
        counts = ingest_jobs_with_outcomes(
            session,
            [
                RawJob(
                    source="url",
                    jd_text=richer,
                    url=(
                        "https://stripe.com/careers/listing/"
                        "backend-engineer-developer-sdks-golang/7557899?gh_jid=7557899"
                    ),
                    company="Stripe",
                    title="Backend Engineer, Developer SDKs (Golang)",
                    location="Toronto, CA",
                )
            ],
        )

        session.refresh(existing)
        assert counts.upgraded == {"url": 1}
        assert counts.changed_raw_job_ids == [existing.id]
        assert existing.status == JobStatus.raw.value
        assert existing.criteria_json is None
        assert existing.analysis_meta_json is None
        assert existing.fit_score is None
        assert existing.fit_rationale is None
        assert existing.location == "Toronto, CA"
        assert "Pay and benefits" in existing.jd_text


def test_richer_direct_url_refresh_does_not_replace_user_progress():
    with _session() as session:
        existing, _ = save_or_upgrade(
            session,
            source="greenhouse",
            jd_text="Who we are\nBuild SDKs.",
            url="https://stripe.com/jobs/search?gh_jid=7557899",
            company="Stripe",
            title="Backend Engineer, Developer SDKs (Golang)",
        )
        assert existing is not None and existing.id is not None
        existing.status = JobStatus.shortlisted.value
        session.add(existing)
        session.add(
            Application(
                job_id=existing.id,
                status=ApplicationStatus.submitted.value,
            )
        )
        session.commit()

        refreshed, outcome = save_or_upgrade(
            session,
            source="url",
            jd_text=" ".join(f"richer{i}" for i in range(80)),
            url=(
                "https://stripe.com/careers/listing/"
                "backend-engineer-developer-sdks-golang/7557899?gh_jid=7557899"
            ),
            company="Stripe",
            title="Backend Engineer, Developer SDKs (Golang)",
            location="Toronto, CA",
        )

        session.refresh(existing)
        assert outcome is IngestOutcome.skipped
        assert refreshed is None
        assert existing.jd_text == "Who we are\nBuild SDKs."
        assert existing.location is None


def test_upgrade_preserves_application_and_status():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="thin",
            url="http://adz/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert first is not None
        assert first.id is not None
        first.status = JobStatus.shortlisted.value
        s.add(first)
        s.commit()
        s.add(
            Application(
                job_id=first.id,
                status=ApplicationStatus.submitted.value,
                notes="applied via referral",
            )
        )
        s.commit()
        resume = save_resume_version(
            s, ResumeVersion(job_id=first.id, pdf_path="/r/resume.pdf")
        )
        cover = save_cover_letter(
            s, CoverLetter(job_id=first.id, pdf_path="/c/cover.pdf")
        )
        assert resume.id is not None and cover.id is not None

        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full canonical jd",
            url="http://wd/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert upgraded is not None
        assert upgraded.id is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.status == JobStatus.shortlisted.value
        app = application_for_job(s, upgraded.id)
        assert app is not None and app.notes == "applied via referral"
        # AC4: upgrading the posting must not orphan or drop user-authored artifacts.
        versions = resume_versions_for_job(s, upgraded.id)
        assert len(versions) == 1 and versions[0].pdf_path == "/r/resume.pdf"
        saved_cover = get_cover_letter(s, cover.id)
        assert saved_cover is not None and saved_cover.pdf_path == "/c/cover.pdf"


def test_post_raw_upgrade_freezes_text_but_takes_url():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="ORIGINAL jd",
            url="http://adz/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert first is not None
        first.status = JobStatus.tailored.value
        s.add(first)
        s.commit()

        upgraded, _ = save_or_upgrade(
            s,
            source="workday",
            jd_text="REPLACEMENT jd",
            url="http://wd/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert upgraded is not None
        assert upgraded.url == "http://wd/1"
        assert upgraded.source == "workday"
        assert upgraded.jd_text == "ORIGINAL jd"


def test_post_raw_higher_tier_without_url_is_skipped():
    with _session() as s:
        first, _ = save_or_upgrade(
            s,
            source="adzuna",
            jd_text="ORIGINAL jd",
            url="http://adz/1",
            company="Acme",
            title="Backend Engineer",
        )
        assert first is not None
        first.status = JobStatus.tailored.value
        s.add(first)
        s.commit()

        job, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="REPLACEMENT jd",
            url=None,
            company="Acme",
            title="Backend Engineer",
        )
        assert outcome is IngestOutcome.skipped
        assert job is None


def test_same_source_different_url_inserts_as_distinct_posting():
    """Same company+title from the same ATS but different URLs = different locations; both kept."""
    with _session() as s:
        j1, o1 = save_or_upgrade(
            s,
            source="workday",
            jd_text="jd nyc",
            url="http://wd/nyc",
            company="Acme",
            title="Engineer",
        )
        j2, o2 = save_or_upgrade(
            s,
            source="workday",
            jd_text="jd sf",
            url="http://wd/sf",
            company="Acme",
            title="Engineer",
        )
        assert o1 is IngestOutcome.inserted
        assert o2 is IngestOutcome.inserted
        assert j1 is not None and j2 is not None
        assert j1.id != j2.id


def test_keyless_near_duplicate_collapses_via_fingerprint():
    from resume_agent.discovery.ingest import add_job
    from resume_agent.tracking.repository import jobs_by_status
    from resume_agent.tracking.tables import JobStatus

    with _session() as s:
        first = add_job(s, source="remoteok", jd_text="Build great systems for us")
        second = add_job(s, source="remoteok", jd_text="Build  great   systems for us")
        assert first is not None
        assert second is None  # deduped by fingerprint, not inserted
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_same_key_different_city_inserts_sibling():
    with _session() as s:
        first = add_job(
            s,
            source="workday",
            jd_text="Build cars. Austin team.",
            company="GM",
            title="Software Engineer",
            location="Austin, TX",
        )
        sibling = add_job(
            s,
            source="workday",
            jd_text="Build cars. Detroit team.",
            company="GM",
            title="Software Engineer",
            location="Detroit, MI",
        )

        assert first is not None and sibling is not None
        assert first.id != sibling.id
        assert first.dedup_key == sibling.dedup_key


def test_identical_jd_different_city_inserts_sibling():
    with _session() as s:
        first = add_job(
            s,
            source="workday",
            jd_text="Same req text",
            company="GM",
            title="Software Engineer",
            location="Austin, TX",
            url="http://wd/1",
        )
        sibling = add_job(
            s,
            source="workday",
            jd_text="Same req text",
            company="GM",
            title="Software Engineer",
            location="Detroit, MI",
            url="http://wd/2",
        )

        assert first is not None and sibling is not None
        assert first.id != sibling.id


def test_same_key_compatible_city_upgrades_in_place():
    with _session() as s:
        aggregate = add_job(
            s,
            source="adzuna",
            jd_text="snippet",
            company="GM",
            title="Software Engineer",
            location="Austin, TX",
        )
        assert aggregate is not None

        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full detail text",
            company="GM",
            title="Software Engineer",
            location="Austin, Texas, United States",
            url="http://wd/1",
        )

        assert outcome is IngestOutcome.upgraded
        assert upgraded is not None and upgraded.id == aggregate.id


def test_blank_location_still_merges():
    with _session() as s:
        aggregate = add_job(
            s,
            source="adzuna",
            jd_text="snippet",
            company="GM",
            title="Software Engineer",
        )
        assert aggregate is not None

        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="full detail",
            company="GM",
            title="Software Engineer",
            location="Austin, TX",
            url="http://wd/1",
        )

        assert outcome is IngestOutcome.upgraded
        assert upgraded is not None and upgraded.id == aggregate.id


def test_keyless_fingerprint_different_city_inserts_sibling():
    with _session() as s:
        first = add_job(
            s,
            source="remoteok",
            jd_text="Build great systems",
            location="Austin, TX",
        )
        sibling = add_job(
            s,
            source="remoteok",
            jd_text="BUILD   GREAT SYSTEMS",
            location="Detroit, MI",
        )

        assert first is not None and sibling is not None
        assert first.id != sibling.id


def test_location_guard_scans_past_incompatible_candidate():
    with _session() as s:
        austin = add_job(
            s,
            source="adzuna",
            jd_text="Austin snippet",
            company="GM",
            title="Software Engineer",
            location="Austin, TX",
        )
        detroit = add_job(
            s,
            source="adzuna",
            jd_text="Detroit snippet",
            company="GM",
            title="Software Engineer",
            location="Detroit, MI",
        )
        upgraded, outcome = save_or_upgrade(
            s,
            source="workday",
            jd_text="Detroit full detail",
            company="GM",
            title="Software Engineer",
            location="Detroit, Michigan",
            url="http://wd/detroit",
        )

        assert austin is not None and detroit is not None and upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == detroit.id


def test_archived_duplicate_does_not_block_new_active_job():
    with _session() as s:
        archived = add_job(
            s,
            source="manual",
            url="https://jobs.example/1",
            jd_text="Build great systems",
        )
        assert archived is not None and archived.id is not None
        archive_job(s, archived.id)

        active = add_job(
            s,
            source="manual",
            url="https://jobs.example/1",
            jd_text="Build  great systems",
        )

        assert active is not None
        assert active.id != archived.id
        assert [j.id for j in jobs_by_status(s, JobStatus.raw.value)] == [active.id]


def test_skipped_outcome_is_counted():
    from resume_agent.discovery.connectors.base import RawJob
    from resume_agent.discovery.ingest import ingest_jobs_with_outcomes

    with _session() as s:
        job = RawJob(
            source="greenhouse",
            url="https://x/1",
            company="Acme",
            title="AI Engineer",
            location="Remote",
            jd_text="Build agents.",
        )
        first = ingest_jobs_with_outcomes(s, [job])
        assert first.added.get("greenhouse") == 1

        again = ingest_jobs_with_outcomes(s, [job])
        assert again.added.get("greenhouse", 0) == 0
        assert again.skipped.get("greenhouse") == 1


def test_active_job_cap_blocks_only_new_rows():
    from resume_agent.discovery.connectors.base import RawJob
    from resume_agent.discovery.ingest import ingest_jobs_with_outcomes

    with _session() as s:
        first = RawJob(
            source="adzuna",
            jd_text="thin",
            url="https://a/1",
            company="Acme",
            title="Engineer",
            location=None,
        )
        second = RawJob(
            source="adzuna",
            jd_text="other",
            url="https://a/2",
            company="Beta",
            title="Engineer",
            location=None,
        )
        assert ingest_jobs_with_outcomes(s, [first], max_active_jobs=1).added == {
            "adzuna": 1
        }

        blocked = ingest_jobs_with_outcomes(s, [second], max_active_jobs=1)
        assert blocked.quota_skipped == {"adzuna": 1}

        upgraded = RawJob(
            source="workday",
            jd_text="full canonical description",
            url="https://wd/1",
            company="Acme",
            title="Engineer",
            location=None,
        )
        result = ingest_jobs_with_outcomes(s, [upgraded], max_active_jobs=1)
        assert result.upgraded == {"workday": 1}


def test_archived_jobs_do_not_count_toward_active_job_cap():
    from resume_agent.discovery.connectors.base import RawJob
    from resume_agent.discovery.ingest import ingest_jobs_with_outcomes

    with _session() as s:
        old = add_job(s, source="manual", jd_text="old")
        assert old is not None and old.id is not None
        archive_job(s, old.id)

        result = ingest_jobs_with_outcomes(
            s,
            [
                RawJob(
                    source="manual",
                    jd_text="replacement",
                    url=None,
                    company=None,
                    title=None,
                    location=None,
                )
            ],
            max_active_jobs=1,
        )
        assert result.added == {"manual": 1}
        assert result.quota_skipped == {}
