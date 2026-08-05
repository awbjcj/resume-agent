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
    assert "- Python — covered — facts: s1" in block
    assert "- Kubernetes — gap — no profile evidence; do not claim or imply" in block
    assert (
        "- Terraform — adjacent (Infrastructure as Code) — may inform emphasis, "
        "never named" in block
    )
    assert block.index("Python") < block.index("Docker")


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
    assert [i.severity for i in critique.issues] == [Severity.major]
    assert "LangChain" in critique.issues[0].message


def test_coverage_critique_is_none_without_evidenced_must_haves():
    content = ResumeContent(contact=Contact(name="Ada"))

    assert coverage_critique(content, None) is None
    assert coverage_critique(content, SkillMatchContext()) is None
