from resume_agent.tracking.canonicalize import (
    SkillClusters,
    build_skill_canonicalizer,
    clusters_to_mapping,
)


def test_clusters_to_mapping_uses_first_member_as_canonical():
    mapping = clusters_to_mapping([["kubernetes", "k8s"]], {"kubernetes", "k8s", "python"})

    assert mapping == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "python": "python",
    }


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRunner:
    def __init__(self, clusters):
        self._clusters = clusters

    def run(self, prompt):
        return _FakeResult(SkillClusters(clusters=self._clusters))


def test_canonicalizer_collapses_synonyms_with_a_fake_agent():
    canon = build_skill_canonicalizer(agent=_FakeRunner([["kubernetes", "k8s"]]))

    assert canon({"kubernetes", "k8s", "python"}) == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "python": "python",
    }


def test_canonicalizer_short_circuits_on_empty():
    canon = build_skill_canonicalizer(agent=_FakeRunner([]))

    assert canon(set()) == {}
