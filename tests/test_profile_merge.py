from resume_agent.models.profile import Contact, GitHubProfile, ProfileFacts, Project
from resume_agent.profile.merge import merge_facts


def test_merge_appends_github_projects_and_sets_profile():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="from-resume", source="resume")],
    )
    gh_projects = [Project(name="from-github", source="github")]
    gh_profile = GitHubProfile(username="ada", total_stars=5)

    merged = merge_facts(resume_facts, github_projects=gh_projects, github_profile=gh_profile)

    names = [p.name for p in merged.projects]
    assert names == ["from-resume", "from-github"]
    assert merged.github_profile.username == "ada"


def test_merge_without_github_is_unchanged_copy():
    resume_facts = ProfileFacts(contact=Contact(name="Ada"))
    merged = merge_facts(resume_facts)
    assert merged is not resume_facts  # a copy, not the same object
    assert merged.github_profile is None
    assert merged.contact.name == "Ada"
