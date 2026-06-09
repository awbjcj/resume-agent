# Resume Agent — Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `profile` component and a `resume-agent profile build` CLI command that turns your existing resume file + GitHub profile into `data/profile/facts.json` — the human-editable, authoritative fact-lock that all downstream tailoring draws from.

**Architecture:** Deterministic I/O (resume text extraction, GitHub REST fetch, JSON store, merge) is separated from the single LLM step (resume-text → `ProfileFacts` via an Agno agent on the cheap model). Every unit takes its collaborators as parameters so it can be tested with fakes/fixtures — no network or API key needed in tests.

**Tech Stack:** Python 3.13, uv, Pydantic v2, Agno (`Agent` + `Claude`), Anthropic, httpx, pypdf, python-docx, Typer, pytest.

**Depends on:** the Foundation plan (`resume_agent.models.profile.ProfileFacts` etc., `resume_agent.config`). Foundation is merged to `main` and green (31 tests).

> **Commit convention:** every commit ends with the trailer via a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec: `docs/superpowers/specs/2026-06-08-resume-agent-design.md` §5.1.

Plan-author decisions (documented; override if undesired):
- **GitHub client uses `httpx` raw REST**, not PyGithub — testable against `httpx.MockTransport` fixtures with no network.
- **GitHub ingest is deterministic in v1.** GitHub repo metadata (description, topics, languages, stars) already maps cleanly to `Project` facts. Per-README LLM summarization is deferred to v2.
- **The only LLM call** is resume-text → `ProfileFacts` via an Agno `Agent` (cheap model, Claude Haiku, configurable).
- **`facts.json` is protected**: `build` refuses to overwrite an existing file without `--refresh`.

## File Structure (created/modified by this plan)

```
src/resume_agent/
  config.py                 # MODIFY: add cheap_model setting
  cli.py                    # CREATE: Typer app + `profile build`
  profile/
    __init__.py             # CREATE
    resume_reader.py        # CREATE: read_resume_text() for .pdf/.docx/.txt
    github.py               # CREATE: GitHubClient (httpx, injectable)
    extractor.py            # CREATE: Agno agent factory + extract_profile_facts()
    github_ingest.py        # CREATE: deterministic profile/repo -> GitHubProfile + Project[]
    merge.py                # CREATE: merge_facts()
    store.py                # CREATE: save_facts()/load_facts()
    build.py                # CREATE: build_profile() orchestrator
config/
  profile_sources.yaml.example   # CREATE
pyproject.toml              # MODIFY: deps + [project.scripts]
tests/
  test_profile_resume_reader.py
  test_profile_github.py
  test_profile_extractor.py
  test_profile_github_ingest.py
  test_profile_merge.py
  test_profile_store.py
  test_profile_build.py
  test_cli_profile.py
  test_config.py            # MODIFY: add cheap_model assertion
```

---

## Task 1: Dependencies, config, and package scaffold

**Files:**
- Modify: `pyproject.toml`, `src/resume_agent/config.py`, `tests/test_config.py`
- Create: `src/resume_agent/profile/__init__.py`, `config/profile_sources.yaml.example`

- [ ] **Step 1: Add the Profile dependencies**

Run:
```bash
uv add agno anthropic httpx pypdf python-docx typer
```
Expected: these appear in `pyproject.toml` `dependencies`; `uv.lock` updates.

- [ ] **Step 2: Write the failing config test (add to `tests/test_config.py`)**

Append this test to `tests/test_config.py`:
```python
def test_settings_has_cheap_model_default():
    settings = Settings(_env_file=None)
    assert settings.cheap_model == "claude-haiku-4-5-20251001"
```

- [ ] **Step 3: Run it to verify it fails**

Run:
```bash
uv run pytest tests/test_config.py::test_settings_has_cheap_model_default -v
```
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'cheap_model'`.

- [ ] **Step 4: Add the setting**

In `src/resume_agent/config.py`, add this line to the `Settings` class, right after `db_url`:
```python
    cheap_model: str = "claude-haiku-4-5-20251001"
