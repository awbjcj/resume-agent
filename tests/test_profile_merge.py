from resume_tailor_harness.models.base import Source
from resume_tailor_harness.models.profile import (
    Award,
    Bullet,
    Certification,
    Contact,
    Education,
    Experience,
    GitHubProfile,
    Language,
    ProfileFacts,
    Project,
    Publication,
    Skill,
    Volunteer,
)
from resume_tailor_harness.profile.corpus import SourceDoc
from resume_tailor_harness.profile.merge import (
    BulletDupGroups,
    MergeReport,
    apply_synthesis_fragments,
    dedup_experience_bullets,
    merge_facts,
    merge_fragments,
)


def test_merge_appends_github_projects_and_sets_profile():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="from-resume", source=Source.resume)],
    )
    gh_projects = [Project(name="from-github", source=Source.github)]
    gh_profile = GitHubProfile(username="ada", total_stars=5)

    merged = merge_facts(
        resume_facts, github_projects=gh_projects, github_profile=gh_profile
    )

    names = [p.name for p in merged.projects]
    assert names == ["from-resume", "from-github"]
    assert merged.github_profile is not None
    assert merged.github_profile.username == "ada"


def test_merge_without_github_is_unchanged_copy():
    resume_facts = ProfileFacts(contact=Contact(name="Ada"))
    merged = merge_facts(resume_facts)
    assert merged is not resume_facts  # a copy, not the same object
    assert merged.github_profile is None
    assert merged.contact.name == "Ada"


def test_merge_dedupes_github_project_by_normalized_name_and_enriches():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="Résumé Tailor Harness", source=Source.resume)],
    )
    gh_projects = [
        Project(
            name="resume-tailor-harness",
            source=Source.github,
            stars=42,
            repo_url="https://github.com/ada/resume-tailor-harness",
        )
    ]

    merged = merge_facts(resume_facts, github_projects=gh_projects)

    names = [p.name for p in merged.projects]
    assert names == ["Résumé Tailor Harness"]
    assert merged.projects[0].stars == 42
    assert merged.projects[0].repo_url == "https://github.com/ada/resume-tailor-harness"


def test_merge_keeps_distinct_github_project():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"), projects=[Project(name="from-resume")]
    )
    gh = [Project(name="totally-different", source=Source.github)]
    merged = merge_facts(resume_facts, github_projects=gh)
    assert [p.name for p in merged.projects] == ["from-resume", "totally-different"]


def test_project_identity_prefers_repo_url_across_fragment_and_metadata_merges():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[
            Project(
                name="Résumé Tailor Harness CLI",
                repo_url="https://github.com/me/resume-tailor-harness",
                description="from resume",
            )
        ],
    )
    dossier = ProfileFacts(
        contact=Contact(name=""),
        projects=[
            Project(
                name="resume-tailor-harness",
                repo_url="git@github.com:Me/Resume-Tailor-Harness.git",
                highlights=[Bullet(text="From dossier")],
            )
        ],
    )
    merged, _ = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("dossier"), dossier)]
    )
    enriched = merge_facts(
        merged,
        github_projects=[
            Project(
                source=Source.github,
                name="different display",
                repo_url="ssh://git@github.com/me/resume-tailor-harness.git",
                stars=42,
                languages=["Python"],
                topics=["agents"],
                is_fork=False,
            )
        ],
    )
    assert len(enriched.projects) == 1
    project = enriched.projects[0]
    assert project.description == "from resume"
    assert [highlight.text for highlight in project.highlights] == ["From dossier"]
    assert project.stars == 42
    assert project.languages == ["Python"]
    assert project.topics == ["agents"]
    assert project.is_fork is False


def test_same_project_name_with_distinct_repo_urls_stays_distinct():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="tool", repo_url="https://github.com/a/tool")],
    )
    merged = merge_facts(
        facts,
        github_projects=[Project(name="tool", repo_url="https://github.com/b/tool")],
    )
    assert len(merged.projects) == 2


def _doc(doc_id, primary=False):
    return SourceDoc(
        id=doc_id,
        filename=f"{doc_id}.txt",
        sha256="0" * 64,
        added_at="2026-07-01T00:00:00+00:00",
        primary=primary,
    )


