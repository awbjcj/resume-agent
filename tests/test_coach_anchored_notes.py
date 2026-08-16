"""Regression: an approved anchored coach note must enrich its named role."""

from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.profile.corpus import SourceDoc
from resume_agent.profile.merge import MergeReport, apply_synthesis_fragments


def _target_facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-umich",
                company="University of Michigan",
                title="Graduate Student Instructor",
                bullets=[Bullet(id="existing", text="Taught verification modules")],
            )
        ],
    )


def _anchored_note() -> SourceDoc:
    return SourceDoc(
        id="note-teaching",
        filename="note--teaching-impact.md",
        sha256="0" * 64,
        added_at="2026-08-15T00:00:00Z",
        mode="synthesis",
        anchor="exp-umich",
    )


def _anchored_fragment() -> ProfileFacts:
    # Synthesis pins the generated stub's id to SourceDoc.anchor.  Deliberately
    # unrelated identity text makes a heuristic merge unable to pass this test.
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="exp-umich",
                company="",
                title="",
                synthesized=True,
                bullets=[
                    Bullet(id="note-1", text="Ran verification labs for 120 students"),
                    Bullet(id="note-2", text="Rewrote the final-project rubric"),
                ],
            )
        ],
    )


def test_anchored_note_bullets_land_on_its_target_without_a_duplicate_role():
    facts = _target_facts()

    apply_synthesis_fragments(
        facts, [(_anchored_note(), _anchored_fragment())], MergeReport()
    )

    assert len(facts.experience) == 1
    assert facts.projects == []
    assert [bullet.text for bullet in facts.experience[0].bullets] == [
        "Taught verification modules",
        "Ran verification labs for 120 students",
        "Rewrote the final-project rubric",
    ]


def test_rebuilding_the_same_anchored_note_does_not_duplicate_its_bullets():
    facts = _target_facts()
    pair = [(_anchored_note(), _anchored_fragment())]

    apply_synthesis_fragments(facts, pair, MergeReport())
    apply_synthesis_fragments(facts, pair, MergeReport())

    assert len(facts.experience) == 1
    assert len(facts.experience[0].bullets) == 3
