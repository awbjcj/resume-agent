from resume_agent.models.base import Source
from resume_agent.models.profile import Contact, GitHubProfile, ProfileFacts, Project
from resume_agent.profile.merge import merge_facts


def test_merge_appends_github_projects_and_sets_profile():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="from-resume", source=Source.resume)],
    )
    gh_projects = [Project(name="from-github", source=Source.github)]
    gh_profile = GitHubProfile(username="ada", total_stars=5)

    merged = merge_facts(resume_facts, github_projects=gh_projects, github_profile=gh_profile)

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
        projects=[Project(name="Resume Agent", source=Source.resume)],
    )
    gh_projects = [
        Project(
            name="resume-agent",
            source=Source.github,
            stars=42,
            repo_url="https://github.com/ada/resume-agent",
        )
    ]

    merged = merge_facts(resume_facts, github_projects=gh_projects)

    names = [p.name for p in merged.projects]
    assert names == ["Resume Agent"]
    assert merged.projects[0].stars == 42
    assert merged.projects[0].repo_url == "https://github.com/ada/resume-agent"


def test_merge_keeps_distinct_github_project():
    resume_facts = ProfileFacts(contact=Contact(name="Ada"), projects=[Project(name="from-resume")])
    gh = [Project(name="totally-different", source=Source.github)]
    merged = merge_facts(resume_facts, github_projects=gh)
    assert [p.name for p in merged.projects] == ["from-resume", "totally-different"]