```

- [ ] **Step 5: Create the package + example sources file**

Create `src/resume_agent/profile/__init__.py`:
```python
"""Profile component: build the fact-lock from resume + GitHub."""
```

Create `config/profile_sources.yaml.example`:
```yaml
# Where your ground-truth facts come from (see design spec §5.1).
# Copy to config/profile_sources.yaml and edit.
resume_path: path/to/your_resume.pdf   # .pdf, .docx, or .txt
github_username: your-github-username    # leave blank to skip GitHub
```

- [ ] **Step 6: Run config tests to verify they pass**

Run:
```bash
uv run pytest tests/test_config.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/resume_agent/config.py src/resume_agent/profile/__init__.py config/profile_sources.yaml.example tests/test_config.py
git commit -m "feat(profile): add deps, cheap_model setting, package scaffold" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Resume text reader

**Files:**
- Create: `src/resume_agent/profile/resume_reader.py`
- Test: `tests/test_profile_resume_reader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_resume_reader.py`:
```python
import pytest

from resume_agent.profile.resume_reader import read_resume_text


def test_reads_txt(tmp_path):
    f = tmp_path / "resume.txt"
    f.write_text("Ada Lovelace\nEngineer", encoding="utf-8")
    assert read_resume_text(f) == "Ada Lovelace\nEngineer"


def test_reads_docx(tmp_path):
    from docx import Document

    f = tmp_path / "resume.docx"
    doc = Document()
    doc.add_paragraph("Ada Lovelace")
    doc.add_paragraph("Analytical Engines Ltd")
    doc.save(str(f))

    text = read_resume_text(f)
    assert "Ada Lovelace" in text
    assert "Analytical Engines Ltd" in text


def test_unsupported_format_raises(tmp_path):
    f = tmp_path / "resume.rtf"
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        read_resume_text(f)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_resume_reader.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.resume_reader'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/resume_reader.py`:
```python
from pathlib import Path


def read_resume_text(path: str | Path) -> str:
    """Extract plain text from a .pdf, .docx, or .txt resume."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".txt":
        return p.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix == ".docx":
        return _read_docx(p)
    raise ValueError(f"Unsupported resume format: {suffix or '(none)'} (use .pdf, .docx, or .txt)")


def _read_pdf(p: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(p))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(p: Path) -> str:
    from docx import Document

    doc = Document(str(p))
    return "\n".join(para.text for para in doc.paragraphs)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_resume_reader.py -v
```
Expected: PASS (3 tests). (PDF extraction is exercised manually with a real resume; `.txt`/`.docx` are covered here.)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/resume_reader.py tests/test_profile_resume_reader.py
git commit -m "feat(profile): resume text reader for pdf/docx/txt" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: GitHub client

**Files:**
- Create: `src/resume_agent/profile/github.py`
- Test: `tests/test_profile_github.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_github.py`:
```python
import httpx

from resume_agent.profile.github import GitHubClient


def _client(handler) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.github.com")
    return GitHubClient(token="t", client=http)


def test_fetch_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/ada"
        return httpx.Response(200, json={"login": "ada", "followers": 42, "public_repos": 3})

    gh = _client(handler)
    profile = gh.fetch_profile("ada")
    assert profile["login"] == "ada"
    assert profile["followers"] == 42


def test_fetch_repos():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/ada/repos"
        return httpx.Response(200, json=[{"name": "engine", "stargazers_count": 10}])

    gh = _client(handler)
    repos = gh.fetch_repos("ada")
    assert repos[0]["name"] == "engine"


def test_fetch_readme_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/ada/engine/readme"
        return httpx.Response(200, text="# Engine\nThe first computer.")

    gh = _client(handler)
    assert "first computer" in gh.fetch_readme("ada", "engine")


def test_fetch_readme_missing_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    gh = _client(handler)
    assert gh.fetch_readme("ada", "engine") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_github.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.github'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/github.py`:
