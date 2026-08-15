from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
    TailoredSkill,
)
from resume_agent.models.review import Severity
from resume_agent.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext
from resume_agent.tailor.coverage import (
    COVERAGE_REVIEWER,
    CoverageCritique,
    coverage_critique,
    coverage_report,
    format_coverage,
)


def _context() -> SkillMatchContext:
    return SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Python",
                source="must",
                coverage="covered",
                row=MatrixRow(key="python", display="Python", evidence_fact_ids=["s1"]),
            ),
            SkillMatch(
                requirement="LangChain",
                source="must",
                coverage="covered",
                row=MatrixRow(key="langchain", display="LangChain", evidence_fact_ids=["s2"]),
            ),
            SkillMatch(requirement="Kubernetes", source="must", coverage="gap", row=None),
            SkillMatch(
                requirement="Terraform",
                source="must",
                coverage="adjacent",
                row=MatrixRow(key="iac", display="Infrastructure as Code"),
            ),
            SkillMatch(
                requirement="Docker",
                source="nice",
                coverage="covered",
                row=MatrixRow(key="docker", display="Docker", evidence_fact_ids=["s3"]),
            ),
        ]
    )


def test_format_coverage_lists_must_haves_before_nice_to_haves():
    block = format_coverage(_context())

    assert block.startswith("MUST-HAVE COVERAGE")
    assert "- (must-have) Python — covered — facts: s1" in block
    assert (
        "- (must-have) Kubernetes — gap — no profile evidence; do not claim or imply"
        in block
    )
    assert (
        "- (must-have) Terraform — adjacent (Infrastructure as Code) — may inform "
        "emphasis, never named" in block
    )
    assert block.index("Python") < block.index("Docker")


def test_format_coverage_names_the_tier_of_every_requirement():
    # The block carries all three tiers under one MUST-HAVE header, so ordering
    # alone cannot tell the writer a nice-to-have gap from a must-have gap.
    block = format_coverage(_context())

    assert "- (nice-to-have) Docker — covered — facts: s3" in block


def test_format_coverage_labels_a_tech_stack_requirement():
    context = SkillMatchContext(
        matches=[
            SkillMatch(requirement="Kafka", source="tech", coverage="gap", row=None)
        ]
    )

    assert "- (tech stack) Kafka — gap" in format_coverage(context)


def test_format_coverage_degrades_to_empty_without_a_context():
    assert format_coverage(None) == ""
    assert format_coverage(SkillMatchContext()) == ""


def test_coverage_report_counts_a_skills_entry_as_rendered():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    report = coverage_report(content, _context())

    assert report.covered_total == 2
    assert report.rendered == ["Python"]
    assert report.missed == ["LangChain"]


def test_coverage_report_counts_a_bullet_mention_as_rendered():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(text="Built agents with LangChain", provenance="b1")
                ],
            )
        ],
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    report = coverage_report(content, _context())

    assert sorted(report.rendered) == ["LangChain", "Python"]
    assert report.missed == []


def test_coverage_report_does_not_match_a_phrase_across_two_bullets():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Machine Learning",
                source="must",
                coverage="covered",
                row=MatrixRow(key="machine learning", display="Machine Learning"),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(text="Serviced the machine", provenance="b1"),
                    TailoredBullet(text="Learning was continuous", provenance="b2"),
                ],
            )
        ],
    )

    report = coverage_report(content, context)

    assert report.rendered == []
    assert report.missed == ["Machine Learning"]


def test_coverage_report_does_not_count_a_summary_only_mention():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="LangChain",
                source="must",
                coverage="covered",
                row=MatrixRow(key="langchain", display="LangChain"),
            )
        ]
    )
    content = ResumeContent(contact=Contact(name="Ada"), summary="LangChain engineer")

    report = coverage_report(content, context)

    assert report.rendered == []
    assert report.missed == ["LangChain"]


def test_coverage_report_does_not_count_a_project_description_only_mention():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="LangChain",
                source="must",
                coverage="covered",
                row=MatrixRow(key="langchain", display="LangChain"),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        projects=[
            TailoredProject(
                name="Agents",
                description="Built with LangChain",
                provenance="p1",
            )
        ],
    )

    report = coverage_report(content, context)

    assert report.rendered == []
    assert report.missed == ["LangChain"]


def test_coverage_report_accepts_a_row_display_equivalent_only():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="AWS",
                source="must",
                coverage="covered",
                row=MatrixRow(
                    key="cloud-provider",
                    display="Amazon Web Services",
                    aliases=["Cloud"],
                ),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(
                        text="Deployed services on Amazon Web Services", provenance="b1"
                    )
                ],
            )
        ],
    )

    report = coverage_report(content, context)

    assert report.covered_total == 1
    assert report.rendered == ["AWS"]
    assert report.missed == []


