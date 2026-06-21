from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import IngestOutcome, add_job, save_or_upgrade
from resume_agent.tracking.repository import (
    application_for_job,
    get_cover_letter,
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
        job = add_job(s, source="manual", jd_text="  hello  ", company="  Acme ", title=" Eng ")
        assert job is not None
        assert job.status == JobStatus.raw.value
        assert job.jd_text == "hello"
        assert job.company == "Acme"
        assert job.title == "Eng"


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
        job, outcome = save_or_upgrade(s, source="adzuna", jd_text="jd", url="http://a/1",
                                       company="Acme", title="Backend Engineer")
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
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin jd", url="http://adz/1",
                                   company="Acme Corp", title="Backend Engineer")
        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url="http://workday/1", company="Acme Corp",
                                            title="Senior Backend Engineer")
        assert first is not None
        assert upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.source == "workday"
        assert upgraded.url == "http://workday/1"
        assert upgraded.jd_text == "full canonical jd"


def test_raw_upgrade_does_not_clobber_existing_fields_with_missing_values():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin jd", url="http://adz/1",
                                   company="Acme Corp", title="Backend Engineer",
                                   location="Remote")
        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url=None, company="Acme Corp",
                                            title="Backend Engineer", location=None)
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
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin jd", url="http://x/1",
                                   company="Acme Corp", title="Backend Engineer")
        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url="http://x/1", company=None, title=None)
        assert first is not None
        assert upgraded is not None
        assert outcome is IngestOutcome.upgraded
        assert upgraded.id == first.id
        assert upgraded.company == "Acme Corp"
        assert upgraded.title == "Backend Engineer"


def test_lower_tier_does_not_overwrite_higher_tier():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="workday", jd_text="canonical", url="http://wd/1",
                                   company="Acme", title="Backend Engineer")
        job, outcome = save_or_upgrade(s, source="adzuna", jd_text="thin", url="http://adz/1",
                                       company="Acme", title="Backend Engineer")
        assert first is not None
        assert outcome is IngestOutcome.skipped
        assert job is None
        assert first.source == "workday" and first.url == "http://wd/1"


def test_equal_tier_keeps_first_seen():
    with _session() as s:
        save_or_upgrade(s, source="greenhouse", jd_text="gh jd", url="http://gh/1",
                        company="Acme", title="Backend Engineer")
        job, outcome = save_or_upgrade(s, source="workday", jd_text="wd jd", url="http://wd/1",
                                       company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.skipped
        assert job is None


def test_upgrade_preserves_application_and_status():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="thin", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        assert first is not None
        assert first.id is not None
        first.status = JobStatus.shortlisted.value
        s.add(first)
        s.commit()
        s.add(Application(job_id=first.id, status=ApplicationStatus.submitted.value,
                          notes="applied via referral"))
        s.commit()
        resume = save_resume_version(s, ResumeVersion(job_id=first.id, pdf_path="/r/resume.pdf"))
        cover = save_cover_letter(s, CoverLetter(job_id=first.id, pdf_path="/c/cover.pdf"))
        assert resume.id is not None and cover.id is not None

        upgraded, outcome = save_or_upgrade(s, source="workday", jd_text="full canonical jd",
                                            url="http://wd/1", company="Acme",
                                            title="Backend Engineer")
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
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="ORIGINAL jd", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        assert first is not None
        first.status = JobStatus.tailored.value
        s.add(first)
        s.commit()

        upgraded, _ = save_or_upgrade(s, source="workday", jd_text="REPLACEMENT jd",
                                      url="http://wd/1", company="Acme", title="Backend Engineer")
        assert upgraded is not None
        assert upgraded.url == "http://wd/1"
        assert upgraded.source == "workday"
        assert upgraded.jd_text == "ORIGINAL jd"


def test_post_raw_higher_tier_without_url_is_skipped():
    with _session() as s:
        first, _ = save_or_upgrade(s, source="adzuna", jd_text="ORIGINAL jd", url="http://adz/1",
                                   company="Acme", title="Backend Engineer")
        assert first is not None
        first.status = JobStatus.tailored.value
        s.add(first)
        s.commit()

        job, outcome = save_or_upgrade(s, source="workday", jd_text="REPLACEMENT jd",
                                       url=None, company="Acme", title="Backend Engineer")
        assert outcome is IngestOutcome.skipped
        assert job is None


def test_same_source_different_url_inserts_as_distinct_posting():
    """Same company+title from the same ATS but different URLs = different locations; both kept."""
    with _session() as s:
        j1, o1 = save_or_upgrade(s, source="workday", jd_text="jd nyc",
                                  url="http://wd/nyc", company="Acme", title="Engineer")
        j2, o2 = save_or_upgrade(s, source="workday", jd_text="jd sf",
                                  url="http://wd/sf", company="Acme", title="Engineer")
        assert o1 is IngestOutcome.inserted
        assert o2 is IngestOutcome.inserted
        assert j1 is not None and j2 is not None
        assert j1.id != j2.id
