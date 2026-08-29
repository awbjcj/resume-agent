import json

from resume_agent.taxonomy import skills


def test_split_skill_on_comma_and_or():
    assert skills.split_skill("Python, C++ or C") == ["Python", "C++", "C"]


def test_split_skill_on_slash():
    assert skills.split_skill("Python/Java") == ["Python", "Java"]


def test_split_skill_protects_known_tokens():
    assert skills.split_skill("CI/CD") == ["CI/CD"]
    assert skills.split_skill("A/B testing") == ["A/B testing"]


def test_split_skill_atomic_passthrough():
    assert skills.split_skill("Node.js") == ["Node.js"]
    assert skills.split_skill("  Go  ") == ["Go"]


def test_split_skills_flattens_and_dedupes_preserving_order():
    assert skills.split_skills(["Python, Go", "Go", "Rust"]) == ["Python", "Go", "Rust"]


class _FakeCanonicalizer:
    def __init__(self, mapping):
        self._mapping = mapping
        self.seen = None

    def __call__(self, tokens):
        self.seen = set(tokens)
        return {t: self._mapping.get(t, t) for t in tokens}


def test_load_aliases_missing_file_is_empty(tmp_path):
    assert skills.load_aliases(tmp_path / "nope.json") == {}


def test_canonical_skill_applies_alias_then_normalizes():
    aliases = {"k8s": "kubernetes"}
    assert skills.canonical_skill("K8s", aliases) == "kubernetes"
    assert skills.canonical_skill("Python", aliases) == "python"


def test_merge_aliases_keeps_existing_choice():
    merged = skills.merge_aliases(
        {"k8s": "kubernetes"}, {"k8s": "k8s", "js": "javascript"}
    )
    assert merged == {"k8s": "kubernetes", "js": "javascript"}


def test_refresh_aliases_writes_and_merges(tmp_path):
    path = tmp_path / "skill_aliases.json"
    path.write_text(json.dumps({"py": "python"}), "utf-8")
    canon = _FakeCanonicalizer({"k8s": "kubernetes"})
    merged = skills.refresh_aliases({"k8s", "kubernetes"}, canon, path)
    assert merged["py"] == "python"
    assert merged["k8s"] == "kubernetes"
    assert json.loads(path.read_text("utf-8"))["k8s"] == "kubernetes"
    assert canon.seen == {"k8s", "kubernetes"}


def test_load_aliases_caches_until_file_changes(tmp_path):
    import os

    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"js": "javascript"}), "utf-8")
    first = skills.load_aliases(path)
    assert skills.load_aliases(path) is first

    path.write_text(json.dumps({"js": "javascript", "ts": "typescript"}), "utf-8")
    new_ns = os.stat(path).st_mtime_ns + 1_000_000
    os.utime(path, ns=(new_ns, new_ns))
    assert skills.load_aliases(path)["ts"] == "typescript"


def test_load_aliases_missing_file_returns_empty(tmp_path):
    assert skills.load_aliases(tmp_path / "absent.json") == {}