def _exp(
    company="Acme",
    title="Engineer",
    start=None,
    end=None,
    current=False,
    bullets=(),
    tech=(),
):
    return Experience(
        company=company,
        title=title,
        start=start,
        end=end,
        current=current,
        bullets=[Bullet(text=text) for text in bullets],
        tech=list(tech),
    )


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeDedupAgent:
    def __init__(self, groups):
        self._groups = groups

    def run(self, prompt):
        return _FakeResult(BulletDupGroups(groups=self._groups))

    async def arun(self, prompt):
        return self.run(prompt)


def test_same_experience_across_docs_unions_bullets_and_tech():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[_exp(start="2020", bullets=["Shipped v1"], tech=["Python"])],
    )
    deck = ProfileFacts(
        contact=Contact(name=""),
        experience=[_exp(start="2021", bullets=["Led migration"], tech=["Go"])],
    )
    merged, report = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("deck"), deck)]
    )
    assert len(merged.experience) == 1
    assert sorted(item.text for item in merged.experience[0].bullets) == [
        "Led migration",
        "Shipped v1",
    ]
    assert sorted(merged.experience[0].tech) == ["Go", "Python"]
    assert merged.experience[0].start == "2020"
    assert any("start" in conflict for conflict in report.conflicts)


def test_known_disjoint_experience_ranges_do_not_merge():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[_exp(start="2018", end="2019")],
    )
    later = ProfileFacts(
        contact=Contact(name=""),
        experience=[_exp(start="2022", end="2023")],
    )
    merged, _ = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("later"), later)]
    )
    assert len(merged.experience) == 2


def test_contact_fill_and_current_conflict_follow_primary_wins():
    primary = ProfileFacts(
        contact=Contact(name="Ada", email=None, location="Boston"),
        experience=[_exp(start="2020", end="2024", current=False)],
    )
    secondary = ProfileFacts(
        contact=Contact(name="Ada L.", email="ada@example.com", location="NYC"),
        experience=[_exp(start="2020", current=True)],
    )
    merged, report = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("deck"), secondary)]
    )
    assert merged.contact.name == "Ada"
    assert merged.contact.email == "ada@example.com"
    assert merged.contact.location == "Boston"
    assert merged.experience[0].current is False
    assert any("contact: name" in conflict for conflict in report.conflicts)
    assert any("current" in conflict for conflict in report.conflicts)


def test_duplicate_projects_merge_all_fields_and_report_conflicts():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="Compiler", description="Primary", tech=["Python"])],
    )
    secondary = ProfileFacts(
        contact=Contact(name=""),
        projects=[
            Project(
                name="compiler",
                description="Secondary",
                role="Lead",
                start="2024",
                tech=["Rust"],
                highlights=[Bullet(text="Published")],
            )
        ],
    )
    merged, report = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("deck"), secondary)]
    )
    project = merged.projects[0]
    assert project.description == "Primary"
    assert project.role == "Lead"
    assert project.start == "2024"
    assert project.tech == ["Python", "Rust"]
    assert [highlight.text for highlight in project.highlights] == ["Published"]
    assert any(
        "project Compiler: description" in conflict for conflict in report.conflicts
    )


def test_duplicate_other_entities_merge_scalars_and_collections():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        education=[Education(institution="MIT", degree="BS", honors=["A"])],
        certifications=[Certification(name="AWS")],
        publications=[Publication(title="Paper", authors=["Ada"])],
        awards=[Award(name="Prize")],
        languages=[Language(language="English")],
        volunteer=[Volunteer(organization="Code Club", role="Mentor")],
    )
    secondary = ProfileFacts(
        contact=Contact(name=""),
        education=[
            Education(
                institution="mit",
                degree="BS",
                field="CS",
                honors=["B"],
                activities=["Robotics"],
            )
        ],
        certifications=[Certification(name="aws", issuer="Amazon")],
        publications=[Publication(title="paper", venue="Journal", authors=["Grace"])],
        awards=[Award(name="prize", issuer="ACM")],
        languages=[Language(language="english", proficiency="Native")],
        volunteer=[
            Volunteer(
                organization="code club", role="Mentor", description="Taught Python"
            )
        ],
    )
    merged, _ = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("deck"), secondary)]
    )
    assert merged.education[0].field == "CS"
    assert merged.education[0].honors == ["A", "B"]
    assert merged.education[0].activities == ["Robotics"]
    assert merged.certifications[0].issuer == "Amazon"
    assert merged.publications[0].authors == ["Ada", "Grace"]
    assert merged.awards[0].issuer == "ACM"
    assert merged.languages[0].proficiency == "Native"
    assert merged.volunteer[0].description == "Taught Python"