```python
import httpx

from resume_agent.config import get_settings

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Thin wrapper over the GitHub REST API. Pass ``client`` to inject a test transport."""

    def __init__(self, token: str | None = None, client: httpx.Client | None = None) -> None:
        self._token = token if token is not None else get_settings().github_token
        if client is not None:
            self._client = client
        else:
            headers = {"Accept": "application/vnd.github+json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.Client(base_url=GITHUB_API, headers=headers, timeout=20.0)

    def fetch_profile(self, username: str) -> dict:
        resp = self._client.get(f"/users/{username}")
        resp.raise_for_status()
        return resp.json()

    def fetch_repos(self, username: str) -> list[dict]:
        resp = self._client.get(
            f"/users/{username}/repos",
            params={"per_page": 100, "sort": "updated"},
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_readme(self, owner: str, repo: str) -> str | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_github.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/github.py tests/test_profile_github.py
git commit -m "feat(profile): httpx-based GitHub REST client" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Resume extractor (Agno agent)

**Files:**
- Create: `src/resume_agent/profile/extractor.py`
- Test: `tests/test_profile_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_extractor.py`:
```python
import pytest

from agno.agent import Agent

from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.extractor import build_extractor_agent, extract_profile_facts


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _FakeResult(self._content)


def test_extract_returns_profilefacts_and_passes_text():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    agent = _FakeAgent(facts)
    result = extract_profile_facts("raw resume text", agent)
    assert result is facts
    assert agent.received == "raw resume text"


def test_extract_rejects_wrong_type():
    agent = _FakeAgent("not a ProfileFacts")
    with pytest.raises(TypeError):
        extract_profile_facts("x", agent)


def test_build_extractor_agent_is_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_extractor_agent(model_id="claude-haiku-4-5-20251001")
    assert isinstance(agent, Agent)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_extractor.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.extractor'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/extractor.py`:
```python
from typing import Any, Protocol

from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.models.profile import ProfileFacts


class Runner(Protocol):
    """Anything with Agno's ``run(prompt) -> result`` shape (result has ``.content``)."""

    def run(self, prompt: str) -> Any: ...


_INSTRUCTIONS = [
    "Extract structured resume facts from the raw resume text provided.",
    "Use ONLY information present in the text. Never invent companies, dates, skills, or numbers.",
    "Leave fields empty or null when the text does not provide them.",
    "Split each role's accomplishments into individual bullet entries.",
]


def build_extractor_agent(model_id: str | None = None) -> Agent:
    """Create the Agno agent that structures resume text into ProfileFacts."""
    resolved = model_id or get_settings().cheap_model
    return Agent(
        model=Claude(id=resolved),
        description="You extract structured, truthful resume facts from raw resume text.",
        instructions=_INSTRUCTIONS,
        output_schema=ProfileFacts,
    )


def extract_profile_facts(resume_text: str, agent: Runner) -> ProfileFacts:
    """Run the agent and return its ProfileFacts, validating the result type."""
    result = agent.run(resume_text)
    facts = result.content
    if not isinstance(facts, ProfileFacts):
        raise TypeError(f"Expected ProfileFacts from agent, got {type(facts).__name__}")
    return facts
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_extractor.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/extractor.py tests/test_profile_extractor.py
git commit -m "feat(profile): Agno agent + resume->ProfileFacts extractor" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: GitHub ingest (deterministic)

**Files:**
- Create: `src/resume_agent/profile/github_ingest.py`
- Test: `tests/test_profile_github_ingest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_github_ingest.py`:
```python
from resume_agent.models.profile import GitHubProfile, Project
from resume_agent.profile.github_ingest import build_github_profile, repo_to_project


def test_build_github_profile_aggregates_signals():
    profile = {"login": "ada", "bio": "math", "followers": 42, "public_repos": 2, "created_at": "2010-01-01T00:00:00Z"}
    repos = [
        {"language": "Python", "stargazers_count": 10},
        {"language": "Python", "stargazers_count": 5},
        {"language": "Rust", "stargazers_count": 1},
    ]
    gh = build_github_profile(profile, repos)
    assert isinstance(gh, GitHubProfile)
    assert gh.username == "ada"
    assert gh.total_stars == 16
    assert gh.top_languages[0] == "Python"
    assert gh.source.value == "github"


