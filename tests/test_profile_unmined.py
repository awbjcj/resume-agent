from resume_agent.models.base import Source
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    GitHubProfile,
    ProfileFacts,
    Skill,
)
from resume_agent.profile.corpus import add_source, doc_path, load_manifest
from resume_agent.profile.depth import unmined_block, unmined_sources
from resume_agent.profile.store import save_facts


def _workspace(tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.md"
    goals_2026 = tmp_path / "goals-2026.md"
    goals_2025 = tmp_path / "goals-2025.md"
    resume.write_text("# Resume\nBuilt the system.", encoding="utf-8")
    goals_2026.write_text("# 2026\n" + "Future target. " * 500, encoding="utf-8")
    goals_2025.write_text("# 2025\nImprove the platform.", encoding="utf-8")
    resume_doc = add_source(profile_dir, resume, primary=True)
    zero_doc = add_source(profile_dir, goals_2026)
    skill_doc = add_source(profile_dir, goals_2025)
    save_facts(
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="e1",
                    company="Acme",
                    title="Engineer",
                    source_ref=resume_doc.id,
                    bullets=[
                        Bullet(
                            id="b1",
                            text="Built the system",
                            source_ref=resume_doc.id,
                        )
                    ],
                )
            ],
            skills={
                "hard": [
                    Skill(
                        id="s1",
                        name="Python",
                        source=Source.manual,
                        source_ref=skill_doc.id,
                    )
                ]
            },
            github_profile=GitHubProfile(
                id="gh1", username="ada", source_ref=skill_doc.id
            ),
        ),
        profile_dir / "facts.json",
    )
    return profile_dir, resume_doc, zero_doc, skill_doc


def test_unmined_sources_are_ranked_by_all_fact_totals_and_exclude_bullet_docs(tmp_path):
    profile_dir, resume_doc, zero_doc, skill_doc = _workspace(tmp_path)

    rows = unmined_sources(profile_dir)

    assert [(row.doc_id, row.fact_total) for row in rows] == [
        (zero_doc.id, 0),
        (skill_doc.id, 2),
    ]
    assert resume_doc.id not in [row.doc_id for row in rows]


def test_unmined_block_is_bounded_and_keeps_the_safety_rule(tmp_path):
    profile_dir, _resume_doc, zero_doc, _skill_doc = _workspace(tmp_path)

    block = unmined_block(profile_dir, budget=600)

    assert len(block) <= 600
    assert "QUESTION MATERIAL, NEVER CLAIMABLE FACT" in block
    assert zero_doc.id in block


def test_unmined_block_degrades_away_when_every_candidate_is_unreadable(tmp_path):
    profile_dir, _resume_doc, _zero_doc, _skill_doc = _workspace(tmp_path)
    for source in (profile_dir / "sources").iterdir():
        source.unlink()

    assert unmined_block(profile_dir) == ""


def test_one_unreadable_unmined_source_does_not_hide_the_other_question_material(tmp_path):
    profile_dir, _resume_doc, zero_doc, skill_doc = _workspace(tmp_path)
    manifest = {doc.id: doc for doc in load_manifest(profile_dir).docs}
    doc_path(profile_dir, manifest[zero_doc.id]).unlink()

    block = unmined_block(profile_dir)

    assert skill_doc.id in block
