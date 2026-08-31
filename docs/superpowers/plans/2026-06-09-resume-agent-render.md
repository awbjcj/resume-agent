# Résumé Tailor Harness — Render (Typst → PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a stored `ResumeContent` (the latest passing `resume_versions.content_json`) into a single-column, ATS-parseable **PDF** via a Typst template, store the file path on the resume version, and move the job to `rendered` — all deterministically, with **no LLM call**.

**Architecture:** A Typst template (`templates/resume.typ`) receives the resume as a JSON string through `sys.inputs.data` and decodes it with `json(bytes(...))`. The Python `typst` package (a bundled compiler — no external install) compiles it. As everywhere else in this codebase, the side-effecting compile step is injected (`render_fn`) so the persistence service is unit-testable with a fake, while one real-compile integration test guards the template itself.

**Tech Stack:** Python 3.13, uv, **typst** (new dep), Pydantic v2, SQLModel, Typer, pytest.

**Depends on:** Foundation (`models.resume.ResumeContent`, `models.profile.Contact/Education`, `tracking.tables`, `db`, `config.load_yaml`), Tailor + Review (`resume_versions` populated with `content_json`; `tracking.repository.get_job/save_job/save_resume_version`). All merged to `main`, suite green (101 tests).

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec §5.4. Decisions for this plan:

- **Typst via the bundled Python package** (`import typst`), not a shelled-out `typst` binary — zero system dependency, works in CI.
- **Data in, never markup out:** the LLM already produced structured `ResumeContent`; the template is the _only_ place layout lives. Restyling never needs an LLM.
- **Single-column, no custom font:** rely on Typst's bundled default font so compiles never fail on a missing font. Font/template choice is config (`config/render.yaml`) for later.
- **Injected compile step:** `render_version(..., render_fn=render_pdf)` so the DB/persistence logic is tested with a fake; `render_pdf` itself gets one real integration test.
- **Filename:** `output/{company}_{title}_{YYYYMMDD}.pdf`, slugified.

## File Structure (created/modified)

```
pyproject.toml                       # MODIFY: add `typst` dependency
templates/resume.typ                 # CREATE: single-column ATS template
config/render.yaml.example           # CREATE
src/resume_tailor_harness/
  render/
    __init__.py                      # CREATE
    render_config.py                 # CREATE: RenderConfig + load_render_config()
    renderer.py                      # CREATE: output_filename() + render_pdf()
    service.py                       # CREATE: render_version() persistence + job status
  tracking/
    repository.py                    # MODIFY: get_resume_version()
  cli.py                             # MODIFY: add `render` command
tests/
  test_render_config.py
  test_renderer.py
  test_repository.py                 # MODIFY: get_resume_version test
  test_render_service.py
  test_cli_render.py
```

---

## Task 1: Dependency + RenderConfig

**Files:**

- Modify: `pyproject.toml`
- Create: `src/resume_tailor_harness/render/__init__.py`, `src/resume_tailor_harness/render/render_config.py`
- Test: `tests/test_render_config.py`

- [ ] **Step 1: Add the dependency**

Run:

```bash
uv add typst
```

Expected: `pyproject.toml` gains `typst>=...` under `dependencies`; `uv.lock` updates; install succeeds.

- [ ] **Step 2: Verify the package imports**

Run:

```bash
uv run python -c "import typst; print('typst ok')"
```

Expected: prints `typst ok`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_render_config.py`:

```python
from resume_tailor_harness.render.render_config import RenderConfig, load_render_config


def test_defaults():
    cfg = RenderConfig()
    assert cfg.template_path == "templates/resume.typ"
    assert cfg.output_dir == "output"


def test_load_from_yaml(tmp_path):
    f = tmp_path / "render.yaml"
    f.write_text(
        "template_path: templates/custom.typ\noutput_dir: build/pdfs\n", encoding="utf-8"
    )
    cfg = load_render_config(f)
    assert cfg.template_path == "templates/custom.typ"
    assert cfg.output_dir == "build/pdfs"