def test_repo_to_project_maps_metadata():
    repo = {
        "name": "engine",
        "description": "the first computer",
        "html_url": "https://github.com/ada/engine",
        "homepage": "https://ada.dev",
        "stargazers_count": 10,
        "forks_count": 2,
        "language": "Python",
        "topics": ["compute"],
        "updated_at": "2024-01-01T00:00:00Z",
        "fork": False,
    }
    proj = repo_to_project(repo)
    assert isinstance(proj, Project)
    assert proj.source.value == "github"
    assert proj.name == "engine"
    assert proj.repo_url == "https://github.com/ada/engine"
    assert proj.url == "https://ada.dev"
    assert proj.stars == 10
    assert proj.primary_language == "Python"
    assert proj.topics == ["compute"]
    assert proj.is_fork is False


def test_repo_to_project_falls_back_to_html_url_when_no_homepage():
    repo = {"name": "x", "html_url": "https://github.com/ada/x"}
    proj = repo_to_project(repo)
    assert proj.url == "https://github.com/ada/x"
    assert proj.languages == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_github_ingest.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.github_ingest'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/github_ingest.py`:
```python
from collections import Counter

from resume_agent.models.profile import GitHubProfile, Project


def build_github_profile(profile: dict, repos: list[dict]) -> GitHubProfile:
    """Aggregate a GitHub user profile + repo list into GitHubProfile signals."""
    languages = [r["language"] for r in repos if r.get("language")]
    top_languages = [lang for lang, _ in Counter(languages).most_common(5)]
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    return GitHubProfile(
        username=profile.get("login"),
        bio=profile.get("bio"),
        followers=profile.get("followers"),
        public_repos=profile.get("public_repos"),
        account_created_at=profile.get("created_at"),
        top_languages=top_languages,
        total_stars=total_stars,
    )


def repo_to_project(repo: dict) -> Project:
    """Map a single GitHub repo dict into a Project fact (source=github)."""
    language = repo.get("language")
    return Project(
        source="github",
        name=repo["name"],
        description=repo.get("description"),
        url=repo.get("homepage") or repo.get("html_url"),
        repo_url=repo.get("html_url"),
        stars=repo.get("stargazers_count"),
        forks=repo.get("forks_count"),
        primary_language=language,
        languages=[language] if language else [],
        topics=repo.get("topics", []),
        homepage_url=repo.get("homepage"),
        last_updated=repo.get("updated_at"),
        is_fork=repo.get("fork"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_github_ingest.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/github_ingest.py tests/test_profile_github_ingest.py
git commit -m "feat(profile): deterministic GitHub profile/repo ingest" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Merge

**Files:**
- Create: `src/resume_agent/profile/merge.py`
- Test: `tests/test_profile_merge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_merge.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_merge.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.merge'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/merge.py`:
```python
from resume_agent.models.profile import GitHubProfile, ProfileFacts, Project


def merge_facts(
    resume_facts: ProfileFacts,
    github_projects: list[Project] | None = None,
    github_profile: GitHubProfile | None = None,
) -> ProfileFacts:
    """Combine resume-derived facts with GitHub-derived facts into one ProfileFacts.

    Returns a copy; the resume facts are not mutated. GitHub projects are appended
    after resume projects (no dedup in v1 — the human edits facts.json).
    """
    merged = resume_facts.model_copy(deep=True)
    if github_projects:
        merged.projects = [*merged.projects, *github_projects]
    if github_profile is not None:
        merged.github_profile = github_profile
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_merge.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/merge.py tests/test_profile_merge.py
git commit -m "feat(profile): merge resume + GitHub facts" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Store (facts.json)

**Files:**
- Create: `src/resume_agent/profile/store.py`
- Test: `tests/test_profile_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_store.py`:
```python
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts, save_facts


