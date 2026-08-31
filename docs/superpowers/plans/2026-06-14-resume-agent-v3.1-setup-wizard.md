# Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `resume-tailor-harness setup` — a standalone Textual TUI that takes a new user from zero → configured → validated → ready, writing `.env` and `config/*.yaml` atomically, replacing the manual copy-and-edit ritual.

**Architecture:** Pure cores + thin shell. All real work lives in pure, unit-tested functions (`WizardState`, `merge_env`, the `build_*` YAML generators, `preflight`, `validate`, `atomic_write_all`); the Textual `App` is a thin screen-per-step shell that binds to `WizardState` and calls the cores. Pre-write validation reads secrets explicitly from `WizardState` (never the `@lru_cache get_settings()`); the optional post-write `profile build` runs as a subprocess that reads the freshly written `.env`. Writes are atomic-at-end (temp file + `os.replace`).

**Tech Stack:** Textual (new dependency), Typer (existing CLI), PyYAML (existing), pytest (+ Textual's `App.run_test()` pilot harness), Python 3.13.

---

## File Structure

| File                                                                                                                                                                                                     | Responsibility                                                                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `src/resume_tailor_harness/setup/__init__.py`                                                                                                                                                                     | Package marker.                                                                                                 |
| `src/resume_tailor_harness/setup/state.py`                                                                                                                                                                        | `WizardState` dataclass + `managed_env()`. The single source screens bind to.                                   |
| `src/resume_tailor_harness/setup/env_writer.py`                                                                                                                                                                   | `parse_env`, `merge_env`, `format_env` (pure).                                                                  |
| `src/resume_tailor_harness/setup/yaml_gen.py`                                                                                                                                                                     | `parse_greenhouse_boards`, `build_profile_sources/build_search/build_connectors` (pure), `render_from_example`. |
| `src/resume_tailor_harness/setup/preflight.py`                                                                                                                                                                    | `CheckResult` + detect-and-instruct preflight checks (injected callables).                                      |
| `src/resume_tailor_harness/setup/validate.py`                                                                                                                                                                     | `anthropic_ping`, `connector_smoke` (injected clients).                                                         |
| `src/resume_tailor_harness/setup/writer.py`                                                                                                                                                                       | `atomic_write_all` (temp file + `os.replace`, per-file, tmp cleanup on error) + `load_existing_state`.          |
| `src/resume_tailor_harness/setup/app.py`                                                                                                                                                                          | Thin Textual `SetupApp` (screen per step) + `_perform_write` seam.                                              |
| `src/resume_tailor_harness/cli.py`                                                                                                                                                                                | `setup` command (MODIFY).                                                                                       |
| `pyproject.toml`                                                                                                                                                                                         | Add `textual` (MODIFY via `uv add`).                                                                            |
| `README.md`                                                                                                                                                                                              | One line on running `setup` after `uv sync` (MODIFY).                                                           |
| `tests/test_setup_state.py`, `test_setup_env_writer.py`, `test_setup_yaml_gen.py`, `test_setup_preflight.py`, `test_setup_validate.py`, `test_setup_writer.py`, `test_setup_app.py`, `test_cli_setup.py` | NEW.                                                                                                            |

---

### Task 1: `textual` dependency + `setup` package + `WizardState`

**Files:**

- Modify: `pyproject.toml` (via `uv add`)
- Create: `src/resume_tailor_harness/setup/__init__.py`, `src/resume_tailor_harness/setup/state.py`
- Test: `tests/test_setup_state.py`

- [ ] **Step 1: Add the dependency**

Run: `uv add textual`
Expected: `pyproject.toml` gains `textual` under dependencies; lockfile updates; install succeeds.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_setup_state.py
from resume_tailor_harness.setup.state import WizardState


def test_defaults_match_settings_defaults():
    s = WizardState()
    assert s.db_url == "sqlite:///data/resume_tailor_harness.db"
    assert s.cheap_model == "claude-haiku-4-5-20251001"
    assert s.remote_policy == "any"
    assert s.greenhouse_boards == []


def test_managed_env_omits_empty_and_maps_keys():
    s = WizardState(anthropic_api_key="sk-test", github_token="")
    env = s.managed_env()
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "GITHUB_TOKEN" not in env          # empty → omitted
    assert env["DB_URL"] == "sqlite:///data/resume_tailor_harness.db"
    assert "OPENAI_API_KEY" not in env         # never managed
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.setup'`

- [ ] **Step 4: Write the implementation**

```python
# src/resume_tailor_harness/setup/__init__.py
"""Interactive setup wizard (pure cores + thin Textual shell)."""
```

```python
# src/resume_tailor_harness/setup/state.py
from dataclasses import dataclass, field


@dataclass
class WizardState:
    """Every answer the wizard collects. Screens bind to this; cores read it."""

    # secrets (→ .env)
    anthropic_api_key: str = ""
    github_token: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    linkedin_email: str = ""
    linkedin_password: str = ""
    db_url: str = "sqlite:///data/resume_tailor_harness.db"
    cheap_model: str = "claude-haiku-4-5-20251001"
    mid_model: str = "claude-sonnet-4-6"
    premium_model: str = "claude-opus-4-8"

    # profile sources (→ profile_sources.yaml)
    resume_path: str = ""
    github_username: str = ""

    # search (→ search.yaml)
    keywords: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_policy: str = "any"
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False

    # connectors (→ connectors.yaml)
    greenhouse_enabled: bool = False
    greenhouse_boards: list[dict] = field(default_factory=list)
    adzuna_enabled: bool = False
    adzuna_country: str = "us"
    remoteok_enabled: bool = False
    linkedin_enabled: bool = False

    def managed_env(self) -> dict[str, str]:
        """Map state secrets to .env keys, dropping empty values.

        Note: ``openai_api_key`` and ``linkedin_user_data_dir`` are deliberately
        NOT managed here — they are preserved by ``merge_env`` if already set.
        """
        candidates = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "GITHUB_TOKEN": self.github_token,
            "ADZUNA_APP_ID": self.adzuna_app_id,
            "ADZUNA_APP_KEY": self.adzuna_app_key,
            "LINKEDIN_EMAIL": self.linkedin_email,
            "LINKEDIN_PASSWORD": self.linkedin_password,
            "DB_URL": self.db_url,
            "CHEAP_MODEL": self.cheap_model,
            "MID_MODEL": self.mid_model,
            "PREMIUM_MODEL": self.premium_model,
        }
        return {k: v for k, v in candidates.items() if v}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_state.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/resume_tailor_harness/setup/__init__.py src/resume_tailor_harness/setup/state.py tests/test_setup_state.py
git commit -m "feat(setup): add textual dep + WizardState"
```

---

### Task 2: `parse_greenhouse_boards` pure parser

**Files:**

- Create: `src/resume_tailor_harness/setup/yaml_gen.py`
- Test: `tests/test_setup_yaml_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_yaml_gen.py
from resume_tailor_harness.setup.yaml_gen import parse_greenhouse_boards


def test_parses_token_and_company():
    boards = parse_greenhouse_boards("stripe, Stripe\nairbnb, Airbnb")
    assert boards == [
        {"token": "stripe", "company": "Stripe"},
        {"token": "airbnb", "company": "Airbnb"},
    ]


def test_token_only_defaults_company_to_titlecased_token():
    assert parse_greenhouse_boards("datadog") == [{"token": "datadog", "company": "Datadog"}]


def test_skips_blank_lines_and_trims():
    assert parse_greenhouse_boards("\n  stripe ,  Stripe \n\n") == [
        {"token": "stripe", "company": "Stripe"}
    ]


def test_empty_input_is_empty_list():
    assert parse_greenhouse_boards("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_yaml_gen.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/yaml_gen.py
import datetime as _dt

import yaml

from resume_tailor_harness.setup.state import WizardState


def _header() -> str:
    today = _dt.date.today().isoformat()
    return f"# Generated by 'resume-tailor-harness setup' on {today} — see README for field docs\n"


def parse_greenhouse_boards(text: str) -> list[dict]:
    """One board per line: ``token`` or ``token, Company Name``."""
    boards: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        token, _, company = stripped.partition(",")
        token = token.strip()
        if not token:
            continue
        company = company.strip() or token.title()
        boards.append({"token": token, "company": company})
    return boards
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_yaml_gen.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/yaml_gen.py tests/test_setup_yaml_gen.py
git commit -m "feat(setup): parse_greenhouse_boards pure parser"
```

---

### Task 3: `.env` merge (`env_writer.py`)

**Files:**

- Create: `src/resume_tailor_harness/setup/env_writer.py`
- Test: `tests/test_setup_env_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_env_writer.py
from resume_tailor_harness.setup.env_writer import format_env, merge_env, parse_env


def test_parse_env_ignores_comments_and_blanks():
    assert parse_env("# comment\n\nA=1\nB = two\n") == {"A": "1", "B": "two"}


def test_merge_preserves_unmanaged_keys():
    existing = {"OPENAI_API_KEY": "keep-me", "ANTHROPIC_API_KEY": "old"}
    merged = merge_env(existing, {"ANTHROPIC_API_KEY": "new"})
    assert merged["OPENAI_API_KEY"] == "keep-me"   # untouched
    assert merged["ANTHROPIC_API_KEY"] == "new"     # overwritten


def test_format_quotes_values_with_spaces():
    out = format_env({"A": "no_spaces", "B": "has spaces"})
    assert "A=no_spaces\n" in out
    assert 'B="has spaces"\n' in out


def test_round_trip_parse_format():
    data = {"A": "1", "B": "two words"}
    assert parse_env(format_env(data)) == {"A": "1", "B": "two words"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_env_writer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/env_writer.py
"""Pure .env read/merge/format. The actual file write lives in writer.py."""


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def merge_env(existing: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Overwrite managed keys; never drop an unmanaged key."""
    merged = dict(existing)
    merged.update(updates)
    return merged


def _fmt_value(value: str) -> str:
    if value == "" or any(c in value for c in " #\"'"):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def format_env(data: dict[str, str]) -> str:
    return "".join(f"{key}={_fmt_value(value)}\n" for key, value in data.items())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_env_writer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/env_writer.py tests/test_setup_env_writer.py
git commit -m "feat(setup): pure .env merge/format"
```

---

### Task 4: `build_profile_sources` + round-trip through `load_yaml`

**Files:**

- Modify: `src/resume_tailor_harness/setup/yaml_gen.py`
- Test: `tests/test_setup_yaml_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_yaml_gen.py  (append)
from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.setup.state import WizardState
from resume_tailor_harness.setup.yaml_gen import build_profile_sources


def test_build_profile_sources_round_trips(tmp_path):
    state = WizardState(resume_path="resume.pdf", github_username="octocat")
    text = build_profile_sources(state)
    assert text.startswith("# Generated by 'resume-tailor-harness setup'")
    p = tmp_path / "profile_sources.yaml"
    p.write_text(text, encoding="utf-8")
    data = load_yaml(p)
    assert data["resume_path"] == "resume.pdf"
    assert data["github_username"] == "octocat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_profile_sources_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'build_profile_sources'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/yaml_gen.py  (append)
def build_profile_sources(state: WizardState) -> str:
    data = {
        "resume_path": state.resume_path,
        "github_username": state.github_username,
    }
    return _header() + yaml.safe_dump(data, sort_keys=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_profile_sources_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/yaml_gen.py tests/test_setup_yaml_gen.py
git commit -m "feat(setup): build_profile_sources + round-trip"
```

---

### Task 5: `build_search` + round-trip through `load_search_config`

**Files:**

- Modify: `src/resume_tailor_harness/setup/yaml_gen.py`
- Test: `tests/test_setup_yaml_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_yaml_gen.py  (append)
from resume_tailor_harness.discovery.search_config import load_search_config
from resume_tailor_harness.setup.yaml_gen import build_search


def test_build_search_round_trips(tmp_path):
    state = WizardState(
        keywords=["python"], titles=["Backend Engineer"], locations=["Remote"],
        remote_policy="remote", min_salary=120000, yoe_min=0, yoe_max=5,
        sponsorship_required=True,
    )
    p = tmp_path / "search.yaml"
    p.write_text(build_search(state), encoding="utf-8")
    cfg = load_search_config(p)
    assert cfg.keywords == ["python"]
    assert cfg.min_salary == 120000
    assert cfg.sponsorship_required is True
    assert cfg.remote_policy == "remote"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_search_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'build_search'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/yaml_gen.py  (append)
def build_search(state: WizardState) -> str:
    data = {
        "keywords": state.keywords,
        "titles": state.titles,
        "locations": state.locations,
        "remote_policy": state.remote_policy,
        "min_salary": state.min_salary,
        "yoe_min": state.yoe_min,
        "yoe_max": state.yoe_max,
        "sponsorship_required": state.sponsorship_required,
    }
    return _header() + yaml.safe_dump(data, sort_keys=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_search_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/yaml_gen.py tests/test_setup_yaml_gen.py
git commit -m "feat(setup): build_search + round-trip"
```

---

### Task 6: `build_connectors` + round-trip through `load_connectors_config`

**Files:**

- Modify: `src/resume_tailor_harness/setup/yaml_gen.py`
- Test: `tests/test_setup_yaml_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_yaml_gen.py  (append)
from resume_tailor_harness.discovery.connectors.config import load_connectors_config
from resume_tailor_harness.setup.yaml_gen import build_connectors


def test_build_connectors_round_trips(tmp_path):
    state = WizardState(
        greenhouse_enabled=True,
        greenhouse_boards=[{"token": "stripe", "company": "Stripe"}],
        adzuna_enabled=True, adzuna_country="gb",
        remoteok_enabled=True, linkedin_enabled=False,
    )
    p = tmp_path / "connectors.yaml"
    p.write_text(build_connectors(state), encoding="utf-8")
    cfg = load_connectors_config(p)
    assert cfg.greenhouse.enabled is True
    assert cfg.greenhouse.boards[0].token == "stripe"
    assert cfg.greenhouse.boards[0].company == "Stripe"
    assert cfg.adzuna.country == "gb"
    assert cfg.remoteok.enabled is True
    assert cfg.linkedin.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_connectors_round_trips -v`
Expected: FAIL with `ImportError: cannot import name 'build_connectors'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/yaml_gen.py  (append)
def build_connectors(state: WizardState) -> str:
    data = {
        "greenhouse": {"enabled": state.greenhouse_enabled, "boards": state.greenhouse_boards},
        "adzuna": {"enabled": state.adzuna_enabled, "country": state.adzuna_country},
        "remoteok": {"enabled": state.remoteok_enabled},
        "linkedin": {"enabled": state.linkedin_enabled},
    }
    return _header() + yaml.safe_dump(data, sort_keys=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_yaml_gen.py::test_build_connectors_round_trips -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/yaml_gen.py tests/test_setup_yaml_gen.py
git commit -m "feat(setup): build_connectors + round-trip"
```

---

### Task 7: `render_from_example` for review/render (copy maintained defaults)

review.yaml and render.yaml take no wizard input, so they are generated by copying the maintained `.example` (the single source of the default roster) with a provenance header — verified by round-tripping through the real loaders.

**Files:**

- Modify: `src/resume_tailor_harness/setup/yaml_gen.py`
- Test: `tests/test_setup_yaml_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_yaml_gen.py  (append)
from resume_tailor_harness.render.render_config import load_render_config
from resume_tailor_harness.setup.yaml_gen import render_from_example
from resume_tailor_harness.tailor.review_config import load_review_config


def test_render_from_example_review_round_trips(tmp_path):
    text = render_from_example("config/review.yaml.example")
    assert text.startswith("# Generated by 'resume-tailor-harness setup'")
    p = tmp_path / "review.yaml"
    p.write_text(text, encoding="utf-8")
    cfg = load_review_config(p)
    assert [r.name for r in cfg.reviewers] == [
        "fact-check", "ats-keyword", "recruiter", "hiring-manager", "concision"
    ]
    assert cfg.max_rounds == 3


def test_render_from_example_render_round_trips(tmp_path):
    p = tmp_path / "render.yaml"
    p.write_text(render_from_example("config/render.yaml.example"), encoding="utf-8")
    cfg = load_render_config(p)
    assert cfg.template_path == "templates/resume.typ"
    assert cfg.output_dir == "output"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_yaml_gen.py -k render_from_example -v`
Expected: FAIL with `ImportError: cannot import name 'render_from_example'`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/yaml_gen.py  (append)
from pathlib import Path


def render_from_example(example_path: str | Path) -> str:
    """Return the maintained .example content with a provenance header prepended."""
    body = Path(example_path).read_text(encoding="utf-8")
    return _header() + body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_yaml_gen.py -k render_from_example -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/yaml_gen.py tests/test_setup_yaml_gen.py
git commit -m "feat(setup): render review/render configs from maintained examples"
```

---

### Task 8: Preflight checks (`preflight.py`)

**Files:**

- Create: `src/resume_tailor_harness/setup/preflight.py`
- Test: `tests/test_setup_preflight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_preflight.py
from resume_tailor_harness.setup.preflight import (
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
    for name in ("search.yaml.example", "connectors.yaml.example",
                 "profile_sources.yaml.example", "review.yaml.example", "render.yaml.example"):
        (tmp_path / "config" / name).write_text("x", encoding="utf-8")
    assert check_examples_present(root=tmp_path).ok is True
    (tmp_path / "config" / "search.yaml.example").unlink()
    assert check_examples_present(root=tmp_path).ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_preflight.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/preflight.py
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_EXAMPLES = (
    "search.yaml.example",
    "connectors.yaml.example",
    "profile_sources.yaml.example",
    "review.yaml.example",
    "render.yaml.example",
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    remedy: str = ""


def check_python(version: tuple[int, int, int] | None = None) -> CheckResult:
    major, minor, *_ = version or sys.version_info
    ok = (major, minor) >= (3, 13)
    return CheckResult(
        "python",
        ok,
        f"Python {major}.{minor}",
        remedy="" if ok else "Install Python 3.13+ (this project requires it).",
    )


def check_uv(which: Callable[[str], str | None] = shutil.which) -> CheckResult:
    found = which("uv") is not None
    return CheckResult(
        "uv",
        found,
        "uv found" if found else "uv not found",
        remedy="" if found else "Install uv: https://docs.astral.sh/uv/",
    )


def check_chromium(which: Callable[[str], str | None] = shutil.which) -> CheckResult:
    found = which("playwright") is not None
    return CheckResult(
        "chromium",
        found,
        "playwright available" if found else "playwright CLI not found",
        remedy="" if found else "Only needed for LinkedIn scrape: run 'uv run playwright install chromium'.",
    )


def check_examples_present(root: str | Path = ".") -> CheckResult:
    config = Path(root) / "config"
    missing = [name for name in _EXAMPLES if not (config / name).exists()]
    return CheckResult(
        "examples",
        not missing,
        "all example configs present" if not missing else f"missing: {', '.join(missing)}",
        remedy="" if not missing else "Re-clone the repo; config/*.example files are tracked.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_preflight.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/preflight.py tests/test_setup_preflight.py
git commit -m "feat(setup): detect-and-instruct preflight checks"
```

---

### Task 9: Live validation with injected clients (`validate.py`)

**Files:**

- Create: `src/resume_tailor_harness/setup/validate.py`
- Test: `tests/test_setup_validate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_validate.py
from resume_tailor_harness.setup.preflight import CheckResult
from resume_tailor_harness.setup.validate import anthropic_ping, connector_smoke


class _OkClient:
    class models:
        @staticmethod
        def list():
            return ["ok"]


def test_anthropic_ping_success_with_injected_factory():
    r = anthropic_ping("sk-test", client_factory=lambda key: _OkClient())
    assert isinstance(r, CheckResult)
    assert r.ok is True


def test_anthropic_ping_failure_is_captured_not_raised():
    def boom(key):
        raise RuntimeError("401 unauthorized")
    r = anthropic_ping("bad", client_factory=boom)
    assert r.ok is False
    assert "401" in r.detail


def test_connector_smoke_reports_per_connector():
    def probe(name):
        if name == "adzuna":
            raise RuntimeError("missing keys")
    results = connector_smoke(["remoteok", "adzuna"], probe=probe)
    by_name = {r.name: r.ok for r in results}
    assert by_name == {"remoteok": True, "adzuna": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_validate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/validate.py
from typing import Callable

from resume_tailor_harness.setup.preflight import CheckResult


def _default_anthropic_client(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def anthropic_ping(
    api_key: str,
    client_factory: Callable[[str], object] = _default_anthropic_client,
) -> CheckResult:
    """Confirm the key is accepted via a cheap models.list() call. Never raises."""
    try:
        client = client_factory(api_key)
        client.models.list()  # type: ignore[attr-defined]
        return CheckResult("anthropic", True, "Key accepted.")
    except Exception as exc:  # noqa: BLE001 — surface any failure as a CheckResult
        return CheckResult("anthropic", False, str(exc), remedy="Check ANTHROPIC_API_KEY in .env.")


def connector_smoke(enabled: list[str], probe: Callable[[str], None]) -> list[CheckResult]:
    """Run ``probe(name)`` per enabled connector; capture failures as results."""
    results: list[CheckResult] = []
    for name in enabled:
        try:
            probe(name)
            results.append(CheckResult(name, True, "Reachable."))
        except Exception as exc:  # noqa: BLE001
            results.append(CheckResult(name, False, str(exc)))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_validate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/validate.py tests/test_setup_validate.py
git commit -m "feat(setup): anthropic_ping + connector_smoke with injected clients"
```

---

### Task 10: Atomic write-all + existing-state pre-fill (`writer.py`)

**Files:**

- Create: `src/resume_tailor_harness/setup/writer.py`
- Test: `tests/test_setup_writer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_writer.py
import os

import pytest

from resume_tailor_harness.discovery.search_config import load_search_config
from resume_tailor_harness.setup.state import WizardState
from resume_tailor_harness.setup.writer import atomic_write_all


def _seed_examples(root):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "review.yaml.example").write_text(
        "max_rounds: 3\nscore_threshold: 85\nreviewers: []\n", encoding="utf-8"
    )
    (root / "config" / "render.yaml.example").write_text(
        "template_path: templates/resume.typ\noutput_dir: output\n", encoding="utf-8"
    )


def test_atomic_write_all_writes_every_file(tmp_path):
    _seed_examples(tmp_path)
    state = WizardState(anthropic_api_key="sk-test", keywords=["python"], remote_policy="remote")
    report = atomic_write_all(state, root=tmp_path)

    assert (tmp_path / ".env").exists()
    assert (tmp_path / "config" / "search.yaml").exists()
    cfg = load_search_config(tmp_path / "config" / "search.yaml")
    assert cfg.keywords == ["python"]
    assert all(status == "written" for status in report.values())
    # no temp litter
    assert not list(tmp_path.rglob("*.tmp"))


def test_partial_failure_leaves_no_tmp_litter(tmp_path, monkeypatch):
    _seed_examples(tmp_path)
    state = WizardState(anthropic_api_key="sk-test")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:                     # fail on the 2nd file
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr("resume_tailor_harness.setup.writer.os.replace", flaky_replace)
    report = atomic_write_all(state, root=tmp_path)

    assert any(status.startswith("error") for status in report.values())
    assert not list(tmp_path.rglob("*.tmp"))     # tmp cleaned up even on failure
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_writer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# src/resume_tailor_harness/setup/writer.py
import os
from pathlib import Path

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.discovery.connectors.config import load_connectors_config
from resume_tailor_harness.discovery.search_config import load_search_config
from resume_tailor_harness.setup.env_writer import format_env, merge_env, parse_env
from resume_tailor_harness.setup.state import WizardState
from resume_tailor_harness.setup.yaml_gen import (
    build_connectors,
    build_profile_sources,
    build_search,
    render_from_example,
)


def _atomic_write(path: Path, content: str) -> str:
    """Write ``content`` to ``path`` atomically. Returns 'written' or 'error: ...'."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        return "written"
    except OSError as exc:
        if tmp.exists():
            tmp.unlink()
        return f"error: {exc}"


def _env_content(state: WizardState, root: Path) -> str:
    env_path = root / ".env"
    existing = parse_env(env_path.read_text(encoding="utf-8")) if env_path.exists() else {}
    return format_env(merge_env(existing, state.managed_env()))


def atomic_write_all(state: WizardState, root: str | Path = ".") -> dict[str, str]:
    """Write .env + the five config files, each atomically. Returns per-file status."""
    root = Path(root)
    plan: dict[Path, str] = {
        root / ".env": _env_content(state, root),
        root / "config" / "profile_sources.yaml": build_profile_sources(state),
        root / "config" / "search.yaml": build_search(state),
        root / "config" / "connectors.yaml": build_connectors(state),
        root / "config" / "review.yaml": render_from_example(root / "config" / "review.yaml.example"),
        root / "config" / "render.yaml": render_from_example(root / "config" / "render.yaml.example"),
    }
    return {str(path): _atomic_write(path, content) for path, content in plan.items()}


def load_existing_state(root: str | Path = ".") -> WizardState:
    """Pre-fill a WizardState from any config that already exists (re-run safety)."""
    root = Path(root)
    state = WizardState()

    env_path = root / ".env"
    if env_path.exists():
        env = parse_env(env_path.read_text(encoding="utf-8"))
        state.anthropic_api_key = env.get("ANTHROPIC_API_KEY", "")
        state.github_token = env.get("GITHUB_TOKEN", "")
        state.adzuna_app_id = env.get("ADZUNA_APP_ID", "")
        state.adzuna_app_key = env.get("ADZUNA_APP_KEY", "")
        state.linkedin_email = env.get("LINKEDIN_EMAIL", "")
        state.linkedin_password = env.get("LINKEDIN_PASSWORD", "")
        state.db_url = env.get("DB_URL", state.db_url)

    sources = root / "config" / "profile_sources.yaml"
    if sources.exists():
        data = load_yaml(sources)
        state.resume_path = data.get("resume_path", "")
        state.github_username = data.get("github_username", "")

    search = root / "config" / "search.yaml"
    if search.exists():
        cfg = load_search_config(search)
        state.keywords = cfg.keywords
        state.titles = cfg.titles
        state.locations = cfg.locations
        state.remote_policy = cfg.remote_policy or "any"
        state.min_salary = cfg.min_salary
        state.yoe_min = cfg.yoe_min
        state.yoe_max = cfg.yoe_max
        state.sponsorship_required = cfg.sponsorship_required

    connectors = root / "config" / "connectors.yaml"
    if connectors.exists():
        cfg = load_connectors_config(connectors)
        state.greenhouse_enabled = cfg.greenhouse.enabled
        state.greenhouse_boards = [
            {"token": b.token, "company": b.company or b.token} for b in cfg.greenhouse.boards
        ]
        state.adzuna_enabled = cfg.adzuna.enabled
        state.adzuna_country = cfg.adzuna.country
        state.remoteok_enabled = cfg.remoteok.enabled
        state.linkedin_enabled = cfg.linkedin.enabled

    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_writer.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add a pre-fill round-trip test**

```python
# tests/test_setup_writer.py  (append)
from resume_tailor_harness.setup.writer import load_existing_state


def test_load_existing_state_round_trips_what_was_written(tmp_path):
    _seed_examples(tmp_path)
    written = WizardState(
        anthropic_api_key="sk-rt", keywords=["go"], remote_policy="hybrid",
        greenhouse_enabled=True, greenhouse_boards=[{"token": "stripe", "company": "Stripe"}],
    )
    atomic_write_all(written, root=tmp_path)
    reloaded = load_existing_state(root=tmp_path)
    assert reloaded.anthropic_api_key == "sk-rt"
    assert reloaded.keywords == ["go"]
    assert reloaded.remote_policy == "hybrid"
    assert reloaded.greenhouse_enabled is True
    assert reloaded.greenhouse_boards == [{"token": "stripe", "company": "Stripe"}]
```

- [ ] **Step 6: Run the new test**

Run: `uv run pytest tests/test_setup_writer.py::test_load_existing_state_round_trips_what_was_written -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/setup/writer.py tests/test_setup_writer.py
git commit -m "feat(setup): atomic_write_all + load_existing_state pre-fill"
```

---

### Task 11: Thin Textual shell (`app.py`)

The full screen-by-screen UI follows the screen table in the spec (§5.2). This task builds the **thin testable shell**: a `SetupApp` that holds a `WizardState`, accepts an injected `writer`, exposes a `_perform_write()` seam, and boots cleanly. The engineer fleshes out the per-screen widgets following the spec table; the pilot tests below guard the wiring.

**Files:**

- Create: `src/resume_tailor_harness/setup/app.py`
- Test: `tests/test_setup_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_app.py
import pytest

from resume_tailor_harness.setup.app import SetupApp
from resume_tailor_harness.setup.state import WizardState


def test_perform_write_calls_injected_writer():
    calls = {}

    def fake_writer(state, root="."):
        calls["state"] = state
        return {"/x/.env": "written"}

    app = SetupApp(state=WizardState(anthropic_api_key="sk-x"), writer=fake_writer)
    report = app._perform_write()
    assert report == {"/x/.env": "written"}
    assert calls["state"].anthropic_api_key == "sk-x"


@pytest.mark.asyncio
async def test_app_boots_without_error():
    app = SetupApp(state=WizardState(), writer=lambda s, root=".": {})
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_running
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_setup_app.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the minimal shell**

```python
# src/resume_tailor_harness/setup/app.py
"""Thin Textual shell for the setup wizard.

The pure cores (state, yaml_gen, env_writer, preflight, validate, writer) hold
all logic. This App binds screens to a single WizardState and delegates writing
to an injected callable so the wiring is testable without a terminal.

Screen build-out follows the spec table (§5.2): Welcome/preflight, Secrets,
Profile sources, Search, Connectors, Confirm+write, Build profile, Handoff.
"""

from typing import Callable

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from resume_tailor_harness.setup.state import WizardState
from resume_tailor_harness.setup.writer import atomic_write_all


class SetupApp(App):
    """Wizard application. ``writer`` is injected for testability."""

    TITLE = "Résumé Tailor Harness — Setup"

    def __init__(
        self,
        state: WizardState | None = None,
        writer: Callable[..., dict[str, str]] = atomic_write_all,
        root: str = ".",
    ) -> None:
        super().__init__()
        self.state = state or WizardState()
        self.writer = writer
        self.root = root
        self.write_report: dict[str, str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Welcome to Résumé Tailor Harness setup.\n"
            "Press Ctrl+Q to quit. (Screens build out per spec §5.2.)",
            id="welcome",
        )
        yield Footer()

    def _perform_write(self) -> dict[str, str]:
        """Write all config from the current state. The atomic-at-end seam."""
        self.write_report = self.writer(self.state, root=self.root)
        return self.write_report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_setup_app.py -v`
Expected: PASS (2 tests).
Note: if `test_app_boots_without_error` errors on the `asyncio` marker, add `pytest-asyncio` (`uv add --dev pytest-asyncio`) and set `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `pyproject.toml`, then re-run.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/setup/app.py tests/test_setup_app.py pyproject.toml uv.lock
git commit -m "feat(setup): thin Textual shell + write seam"
```

---

### Task 12: `setup` CLI command

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_setup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_setup.py
from typer.testing import CliRunner

import resume_tailor_harness.cli as cli_mod
from resume_tailor_harness.cli import app

runner = CliRunner()


def test_setup_command_launches_app(monkeypatch):
    launched = {"ran": False}

    class FakeApp:
        def __init__(self, *a, **k):
            pass

        def run(self):
            launched["ran"] = True

    monkeypatch.setattr("resume_tailor_harness.setup.app.SetupApp", FakeApp)
    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 0
    assert launched["ran"] is True


def test_setup_is_a_registered_command():
    result = runner.invoke(app, ["--help"])
    assert "setup" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: FAIL — `setup` not a registered command (exit code != 0 / not in help).

- [ ] **Step 3: Add the command to `cli.py`**

Append after the `dashboard_cmd` definition (near `cli.py:366`):

```python
@app.command("setup")
def setup_cmd() -> None:
    """Launch the interactive setup wizard (zero → configured → ready)."""
    from resume_tailor_harness.setup.app import SetupApp

    SetupApp().run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_setup.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_setup.py
git commit -m "feat(cli): add 'setup' command launching the wizard"
```

---

### Task 13: README pointer + full-suite green

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Add the setup-wizard line**

In `README.md`, in the **Setup** section, immediately after step 1 (`uv sync`), insert:

```markdown
# 1a. (Recommended) Run the guided setup wizard instead of hand-editing config

uv run resume-tailor-harness setup
```

And add a one-line note under the section: _"`resume-tailor-harness setup` walks you through secrets, search criteria, and connectors, then writes `.env` and `config/_.yaml` for you — the manual steps below are the alternative."\*

- [ ] **Step 2: Run the full suite + lint**

Run: `uv run pytest -q`
Expected: PASS (all existing tests + the new `test_setup_*` and `test_cli_setup`).

Run: `uv run ruff check src/resume_tailor_harness/setup src/resume_tailor_harness/cli.py`
Expected: clean.

- [ ] **Step 3: Manual smoke (optional but recommended)**

Run: `uv run resume-tailor-harness setup`
Expected: the Textual welcome screen renders; Ctrl+Q quits cleanly. (No config is written from the skeleton welcome screen until the engineer wires the Confirm screen to `_perform_write`.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(setup): point new users at 'resume-tailor-harness setup'"
```

---

## Self-Review

**Spec coverage (§5):**

- §5.1 package layout → Tasks 1–11 create exactly the listed modules. ✓
- §5.2 screen flow → Task 11 builds the thin shell + write seam; per-screen widgets are explicitly delegated to the engineer following the spec table (the logic each screen calls is fully built and tested in Tasks 2–10). ✓
- §5.3 secrets model (6 prompted / 4 advanced / 2 omitted; `merge_env` preserves unmanaged) → Tasks 1 (`managed_env` omits openai/user_data_dir) + 3 (`merge_env` preserves unmanaged, tested with `OPENAI_API_KEY`). ✓
- §5.4 config generation (clean YAML + header; greenhouse parser; round-trip through real loaders) → Tasks 2, 4, 5, 6, 7 (every builder round-trips through its real loader). ✓
- §5.5 atomic write protocol (temp + `os.replace`, per-file, no litter) → Task 10 (incl. the mid-write-failure/no-tmp-litter test). ✓
- §5.6 re-run pre-fill → Task 10 (`load_existing_state` + round-trip test). ✓
- §5.7 process/freshness (in-memory secrets pre-write; subprocess profile build) → Task 9 (`anthropic_ping(api_key)` takes the key directly, never `get_settings`); the subprocess `profile build` is the engineer's Confirm/Build-screen wiring noted in Task 11 (calls `resume-tailor-harness profile build` via `subprocess`, mirroring `dashboard_cmd`). ✓
- §6 testing rings → Ring 1 (Tasks 1–8, 10), Ring 2 (Task 9), Ring 3 (Task 11 pilot + Task 10 failure test). ✓
- §7 files touched / §2 decision 14 (`textual` hard dep, preflight detect-only) → Tasks 1, 8, 12, 13. ✓

**Placeholder scan:** No "TBD"/"add error handling"/"handle edge cases". The one delegation — per-screen Textual widgets in Task 11 — is explicit and bounded (the spec table is the contract, and every function those screens call is fully implemented and tested in earlier tasks), not a hidden gap.

**Type consistency:** `WizardState` field names are used identically across `managed_env`, `build_*`, `atomic_write_all`, and `load_existing_state`. `CheckResult` is defined once in `preflight.py` and imported by `validate.py` (same shape everywhere). `atomic_write_all(state, root=...)` signature matches its call sites in tests and the `_perform_write` seam. `anthropic_ping(api_key, client_factory=...)` and `connector_smoke(enabled, probe)` signatures match their tests.

```

```
