from resume_agent.setup.preflight import (
    CheckResult,
    check_examples_present,
    check_python,
    check_uv,
)


def test_check_python_passes_for_modern_version():
    r = check_python(version=(3, 13, 0))
    assert isinstance(r, CheckResult)
    assert r.ok is True


def test_check_python_fails_and_gives_remedy():
    r = check_python(version=(3, 11, 0))
    assert r.ok is False
    assert "3.13" in r.remedy


def test_check_uv_uses_injected_which():
    assert check_uv(which=lambda n: "/usr/bin/uv").ok is True
    missing = check_uv(which=lambda n: None)
    assert missing.ok is False
    assert "uv" in missing.remedy.lower()


def test_check_examples_present(tmp_path):
    (tmp_path / "config").mkdir()
    for name in (
        "search.yaml.example",
        "connectors.yaml.example",
        "profile_sources.yaml.example",
        "review.yaml.example",
        "review_deep.yaml.example",
        "render.yaml.example",
    ):
        (tmp_path / "config" / name).write_text("x", encoding="utf-8")
    assert check_examples_present(root=tmp_path).ok is True
    (tmp_path / "config" / "search.yaml.example").unlink()
    assert check_examples_present(root=tmp_path).ok is False
