import json

import httpx
import pytest

from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.profile.build import build_corpus_profile, build_profile
from resume_agent.profile.corpus import add_source
from resume_agent.profile.inference import InferredSkill, InferredSkills
from resume_agent.profile.synthesis import (
    ClaimVerdict,
    ClaimVerdicts,
    SynthesizedClaim,
    SynthesizedEntry,
    SynthesizedFragment,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


class _FakeGitHub:
    def fetch_profile(self, username):
        return {"login": username, "followers": 7, "public_repos": 1}

    def fetch_repos(self, username):
        return [{"name": "engine", "stargazers_count": 3, "language": "Python", "html_url": "https://github.com/ada/engine"}]


class _SequenceAgent:
    def __init__(self, contents):
        self._contents = list(contents)

    def run(self, prompt):
        return _FakeResult(self._contents.pop(0))

    async def arun(self, prompt):
        return self.run(prompt)


class _InferenceByEvidence:
    def run(self, prompt):
        merged = ProfileFacts.model_validate_json(prompt)
        bullet_id = merged.experience[0].bullets[0].id
        return _FakeResult(
            InferredSkills(
                skills=[
                    InferredSkill(
                        name="Mentorship",
                        category="soft",
                        evidence_fact_ids=[bullet_id],
                    )
                ]
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


def test_build_profile_combines_resume_and_github(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada Lovelace", encoding="utf-8")
    extracted = ProfileFacts(contact=Contact(name="Ada Lovelace"))

    facts, raw_text = build_profile(
        resume_path=resume,
        github_username="ada",
        extractor_agent=_FakeAgent(extracted),
        github_client=_FakeGitHub(),
    )

    assert raw_text == "Ada Lovelace"
    assert facts.contact.name == "Ada Lovelace"
    assert facts.github_profile is not None
    assert facts.github_profile.username == "ada"
    assert [p.name for p in facts.projects] == ["engine"]


def test_build_profile_skips_github_when_no_username(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    facts, raw_text = build_profile(
        resume_path=resume,
        github_username="",
        extractor_agent=_FakeAgent(ProfileFacts(contact=Contact(name="Ada"))),
        github_client=_FakeGitHub(),
    )
    assert raw_text == "Ada"
    assert facts.github_profile is None
    assert facts.projects == []


def test_build_corpus_profile_merges_fragments(tmp_path):
    profile_dir = tmp_path / "profile"
    (tmp_path / "resume.txt").write_text("Ada resume", encoding="utf-8")
    (tmp_path / "deck.md").write_text("Case study", encoding="utf-8")
    add_source(profile_dir, tmp_path / "resume.txt", primary=True)
    add_source(profile_dir, tmp_path / "deck.md")
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                bullets=[Bullet(text="Mentored 3 engineers")],
            )
        ],
    )
    deck_facts = ProfileFacts(
        contact=Contact(name=""),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                bullets=[Bullet(text="Led the migration")],
            )
        ],
    )

    facts, report = build_corpus_profile(
        profile_dir,
        github_username="",
        extractor_agent=_SequenceAgent([resume_facts, deck_facts]),
    )
    assert len(facts.experience) == 1
    assert len(facts.experience[0].bullets) == 2
    assert set(report.doc_status.values()) == {"extracted"}


def test_build_corpus_profile_runs_inference(tmp_path):
    profile_dir = tmp_path / "profile"
    (tmp_path / "resume.txt").write_text("Ada resume", encoding="utf-8")
    add_source(profile_dir, tmp_path / "resume.txt", primary=True)
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                company="Acme",
                title="Engineer",
                bullets=[Bullet(text="Mentored 3 engineers")],
            )
        ],
    )

    facts, report = build_corpus_profile(
        profile_dir,
        github_username="",
        extractor_agent=_SequenceAgent([resume_facts]),
        inference_agent=_InferenceByEvidence(),
    )
    assert report.inferred_added == ["Mentorship"]
    assert facts.skills["soft"][0].inferred is True


def test_build_corpus_profile_requires_sources(tmp_path):
    with pytest.raises(ValueError, match="no sources"):
        build_corpus_profile(tmp_path / "empty", github_username="")


def test_build_aborts_when_primary_has_no_fragment(tmp_path):
    profile_dir = tmp_path / "profile"
    primary = tmp_path / "resume.txt"
    secondary = tmp_path / "notes.txt"
    primary.write_text("resume", encoding="utf-8")
    secondary.write_text("notes", encoding="utf-8")
    add_source(profile_dir, primary, primary=True)
    add_source(profile_dir, secondary)
    with pytest.raises(ValueError, match="primary"):
        build_corpus_profile(
            profile_dir,
            github_username="",
            extractor_agent=_SequenceAgent(
                [RuntimeError("boom"), ProfileFacts(contact=Contact(name="Ada"))]
            ),
        )


