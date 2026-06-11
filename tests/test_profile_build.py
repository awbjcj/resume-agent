from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.build import build_profile


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)


class _FakeGitHub:
    def fetch_profile(self, username):
        return {"login": username, "followers": 7, "public_repos": 1}

    def fetch_repos(self, username):
        return [{"name": "engine", "stargazers_count": 3, "language": "Python", "html_url": "https://github.com/ada/engine"}]


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