```

- [ ] **Step 4: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_render_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.render'`.

- [ ] **Step 5: Implement**

Create `src/resume_tailor_harness/render/__init__.py`:

```python
"""Render component: ResumeContent -> Typst -> PDF (deterministic, no LLM)."""
```

Create `src/resume_tailor_harness/render/render_config.py`:

```python
from pathlib import Path

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel


class RenderConfig(ExtensibleModel):
    template_path: str = "templates/resume.typ"
    output_dir: str = "output"


def load_render_config(path: str | Path) -> RenderConfig:
    return RenderConfig.model_validate(load_yaml(path))
```

- [ ] **Step 6: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_render_config.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/resume_tailor_harness/render/__init__.py src/resume_tailor_harness/render/render_config.py tests/test_render_config.py
git commit -m "feat(render): add typst dep + RenderConfig" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Typst template + renderer

**Files:**

- Create: `templates/resume.typ`, `src/resume_tailor_harness/render/renderer.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_renderer.py`:

```python
from pathlib import Path

from resume_tailor_harness.models.profile import Contact, Education
from resume_tailor_harness.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
    TailoredSkill,
)
from resume_tailor_harness.render.renderer import output_filename, render_pdf


def test_output_filename_slugifies():
    name = output_filename("Acme Corp, Inc.", "Senior Backend Engineer", "20260609")
    assert name == "acme_corp_inc_senior_backend_engineer_20260609.pdf"


def _full_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(
            name="Ada Lovelace",
            email="ada@example.com",
            location="London, UK",
        ),
        summary="Backend engineer with a focus on reliability.",
        experience=[
            TailoredExperience(
                company="Analytical Engines",
                title="Staff Engineer",
                start="2020",
                end="Present",
                bullets=[TailoredBullet(text="Cut p99 latency by 40%.", provenance="b1")],
                provenance="e1",
            )
        ],
        projects=[
            TailoredProject(
                name="Looms",
                description="A distributed scheduler.",
                tech=["Python", "Rust"],
                bullets=[TailoredBullet(text="Open-sourced; 1k stars.", provenance="p1b1")],
                provenance="p1",
            )
        ],
        skills={"languages": [TailoredSkill(name="Python", provenance="s1")]},
        education=[Education(institution="Cambridge", degree="BA", field="Mathematics")],
    )


def test_render_pdf_writes_a_pdf(tmp_path):
    out = tmp_path / "resume.pdf"
    result = render_pdf(_full_content(), out, template_path="templates/resume.typ")
    assert result == out
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_renderer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.render.renderer'`.

- [ ] **Step 3: Implement the template**

Create `templates/resume.typ`:

```typst
// Single-column, ATS-parseable resume. Data arrives as a JSON string in
// `sys.inputs.data` (see render/renderer.py) and is decoded here.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: contact.name)
#set page(margin: (x: 1.6cm, y: 1.4cm))
#set text(size: 10pt)
#set par(justify: false)
#show heading.where(level: 1): it => [
  #v(6pt)
  #text(size: 12pt, weight: "bold", upper(it.body))
  #v(-4pt)
  #line(length: 100%, stroke: 0.5pt)
]

// Header
#align(center)[
  #text(size: 18pt, weight: "bold")[#contact.name]
  #if "headline" in contact and contact.headline != none [
    \ #text(size: 11pt)[#contact.headline]
  ]
  #let parts = (
    contact.at("location", default: none),
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none)
  #if parts.len() > 0 [ \ #parts.join("  •  ") ]
  #let links = contact.at("links", default: ())
  #if links.len() > 0 [
    \ #links.map(l => link(l.url)[#l.label]).join("  •  ")
  ]
]

#let summary = data.at("summary", default: none)
#if summary != none and summary != "" [
  = Summary
  #summary
]

#let experience = data.at("experience", default: ())
#if experience.len() > 0 [
  = Experience
  #for e in experience [
    #grid(
      columns: (1fr, auto),
      [*#e.title* — #e.company],
      [#e.at("start", default: "") #h(2pt)–#h(2pt) #e.at("end", default: "Present")],
    )
    #if e.at("location", default: none) != none [ #emph(e.location) \ ]
    #for b in e.at("bullets", default: ()) [ - #b.text ]
    #v(2pt)
  ]
]

#let projects = data.at("projects", default: ())
#if projects.len() > 0 [
  = Projects
  #for p in projects [
    *#p.name*#if p.at("description", default: none) != none [ — #p.description]
    #let tech = p.at("tech", default: ())
    #if tech.len() > 0 [ \ #emph("Tech: " + tech.join(", ")) ]
    #for b in p.at("bullets", default: ()) [ - #b.text ]
    #v(2pt)
  ]
]

#let skills = data.at("skills", default: (:))
#if skills.len() > 0 [
  = Skills
  #for (category, items) in skills [
    *#category:* #items.map(s => s.name).join(", ") \
  ]
]

#let education = data.at("education", default: ())
#if education.len() > 0 [
  = Education
  #for ed in education [
    *#ed.institution*#if ed.at("degree", default: none) != none [ — #ed.degree#if ed.at("field", default: none) != none [, #ed.field]]
    #if ed.at("end", default: none) != none [ #h(1fr) #ed.end ]
    \
  ]
]
```

- [ ] **Step 4: Implement the renderer**

Create `src/resume_tailor_harness/render/renderer.py`:

```python
import re
from pathlib import Path

import typst

from resume_tailor_harness.models.resume import ResumeContent


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


def output_filename(company: str, title: str, date_str: str) -> str:
    return f"{_slug(company)}_{_slug(title)}_{date_str}.pdf"


def render_pdf(
    content: ResumeContent,
    output_path: str | Path,
    template_path: str | Path = "templates/resume.typ",
) -> Path:
    """Compile the Typst template with the resume JSON into a PDF file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(
        str(template_path),
        output=str(out),
        sys_inputs={"data": content.model_dump_json()},
    )
    return out
```

- [ ] **Step 5: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_renderer.py -v
```

Expected: PASS (2 tests). If the compile errors on Typst syntax, fix `templates/resume.typ` until `test_render_pdf_writes_a_pdf` produces a `%PDF`.

- [ ] **Step 6: Eyeball the output (manual, optional)**

Run:

```bash
uv run python -c "from tests.test_renderer import _full_content; from resume_tailor_harness.render.renderer import render_pdf; render_pdf(_full_content(), 'output/_sample.pdf'); print('wrote output/_sample.pdf')"
```

Open `output/_sample.pdf` to confirm it looks like a one-page resume. (Delete it afterward; `output/` holds generated artifacts.)

- [ ] **Step 7: Commit**

```bash
git add templates/resume.typ src/resume_tailor_harness/render/renderer.py tests/test_renderer.py
git commit -m "feat(render): Typst template + render_pdf" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Repository — fetch a resume version

**Files:**

- Modify: `src/resume_tailor_harness/tracking/repository.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repository.py`:

```python
def test_get_resume_version_roundtrip():
    from sqlmodel import SQLModel, create_engine, Session
    from resume_tailor_harness.tracking.repository import get_resume_version, save_resume_version
    from resume_tailor_harness.tracking.tables import ResumeVersion

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        v = save_resume_version(s, ResumeVersion(job_id=1, round=1, content_json={"contact": {"name": "Ada"}}))
        fetched = get_resume_version(s, v.id)
        assert fetched is not None
        assert fetched.content_json["contact"]["name"] == "Ada"
        assert get_resume_version(s, 9999) is None
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_repository.py::test_get_resume_version_roundtrip -v
```

Expected: FAIL — `ImportError: cannot import name 'get_resume_version'`.

- [ ] **Step 3: Implement**

Add to `src/resume_tailor_harness/tracking/repository.py` (after `resume_versions_for_job`):

