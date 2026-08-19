import re
from pathlib import Path
from typing import Any, Literal, cast, get_args, get_origin

from resume_agent.config import Settings


ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
CONFIG_DOC = ROOT / "docs" / "configuration.md"
ENV_ASSIGNMENT = re.compile(r"\s*#?\s*([A-Z][A-Z0-9_]*)=")
DOC_ROW = re.compile(
    r"^\| `([A-Z][A-Z0-9_]*)` \| ([^|]+) \| (.*) \|$",
    re.MULTILINE,
)


def _field_env_names(name: str, field: Any) -> tuple[str, ...]:
    alias = field.validation_alias
    if choices := getattr(alias, "choices", None):
        return tuple(str(choice) for choice in choices)
    if alias is not None:
        return (str(alias),)
    return (name.upper(),)


def _canonical_env_names() -> set[str]:
    return {
        _field_env_names(name, field)[0]
        for name, field in Settings.model_fields.items()
    }


def _all_accepted_env_names() -> set[str]:
    return {
        env_name
        for name, field in Settings.model_fields.items()
        for env_name in _field_env_names(name, field)
    }


def _example_env_names() -> set[str]:
    return {
        match.group(1)
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if (match := ENV_ASSIGNMENT.match(line))
    }


def _settings(*, env_file: str | None) -> Settings:
    settings_type = cast(Any, Settings)
    return settings_type(_env_file=env_file)


def _documented_rows() -> dict[str, tuple[str, str]]:
    return {
        match.group(1): (match.group(2).strip().strip("`"), match.group(3))
        for match in DOC_ROW.finditer(CONFIG_DOC.read_text(encoding="utf-8"))
    }


def _display_default(value: Any) -> str:
    if value is None:
        return "unset"
    if value == "":
        return "empty"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


def test_env_example_covers_every_setting_without_unknown_keys():
    example_names = _example_env_names()

    assert _canonical_env_names() - example_names == set()
    assert example_names - _all_accepted_env_names() == set()


def test_configuration_reference_documents_every_setting():
    documented = _documented_rows()

    missing = {name for name in _canonical_env_names() if name not in documented}
    assert missing == set()


def test_configuration_reference_defaults_and_choices_match_settings():
    documented = _documented_rows()

    for field_name, field in Settings.model_fields.items():
        env_name = _field_env_names(field_name, field)[0]
        documented_default, purpose = documented[env_name]
        assert documented_default == _display_default(field.default), env_name
        if get_origin(field.annotation) is Literal:
            for choice in get_args(field.annotation):
                assert str(choice) in purpose, (env_name, choice)


def test_env_example_values_match_settings_defaults(monkeypatch):
    for name in _all_accepted_env_names():
        monkeypatch.delenv(name, raising=False)

    defaults = _settings(env_file=None)
    example = _settings(env_file=str(ENV_EXAMPLE))

    assert example.model_dump(mode="json") == defaults.model_dump(mode="json")