class _Extractor:
    def run(self, prompt):
        return _FakeResult(ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[Experience(company="Acme", title="Engineer")],
        ))

    async def arun(self, prompt):
        return self.run(prompt)


class _SkeletonAwareSynthesis:
    """Reads the anchor id out of the skeleton section of its own prompt."""

    def run(self, prompt):
        skeleton_json = prompt.split("PROFILE SKELETON (anchor candidates):\n")[1]
        skeleton = json.loads(skeleton_json.split("\n\nDOCUMENT:\n")[0])
        anchor = next(r["id"] for r in skeleton if r["kind"] == "experience")
        return _FakeResult(SynthesizedFragment(entries=[SynthesizedEntry(
            kind="experience_bullets", anchor_id=anchor,
            claims=[SynthesizedClaim(text="Cut latency 30%",
                                     support=["Cut latency 30%"])],
        )]))

    async def arun(self, prompt):
        return self.run(prompt)


class _ApproveAll:
    def run(self, prompt):
        claims = json.loads(prompt)
        return _FakeResult(ClaimVerdicts(verdicts=[
            ClaimVerdict(index=c["index"], verdict="supported") for c in claims
        ]))

    async def arun(self, prompt):
        return self.run(prompt)


def test_corpus_build_applies_synthesis_docs(tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada Lovelace — Engineer at Acme", encoding="utf-8")
    add_source(profile_dir, resume, primary=True)
    deck = tmp_path / "deck.md"
    deck.write_text("Cut latency 30% on the Acme billing system.", encoding="utf-8")
    add_source(profile_dir, deck, mode="synthesis")

    facts, report = build_corpus_profile(
        profile_dir,
        github_username=None,
        extractor_agent=_Extractor(),
        synthesis_agent=_SkeletonAwareSynthesis(),
        entailment_agent=_ApproveAll(),
    )
    acme = next(e for e in facts.experience if e.company == "Acme")
    assert any(b.text == "Cut latency 30%" and b.synthesized for b in acme.bullets)
    assert report.anchor_decisions
    assert report.verification_drops == []


def test_corpus_build_skips_synthesis_without_agents(tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    add_source(profile_dir, resume, primary=True)
    deck = tmp_path / "deck.md"
    deck.write_text("Cut latency 30%.", encoding="utf-8")
    add_source(profile_dir, deck, mode="synthesis")

    facts, report = build_corpus_profile(
        profile_dir, github_username=None, extractor_agent=_Extractor()
    )
    assert any("synthesis skipped" in w for w in report.warnings)


class _DeadGitHub:
    def fetch_repos(self, _username):
        raise httpx.ConnectError("network down")

    def fetch_profile(self, _username):
        raise httpx.ConnectError("network down")


def test_build_includes_project_fragments_and_degrades_github_failures(tmp_path):
    from resume_agent.profile.project_extractor import ProjectDocFacts

    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    add_source(profile_dir, resume, primary=True)
    dossier = tmp_path / "tool-dossier.md"
    dossier.write_text(
        "---\nrepo_url: https://github.com/me/tool\n---\n# Tool\n",
        encoding="utf-8",
    )
    add_source(profile_dir, dossier)

    facts, report = build_corpus_profile(
        profile_dir,
        github_username="me",
        github_client=_DeadGitHub(),
        extractor_agent=_FakeAgent(ProfileFacts(contact=Contact(name="Ada"))),
        project_agent=_FakeAgent(
            ProjectDocFacts(
                project=Project(name="Tool", repo_url="https://github.com/me/tool"),
                skills={"tools": [Skill(name="Python")]},
            )
        ),
    )
    assert [project.name for project in facts.projects] == ["Tool"]
    assert facts.skills["tools"][0].name == "Python"
    assert any("github" in warning.casefold() for warning in report.warnings)


def test_build_warns_when_project_agent_is_missing(tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    add_source(profile_dir, resume, primary=True)
    dossier = tmp_path / "tool-dossier.md"
    dossier.write_text(
        "---\nrepo_url: https://github.com/me/tool\n---\n# Tool\n",
        encoding="utf-8",
    )
    add_source(profile_dir, dossier)

    _facts, report = build_corpus_profile(
        profile_dir,
        github_username=None,
        extractor_agent=_FakeAgent(ProfileFacts(contact=Contact(name="Ada"))),
    )
    assert any("project extraction skipped" in warning for warning in report.warnings)