def test_skills_union_by_normalized_name():
    primary = ProfileFacts(
        contact=Contact(name="Ada"), skills={"Languages": [Skill(name="Python")]}
    )
    secondary = ProfileFacts(
        contact=Contact(name=""),
        skills={"Languages": [Skill(name="python"), Skill(name="Go")]},
    )
    merged, _ = merge_fragments(
        [(_doc("resume", primary=True), primary), (_doc("deck"), secondary)]
    )
    assert [skill.name for skill in merged.skills["Languages"]] == ["Python", "Go"]


def test_dedup_agent_drops_shorter_near_duplicate():
    primary = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            _exp(bullets=["Shipped v1 of the payments platform", "Shipped v1"])
        ],
    )
    merged, report = merge_fragments(
        [(_doc("resume", primary=True), primary)],
        dedup_agent=_FakeDedupAgent([[0, 1]]),
    )
    assert [item.text for item in merged.experience[0].bullets] == [
        "Shipped v1 of the payments platform"
    ]
    assert report.dropped_bullets == ["Shipped v1"]


def test_dedup_agent_failure_keeps_all_bullets():
    class _Boom:
        def run(self, prompt):
            raise RuntimeError("boom")

        async def arun(self, prompt):
            raise RuntimeError("boom")

    primary = ProfileFacts(
        contact=Contact(name="Ada"), experience=[_exp(bullets=["A", "B"])]
    )
    merged, report = merge_fragments(
        [(_doc("resume", primary=True), primary)], dedup_agent=_Boom()
    )
    assert len(merged.experience[0].bullets) == 2
    assert isinstance(report, MergeReport)


def test_merge_fragments_requires_exactly_one_primary_first():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    import pytest

    with pytest.raises(ValueError, match="primary"):
        merge_fragments([(_doc("secondary"), facts)])


def _deck_doc():
    return SourceDoc(
        id="deck-1",
        filename="deck.pptx",
        sha256="0" * 64,
        added_at="2026-07-03T00:00:00+00:00",
        mode="synthesis",
    )


def _merged():
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp1",
                company="Acme",
                title="Engineer",
                bullets=[Bullet(id="b1", text="Shipped the billing rewrite")],
                tech=["Python"],
            )
        ],
    )


def _synth_fragment(anchor_id="exp1"):
    return ProfileFacts(
        contact=Contact(name=""),
        experience=[
            Experience(
                id=anchor_id,
                company="Acme",
                title="Engineer",
                synthesized=True,
                bullets=[
                    Bullet(id="sb1", text="Cut p99 latency 30%", synthesized=True),
                    Bullet(
                        id="sb2", text="Shipped the billing rewrite", synthesized=True
                    ),
                ],
                tech=["Kubernetes", "Python"],
            )
        ],
        skills={
            "hard": [
                Skill(id="sk1", name="Kubernetes", category="hard", synthesized=True)
            ]
        },
        projects=[
            Project(
                id="sp1",
                name="Side tool",
                synthesized=True,
                highlights=[Bullet(text="Built a CLI")],
            )
        ],
    )