def test_save_creates_parent_dirs_and_round_trips(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    out = tmp_path / "nested" / "facts.json"

    saved_path = save_facts(facts, out)
    assert saved_path.exists()

    loaded = load_facts(out)
    assert loaded.contact.name == "Ada Lovelace"


def test_saved_json_is_human_readable(tmp_path):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    out = tmp_path / "facts.json"
    save_facts(facts, out)
    text = out.read_text(encoding="utf-8")
    assert "\n" in text  # indented, not a single line
    assert "Ada" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_store.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.store'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/store.py`:
```python
from pathlib import Path

from resume_agent.models.profile import ProfileFacts


def save_facts(facts: ProfileFacts, path: str | Path) -> Path:
    """Write ProfileFacts to an indented JSON file, creating parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_facts(path: str | Path) -> ProfileFacts:
    """Read ProfileFacts from a JSON file."""
    return ProfileFacts.model_validate_json(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_store.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/store.py tests/test_profile_store.py
git commit -m "feat(profile): facts.json save/load" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Build orchestrator

**Files:**
- Create: `src/resume_agent/profile/build.py`
- Test: `tests/test_profile_build.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_build.py`:
```python
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

    facts = build_profile(
        resume_path=resume,
        github_username="ada",
        extractor_agent=_FakeAgent(extracted),
        github_client=_FakeGitHub(),
    )

    assert facts.contact.name == "Ada Lovelace"
    assert facts.github_profile.username == "ada"
    assert [p.name for p in facts.projects] == ["engine"]


def test_build_profile_skips_github_when_no_username(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada", encoding="utf-8")
    facts = build_profile(
        resume_path=resume,
        github_username="",
        extractor_agent=_FakeAgent(ProfileFacts(contact=Contact(name="Ada"))),
        github_client=_FakeGitHub(),
    )
    assert facts.github_profile is None
    assert facts.projects == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_profile_build.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.build'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/build.py`:
```python
from pathlib import Path

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.extractor import build_extractor_agent, extract_profile_facts
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_ingest import build_github_profile, repo_to_project
from resume_agent.profile.merge import merge_facts
from resume_agent.profile.resume_reader import read_resume_text


def build_profile(
    resume_path: str | Path,
    github_username: str | None,
    extractor_agent=None,
    github_client=None,
) -> ProfileFacts:
    """Build a merged ProfileFacts from a resume file and (optionally) GitHub.

    ``extractor_agent`` and ``github_client`` are injectable for testing; in
    normal use they default to the real Agno agent and GitHub REST client.
    """
    text = read_resume_text(resume_path)
    agent = extractor_agent if extractor_agent is not None else build_extractor_agent()
    resume_facts = extract_profile_facts(text, agent)

    if not github_username:
        return merge_facts(resume_facts)

    gh = github_client if github_client is not None else GitHubClient()
    profile_data = gh.fetch_profile(github_username)
    repos = gh.fetch_repos(github_username)
    gh_profile = build_github_profile(profile_data, repos)
    projects = [repo_to_project(repo) for repo in repos]
    return merge_facts(resume_facts, github_projects=projects, github_profile=gh_profile)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_profile_build.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/build.py tests/test_profile_build.py
git commit -m "feat(profile): build_profile orchestrator" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: CLI — `resume-agent profile build`

**Files:**
- Create: `src/resume_agent/cli.py`
- Modify: `pyproject.toml` (add `[project.scripts]`)
- Test: `tests/test_cli_profile.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_profile.py`:
```python
from typer.testing import CliRunner

from resume_agent.models.profile import Contact, Project, ProfileFacts
from resume_agent import cli

runner = CliRunner()


def _write_sources(tmp_path):
    sources = tmp_path / "profile_sources.yaml"
    sources.write_text("resume_path: r.txt\ngithub_username: ada\n", encoding="utf-8")
    return sources


def test_profile_build_writes_facts(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"), projects=[Project(name="engine")])
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: facts)

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"

    result = runner.invoke(cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "engine" in out.read_text(encoding="utf-8")


def test_profile_build_refuses_to_overwrite_without_refresh(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: facts)

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"
    out.write_text("{}", encoding="utf-8")  # pre-existing (simulating manual edits)

    result = runner.invoke(cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out)])

    assert result.exit_code == 1
    assert out.read_text(encoding="utf-8") == "{}"  # not clobbered


def test_profile_build_refresh_overwrites(tmp_path, monkeypatch):
    facts = ProfileFacts(contact=Contact(name="Ada"))
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: facts)

    sources = _write_sources(tmp_path)
    out = tmp_path / "facts.json"
    out.write_text("{}", encoding="utf-8")

    result = runner.invoke(
        cli.app, ["profile", "build", "--sources", str(sources), "--out", str(out), "--refresh"]
    )

    assert result.exit_code == 0, result.output
    assert "Ada" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