```python
def get_resume_version(session: Session, version_id: int) -> ResumeVersion | None:
    return session.get(ResumeVersion, version_id)
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_repository.py -v
```

Expected: PASS (all existing repo tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/repository.py tests/test_repository.py
git commit -m "feat(render): get_resume_version repository fn" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Render service (persistence + job status)

**Files:**

- Create: `src/resume_tailor_harness/render/service.py`
- Test: `tests/test_render_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_service.py`:

```python
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.profile import Contact
from resume_tailor_harness.render.render_config import RenderConfig
from resume_tailor_harness.render.service import render_version
from resume_tailor_harness.tracking.repository import get_resume_version, save_job, save_resume_version
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_render_version_sets_path_and_marks_rendered(tmp_path):
    calls = {}

    def fake_render(content, output_path, template_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        calls["content"] = content
        calls["template_path"] = template_path
        return Path(output_path)

    config = RenderConfig(template_path="templates/resume.typ", output_dir=str(tmp_path / "out"))
    with _session() as s:
        job = save_job(s, Job(source="manual", jd_text="jd", company="Acme", title="Engineer",
                              status=JobStatus.tailored.value))
        version = save_resume_version(
            s, ResumeVersion(job_id=job.id, round=1,
                             content_json=ResumeContent(contact=Contact(name="Ada")).model_dump(mode="json")),
        )

        path = render_version(s, version.id, config, render_fn=fake_render)

        assert path.exists()
        assert path.suffix == ".pdf"
        assert isinstance(calls["content"], ResumeContent)
        refreshed = get_resume_version(s, version.id)
        assert refreshed.pdf_path == str(path)
        assert job.status == JobStatus.rendered.value


def test_render_version_missing_returns_none(tmp_path):
    config = RenderConfig(output_dir=str(tmp_path))
    with _session() as s:
        assert render_version(s, 4242, config, render_fn=lambda *a, **k: None) is None
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_render_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.render.service'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/render/service.py`:

```python
from pathlib import Path
from typing import Callable

from sqlmodel import Session

from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.render.render_config import RenderConfig
from resume_tailor_harness.render.renderer import output_filename, render_pdf
from resume_tailor_harness.tracking.repository import get_job, get_resume_version, save_job, save_resume_version
from resume_tailor_harness.tracking.tables import JobStatus, ResumeVersion, utcnow

RenderFn = Callable[[ResumeContent, str | Path, str | Path], Path]


def render_version(
    session: Session,
    version_id: int,
    config: RenderConfig,
    render_fn: RenderFn = render_pdf,
) -> Path | None:
    """Render one resume version to PDF, store its path, mark the job rendered."""
    version: ResumeVersion | None = get_resume_version(session, version_id)
    if version is None:
        return None
    job = get_job(session, version.job_id)

    content = ResumeContent.model_validate(version.content_json or {})
    company = (job.company if job else None) or "company"
    title = (job.title if job else None) or "role"
    filename = output_filename(company, title, utcnow().strftime("%Y%m%d"))
    out_path = Path(config.output_dir) / filename

    render_fn(content, out_path, config.template_path)

    version.pdf_path = str(out_path)
    save_resume_version(session, version)
    if job is not None:
        job.status = JobStatus.rendered.value
        save_job(session, job)
    return out_path
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_render_service.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/render/service.py tests/test_render_service.py
git commit -m "feat(render): render_version persistence service" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLI — `render`

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Create: `config/render.yaml.example`
- Test: `tests/test_cli_render.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_render.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.tables import Job, JobStatus, ResumeVersion

runner = CliRunner()


def _seed(db_url) -> int:
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = Job(source="manual", jd_text="jd", company="Acme", title="Eng",
                  status=JobStatus.tailored.value)
        s.add(job)
        s.commit()
        s.refresh(job)
        v = ResumeVersion(job_id=job.id, round=1, content_json={"contact": {"name": "Ada"}})
        s.add(v)
        s.commit()
        s.refresh(v)
        return v.id


def test_render_command(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    version_id = _seed(db_url)

    monkeypatch.setattr(cli, "load_render_config", lambda path: object())

    def fake_render_version(session, vid, config, render_fn=None):
        assert vid == version_id
        return Path("output/fake.pdf")

    monkeypatch.setattr(cli, "render_version", fake_render_version)

    result = runner.invoke(cli.app, ["render", str(version_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "output/fake.pdf" in result.output.replace("\\", "/")
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_cli_render.py -v
```

Expected: FAIL — `AttributeError: module 'resume_tailor_harness.cli' has no attribute 'load_render_config'`.

- [ ] **Step 3: Implement**

Add imports near the other imports in `src/resume_tailor_harness/cli.py`:

```python
from resume_tailor_harness.render.render_config import load_render_config
from resume_tailor_harness.render.service import render_version
```

Add the command AFTER the `tailor` command and BEFORE `if __name__ == "__main__":`:

```python
DEFAULT_RENDER = "config/render.yaml"


@app.command("render")
def render_cmd(
    version_id: int = typer.Argument(..., help="resume_versions.id to render to PDF."),
    config: str = typer.Option(DEFAULT_RENDER, help="Path to render.yaml."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Render a stored resume version to a PDF."""
    render_config = load_render_config(config) if Path(config).exists() else None
    if render_config is None:
        from resume_tailor_harness.render.render_config import RenderConfig

        render_config = RenderConfig()
    engine = _engine(db_url)
    with get_session(engine) as session:
        path = render_version(session, version_id, render_config)
    if path is None:
        typer.echo(f"Resume version #{version_id} not found.")
        raise typer.Exit(code=1)
    typer.echo(f"Rendered version #{version_id} -> {path}")
```

Create `config/render.yaml.example`:

```yaml
# Render settings (see design spec §5.4).
template_path: templates/resume.typ
output_dir: output
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_cli_render.py -v
```

Expected: PASS (1 test).

- [ ] **Step 5: Verify wiring**

Run:

```bash
uv run resume-tailor-harness render --help
```

Expected: help text (exit 0).

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass (101 prior + Render additions).

- [ ] **Step 7: Commit**

```bash
git add src/resume_tailor_harness/cli.py config/render.yaml.example tests/test_cli_render.py
git commit -m "feat(render): render CLI command + render.yaml example" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.4):** `templates/resume.typ` single-column, ATS-parseable, content passed as JSON via `sys.inputs` (Task 2); `typst compile` → PDF (Task 2); output to `output/{company}_{role}_{date}.pdf` + path stored on the resume version (Tasks 2 & 4); template selectable via `config/render.yaml` (Tasks 1 & 5); no LLM anywhere (whole plan). Job advances to `rendered` (Task 4).
- **Placeholder scan:** none — complete template, renderer, service, and CLI code with exact commands.
- **Type consistency:** `render_pdf(content: ResumeContent, output_path, template_path) -> Path` is the default `render_fn` for `render_version(session, version_id, config, render_fn=render_pdf) -> Path | None`; CLI patches module-level `cli.load_render_config` and `cli.render_version`. `output_filename(company, title, date_str) -> str`. `RenderConfig(template_path, output_dir)` fields match the YAML keys and the service's use. `ResumeContent`/`Contact`/`Education`/`Tailored*` fields referenced in the template match `models/resume.py` + `models/profile.py`.

---

## Notes to carry into later plans

- **Tracking plan:** the Pipeline board reads `resume_versions.pdf_path` for the "open PDF" link; surface `rendered` jobs. A `dashboard`-driven render button can call `render_version` directly.
- A future "render the latest passing version for a job" convenience (`render_job <job_id>`) can select `max(round)` where `fact_check_passed` — deferred until the dashboard needs it.

## Execution Handoff

After this plan is executed and green, the remaining v1 components are **Tracking** (Streamlit dashboard) and the deferred **LinkedIn scraper** (see their plans).
