from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
)
from resume_agent.profile.depth import (
    SUPPLY_TARGET,
    depth_topics,
    evidence_owners,
    owner_depth,
    planned_owners,
)
from resume_agent.tailor.length import format_depth_plan
from resume_agent.tailor.review_config import LengthBudget


def _bullets(count: int, *, prefix: str = "bullet") -> list[Bullet]:
    return [
        Bullet(id=f"{prefix}-{index}", text=f"{prefix} {index}")
        for index in range(count)
    ]


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-1",
                company="One",
                title="Engineer",
                bullets=_bullets(6, prefix="e1"),
            ),
            Experience(
                id="exp-2",
                company="Two",
                title="Engineer",
                bullets=_bullets(2, prefix="e2"),
            ),
            Experience(
                id="exp-3",
                company="Three",
                title="Engineer",
                bullets=_bullets(4, prefix="e3"),
            ),
        ],
        projects=[
            Project(
                id="prj-1", name="One project", highlights=_bullets(4, prefix="p1")
            ),
            Project(id="prj-2", name="Empty project"),
        ],
    )


def test_evidence_owners_exposes_experience_and_project_bullets():
    owners = evidence_owners(_facts())

    assert [(owner.id, owner.kind, len(owner.bullets)) for owner in owners] == [
        ("exp-1", "experience", 6),
        ("exp-2", "experience", 2),
        ("exp-3", "experience", 4),
        ("prj-1", "project", 4),
        ("prj-2", "project", 0),
    ]


def test_planned_owners_honor_kind_and_combined_caps_and_skip_empty_supply():
    budget = LengthBudget(max_experiences=2, max_projects=2, max_evidence_owners=3)

    assert [owner.id for owner in planned_owners(_facts(), budget)] == [
        "exp-1",
        "exp-2",
        "prj-1",
    ]


def test_planned_owners_skip_kinds_with_a_zero_render_floor():
    budget = LengthBudget(
        min_bullets_per_role=0,
        min_bullets_per_project=0,
    )

    assert planned_owners(_facts(), budget) == []


def test_depth_plan_clamps_each_floor_to_its_source_supply():
    text = format_depth_plan(_facts(), LengthBudget(max_evidence_owners=8))

    assert '"One — Engineer": 6 source -> render 5–6' in text
    assert '"Two — Engineer": 2 source -> render 2 (supply-limited' in text
    assert '"One project": 4 source -> render 4' in text
    assert "Empty project" not in text


def test_owner_depth_reports_supply_and_stable_aspect_gaps():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-1",
                company="One",
                title="Engineer",
                bullets=[
                    Bullet(id="b1", text="Built it", aspect="technical"),
                    Bullet(id="b2", text="Led it", aspect="leadership"),
                    Bullet(id="b3", text="Measured it"),
                ],
            )
        ],
    )

    row = owner_depth(facts)[0]

    assert SUPPLY_TARGET == 10
    assert row.source_total == 3
    assert row.meets_target is False
    assert row.aspects_present == ["technical", "leadership"]
    assert "impact" in row.aspects_missing
    assert row.unclassified == 1


def test_depth_topics_seed_only_nonempty_below_target_owners_in_source_order():
    topics = depth_topics(_facts(), target=5, cap=2)

    assert [(topic.id, topic.owner_id, topic.related_ref) for topic in topics] == [
        ("t1", "exp-2", "exp-2"),
        ("t2", "exp-3", "exp-3"),
    ]
    assert "2 of 5 source bullets" in topics[0].gap
    assert "profile holds" in topics[0].why_it_matters