uv run pytest tests/test_cli_profile.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.cli'`.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/cli.py`:
```python
from pathlib import Path

import typer

from resume_agent.config import load_yaml
from resume_agent.profile.build import build_profile
from resume_agent.profile.store import save_facts

app = typer.Typer(help="Resume Agent — personal job-hunt automation pipeline.")
profile_app = typer.Typer(help="Build and manage your fact-lock profile.")
app.add_typer(profile_app, name="profile")

DEFAULT_SOURCES = "config/profile_sources.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


@profile_app.command("build")
def profile_build(
    sources: str = typer.Option(DEFAULT_SOURCES, help="Path to profile_sources.yaml."),
    out: str = typer.Option(DEFAULT_FACTS, help="Where to write facts.json."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Overwrite an existing facts.json (discards manual edits)."
    ),
) -> None:
    """Build facts.json from your resume + GitHub."""
    if Path(out).exists() and not refresh:
        typer.echo(f"{out} already exists. Use --refresh to rebuild (this discards manual edits).")
        raise typer.Exit(code=1)

    cfg = load_yaml(sources)
    facts = build_profile(
        resume_path=cfg.get("resume_path"),
        github_username=cfg.get("github_username"),
    )
    path = save_facts(facts, out)
    typer.echo(
        f"Wrote {len(facts.experience)} experiences and {len(facts.projects)} projects to {path}"
    )


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
uv run pytest tests/test_cli_profile.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Register the console script**

In `pyproject.toml`, add this block (after `[project]`/dependencies, near the other tool blocks):
```toml
[project.scripts]
resume-agent = "resume_agent.cli:app"
```

- [ ] **Step 6: Verify the CLI is wired**

Run:
```bash
uv run resume-agent profile build --help
```
Expected: help text for the `profile build` command (exit 0).

- [ ] **Step 7: Run the full suite**

Run:
```bash
uv run pytest -q
```
Expected: all tests pass (Foundation 31 + Profile additions).

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/cli.py pyproject.toml tests/test_cli_profile.py
git commit -m "feat(profile): profile build CLI with overwrite protection" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.1):** resume parse (Task 2) + Agno-agent structuring to full `ProfileFacts` (Task 4); GitHub ingest of profile signals + all repos with metadata (Task 5); merge into one fact-lock (Task 6); human-editable `facts.json` output (Task 7); one-time/`--refresh` `profile build` (Task 9). The "every fact carries id/source" + extensibility requirements are satisfied by the Foundation models reused here. **Deviation from spec:** per-README LLM summarization is deferred to v2 (deterministic GitHub metadata used instead) — documented above and to be added to the roadmap memo.
- **Placeholder scan:** none — every step has complete code and exact commands.
- **Type consistency:** `extract_profile_facts(text, agent) -> ProfileFacts`; `build_github_profile(profile, repos) -> GitHubProfile`; `repo_to_project(repo) -> Project`; `merge_facts(resume_facts, github_projects=None, github_profile=None) -> ProfileFacts`; `build_profile(resume_path, github_username, extractor_agent=None, github_client=None)` — keyword names match the CLI call and the tests. `GitHubClient` and the `_FakeGitHub` test double share the `fetch_profile`/`fetch_repos` method names. `save_facts`/`load_facts` paired in Task 7.
- **Test isolation:** no test hits the network or needs an API key — the Agno agent and GitHub client are injected as fakes; `build_extractor_agent` construction test only sets a dummy env var.

---

## Notes to carry into later plans
- **Tracking plan:** add `updated_at` auto-update (`onupdate`) and decide tz-aware vs naive datetime storage for the SQLModel tables (deferred from the Foundation review).
- **v2 roadmap:** per-README LLM summarization in GitHub ingest; resume-projects vs GitHub-projects dedup in `merge_facts`.

## Execution Handoff
After this plan is executed and green, the next plan is **Discovery** (LinkedIn scrape → clean → extract → filter → fit-score → shortlist).