def test_anchored_bullets_append_by_id_with_exact_dedup():
    merged = _merged()
    report = MergeReport()
    decisions, touched = apply_synthesis_fragments(
        merged, [(_deck_doc(), _synth_fragment())], report
    )
    target = merged.experience[0]
    texts = [bullet.text for bullet in target.bullets]
    assert "Cut p99 latency 30%" in texts
    assert texts.count("Shipped the billing rewrite") == 1  # exact dup skipped
    assert "Kubernetes" in target.tech and target.tech.count("Python") == 1
    assert touched == {"exp1"}
    assert any("exp1" in line or "Acme" in line for line in decisions)
    assert merged.skills["hard"][0].name == "Kubernetes"
    assert any(project.name == "Side tool" for project in merged.projects)


def test_unresolvable_anchor_falls_back_to_project():
    merged = _merged()
    report = MergeReport()
    decisions, touched = apply_synthesis_fragments(
        merged, [(_deck_doc(), _synth_fragment(anchor_id="ghost"))], report
    )
    assert touched == set()
    assert len(merged.experience[0].bullets) == 1  # untouched
    fallback = next(
        p for p in merged.projects if p.synthesized and p.name != "Side tool"
    )
    assert "Cut p99 latency 30%" in [
        highlight.text for highlight in fallback.highlights
    ]
    assert any("not found" in line for line in decisions)


def test_synthesis_project_merges_by_repo_url_when_names_differ():
    merged = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="Tool CLI", repo_url="https://github.com/me/tool")],
    )
    fragment = ProfileFacts(
        contact=Contact(name=""),
        projects=[
            Project(
                name="tool",
                repo_url="git@github.com:me/tool.git",
                highlights=[Bullet(text="Synthesized detail")],
            )
        ],
    )
    apply_synthesis_fragments(merged, [(_deck_doc(), fragment)], MergeReport())
    assert len(merged.projects) == 1
    assert [highlight.text for highlight in merged.projects[0].highlights] == [
        "Synthesized detail"
    ]


def test_synthesized_scalars_never_win():
    merged = _merged()
    merged.experience[0].location = "Detroit"
    fragment = _synth_fragment()
    fragment.experience[0].location = "Austin"
    apply_synthesis_fragments(merged, [(_deck_doc(), fragment)], MergeReport())
    assert merged.experience[0].location == "Detroit"


def _synth_fragment_all_dupes(anchor_id="exp1"):
    """A synthesis fragment whose stub bullets are all exact duplicates already
    present on the anchor target, so applying it appends zero new bullets."""
    return ProfileFacts(
        contact=Contact(name=""),
        experience=[
            Experience(
                id=anchor_id,
                company="Acme",
                title="Engineer",
                synthesized=True,
                bullets=[
                    Bullet(
                        id="sb1", text="Shipped the billing rewrite", synthesized=True
                    )
                ],
            )
        ],
    )


def test_touched_only_includes_experiences_that_gained_bullets():
    merged = _merged()
    report = MergeReport()
    decisions, touched = apply_synthesis_fragments(
        merged, [(_deck_doc(), _synth_fragment_all_dupes())], report
    )
    assert len(merged.experience[0].bullets) == 1  # no new bullets appended
    assert touched == set()
    assert any("+0 bullets" in line for line in decisions)


class _RecordingDedupAgent:
    """Fake dedup agent that records which experience's bullet listing it saw."""

    def __init__(self):
        self.seen_prompts: list[str] = []

    def run(self, prompt):
        self.seen_prompts.append(prompt)
        return _FakeResult(BulletDupGroups(groups=[]))

    async def arun(self, prompt):
        return self.run(prompt)


def test_dedup_experience_bullets_only_ids_skips_untouched_experiences():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-touched",
                company="Acme",
                title="Engineer",
                bullets=[Bullet(text="Shipped v1"), Bullet(text="Shipped v1 again")],
            ),
            Experience(
                id="exp-untouched",
                company="Globex",
                title="Analyst",
                bullets=[
                    Bullet(text="Analyzed reports"),
                    Bullet(text="Analyzed more reports"),
                ],
            ),
        ],
    )
    agent = _RecordingDedupAgent()
    report = MergeReport()

    dedup_experience_bullets(facts, agent, report, only_ids={"exp-touched"})

    assert len(agent.seen_prompts) == 1
    assert "Shipped v1" in agent.seen_prompts[0]
    assert "Analyzed reports" not in agent.seen_prompts[0]