def test_coverage_report_accepts_a_normalized_requirement_equivalent_only():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="PYTHON!",
                source="must",
                coverage="covered",
                row=MatrixRow(
                    key="language",
                    display="Scripting Language",
                    aliases=["Py"],
                ),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="python", provenance="s1")]},
    )

    report = coverage_report(content, context)

    assert report.rendered == ["PYTHON!"]
    assert report.missed == []


def test_coverage_report_accepts_a_row_alias_equivalent_only():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="AWS",
                source="must",
                coverage="covered",
                row=MatrixRow(
                    key="cloud-provider",
                    display="Hosted Platform",
                    aliases=["Cloud"],
                ),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Cloud", provenance="s1")]},
    )

    report = coverage_report(content, context)

    assert report.rendered == ["AWS"]
    assert report.missed == []


def test_coverage_report_accepts_canonical_row_key_in_a_skill_entry():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Amazon Web Services",
                source="must",
                coverage="covered",
                row=MatrixRow(key="aws", display="Cloud Platform"),
            )
        ]
    )
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="AWS", provenance="s1")]},
    )

    report = coverage_report(content, context)

    assert report.rendered == ["Amazon Web Services"]
    assert report.missed == []


def test_coverage_critique_scores_the_rendered_share_and_never_blocks():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    critique = coverage_critique(content, _context())

    assert critique is not None
    assert isinstance(critique, CoverageCritique)
    assert critique.reviewer == COVERAGE_REVIEWER
    assert critique.passed is True
    assert critique.score == 50
    assert critique.model_dump(mode="json")["covered_total"] == 2
    assert critique.model_dump(mode="json")["rendered_total"] == 1
    # Score still reports the MUST-HAVE share only; supporting coverage rides
    # alongside as its own issue and must not move this number.
    assert critique.score == 50
    assert all(issue.severity == Severity.major for issue in critique.issues)
    must_issues = [i for i in critique.issues if i.message.startswith("must-have")]
    assert len(must_issues) == 1
    assert "LangChain" in must_issues[0].message


def test_coverage_critique_is_none_without_evidenced_must_haves():
    content = ResumeContent(contact=Contact(name="Ada"))

    assert coverage_critique(content, None) is None
    assert coverage_critique(content, SkillMatchContext()) is None


def _supporting_context(count: int = 3) -> SkillMatchContext:
    """Only nice-to-have / tech-stack requirements, all evidenced."""
    return SkillMatchContext(
        matches=[
            SkillMatch(
                requirement=f"Tool{index}",
                source="nice" if index % 2 else "tech",
                coverage="covered",
                row=MatrixRow(
                    key=f"tool{index}",
                    display=f"Tool{index}",
                    evidence_fact_ids=[f"s{index}"],
                ),
            )
            for index in range(count)
        ]
    )


def test_coverage_report_measures_supporting_tiers_separately():
    # Under-inclusion was invisible: the report skipped every non-must match, so
    # a resume could omit every evidenced nice-to-have and tech-stack skill and
    # no reviewer could observe it.
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Tool0", provenance="s0")]},
    )

    report = coverage_report(content, _supporting_context())

    assert report.supporting_total == 3
    assert report.supporting_rendered == ["Tool0"]
    assert report.supporting_missed == ["Tool1", "Tool2"]
    # Must-have accounting is untouched.
    assert report.covered_total == 0


def test_coverage_report_keeps_must_haves_out_of_the_supporting_tally():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    report = coverage_report(content, _context())

    assert report.covered_total == 2
    assert report.missed == ["LangChain"]
    # 'Docker' is the only evidenced nice-to-have in _context().
    assert report.supporting_total == 1
    assert report.supporting_missed == ["Docker"]


def test_coverage_critique_aggregates_omitted_supporting_skills_into_one_issue():
    # One issue per omitted supporting skill would flood the reviser prompt on a
    # profile with hundreds of skills, so the omissions are named in a single
    # bounded issue.
    content = ResumeContent(contact=Contact(name="Ada"))

    critique = coverage_critique(content, _supporting_context(count=30))

    assert critique is not None
    supporting_issues = [
        issue for issue in critique.issues if "supporting" in issue.message
    ]
    assert len(supporting_issues) == 1
    assert supporting_issues[0].severity == Severity.major
    assert "Tool0" in supporting_issues[0].message
    # Bounded: the message names a sample and counts the remainder.
    assert "more" in supporting_issues[0].message


def test_coverage_critique_reports_supporting_totals_through_json():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Tool0", provenance="s0")]},
    )

    critique = coverage_critique(content, _supporting_context())
    assert critique is not None
    dumped = critique.model_dump(mode="json")

    assert dumped["supporting_total"] == 3
    assert dumped["supporting_rendered_total"] == 1


def test_coverage_critique_exists_when_only_supporting_skills_are_evidenced():
    # Previously returned None whenever no must-have was evidenced, which is
    # exactly the case where breadth feedback matters most.
    content = ResumeContent(contact=Contact(name="Ada"))

    critique = coverage_critique(content, _supporting_context())

    assert critique is not None
    assert critique.passed is True
