# Résumé Tailor Harness v2 — Unified `pull` + Connector Health (`sources`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command — `resume-tailor-harness pull` — runs every _enabled_ connector in canonical dedup order, ingests through the shared dedupe, records per-connector telemetry, and prints a per-source count table. A second command — `resume-tailor-harness sources` — shows each connector's last run, jobs added, and last error. `scrape` survives as a thin LinkedIn-only alias.

**Architecture:** This is **Plan 3 of 6** for v2 (spec `docs/superpowers/specs/2026-06-11-resume-tailor-harness-v2-connectors-design.md`). The deep module here is `run_pull`: it concentrates "iterate connectors → fetch → ingest → isolate failures → record telemetry → tally" in one place, so the CLI command is a thin shell and the orchestration is unit-tested with fake connectors (including one that raises). Telemetry is a **JSON state file** (`data/connector_runs.json`) — chosen over a DB table to avoid schema churn, per the spec's lean.

**Tech Stack:** Python 3.13, uv, Typer, SQLModel, pytest. No new deps.

**Depends on:** **Plan 1 + Plan 2 merged** (`ingest_jobs`, `build_connectors`, `ConnectorsConfig`/`load_connectors_config`, `Connector`/`RawJob`). Reuses the CLI's `_engine`, `get_session`, `load_search_config`.

> **Commit convention:** every commit ends with `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`.

---

## Architecture notes (the two lenses)

**Deepening:** `run_pull(session, connectors, search, telemetry, limit)` has a small interface but absorbs all the failure-isolation and tallying behavior — the **deletion test** says inlining it into the CLI would scatter that logic and make it untestable. Telemetry read/write is one module (`telemetry.py`); the format lives in exactly one place.

**Restraint (karpathy):** no scheduler, no retries, no concurrency — `pull` is a sequential, personal-volume command. `sources` reads the same file `pull` writes; no second source of truth. `scrape` is left almost untouched (it already builds the LinkedIn connector) rather than rewritten to route through `pull`.

---

## File Structure

```
src/resume_tailor_harness/discovery/connectors/
  telemetry.py            # CREATE — read_runs / record_run over a JSON file
  runner.py               # CREATE — run_pull(session, connectors, search, telemetry_path, limit)
src/resume_tailor_harness/cli.py   # MODIFY — add `pull` and `sources` commands
tests/test_connectors_telemetry.py   # CREATE
tests/test_connectors_runner.py      # CREATE
tests/test_cli_pull.py               # CREATE
tests/test_cli_sources.py            # CREATE
```

---

## Task 1: connector run telemetry (JSON state file)

**Files:**

- Create: `src/resume_tailor_harness/discovery/connectors/telemetry.py`
- Test: `tests/test_connectors_telemetry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_telemetry.py`:

```python
from resume_tailor_harness.discovery.connectors.telemetry import read_runs, record_run


def test_read_runs_missing_file_returns_empty(tmp_path):
    assert read_runs(tmp_path / "none.json") == {}


def test_record_run_persists_and_roundtrips(tmp_path):
    path = tmp_path / "runs.json"
    record_run(path, "greenhouse", added=4, error=None)
    record_run(path, "adzuna", added=0, error="HTTP 429")

    runs = read_runs(path)
    assert runs["greenhouse"]["added"] == 4
    assert runs["greenhouse"]["error"] is None
    assert runs["greenhouse"]["last_run"]  # ISO timestamp present
    assert runs["adzuna"]["error"] == "HTTP 429"


def test_record_run_overwrites_previous_entry_for_same_source(tmp_path):
    path = tmp_path / "runs.json"
    record_run(path, "greenhouse", added=4, error=None)
    record_run(path, "greenhouse", added=9, error=None)
    assert read_runs(path)["greenhouse"]["added"] == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_telemetry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.connectors.telemetry'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/discovery/connectors/telemetry.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path


def read_runs(path: str | Path) -> dict[str, dict]:
    """Return the per-connector run record, or {} if the file does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def record_run(path: str | Path, name: str, added: int, error: str | None) -> None:
    """Upsert one connector's last run (timestamp, jobs added, last error)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    runs = read_runs(p)
    runs[name] = {
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": added,
        "error": error,
    }
    p.write_text(json.dumps(runs, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_telemetry.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/telemetry.py tests/test_connectors_telemetry.py
git commit -m "feat(pull): connector run telemetry (JSON state file)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `run_pull` orchestrator (failure-isolating)

**Files:**

- Create: `src/resume_tailor_harness/discovery/connectors/runner.py`
- Test: `tests/test_connectors_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_connectors_runner.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.connectors.runner import run_pull
from resume_tailor_harness.discovery.connectors.telemetry import read_runs
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.tracking.repository import jobs_by_status
from resume_tailor_harness.tracking.tables import JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


class _Good:
    name = "greenhouse"

    def fetch(self, search, limit=None):
        return [RawJob("greenhouse", "https://gh/1", "Acme", "Backend Engineer", "Remote", "jd a")]


class _Boom:
    name = "adzuna"

    def fetch(self, search, limit=None):
        raise RuntimeError("HTTP 429")


def test_run_pull_ingests_counts_and_isolates_failures(tmp_path):
    telemetry = tmp_path / "runs.json"
    with _session() as s:
        counts = run_pull(s, [_Good(), _Boom()], SearchConfig(), telemetry, limit=None)

        assert counts == {"greenhouse": 1}  # Boom contributed nothing but did not abort the run
        assert {j.source for j in jobs_by_status(s, JobStatus.raw.value)} == {"greenhouse"}

        runs = read_runs(telemetry)
        assert runs["greenhouse"]["added"] == 1 and runs["greenhouse"]["error"] is None
        assert runs["adzuna"]["added"] == 0 and "429" in runs["adzuna"]["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_tailor_harness.discovery.connectors.runner'`.

- [ ] **Step 3: Implement**

Create `src/resume_tailor_harness/discovery/connectors/runner.py`:

```python
from pathlib import Path

from sqlmodel import Session

from resume_tailor_harness.discovery.connectors.base import Connector
from resume_tailor_harness.discovery.connectors.telemetry import record_run
from resume_tailor_harness.discovery.ingest import ingest_jobs
from resume_tailor_harness.discovery.search_config import SearchConfig


def run_pull(
    session: Session,
    connectors: list[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
) -> dict[str, int]:
    """Fetch + ingest each connector in order, isolating failures, recording telemetry.

    Returns the per-source added counts. A connector that raises is logged to
    telemetry with its error and contributes 0 — it never aborts the run.
    """
    totals: dict[str, int] = {}
    for connector in connectors:
        try:
            raw_jobs = connector.fetch(search, limit=limit)
            added = ingest_jobs(session, raw_jobs)
            count = added.get(connector.name, sum(added.values()))
            totals[connector.name] = count
            record_run(telemetry_path, connector.name, added=count, error=None)
        except Exception as exc:  # one bad source must not sink the rest
            record_run(telemetry_path, connector.name, added=0, error=f"{type(exc).__name__}: {exc}")
    return totals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_runner.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/runner.py tests/test_connectors_runner.py
git commit -m "feat(pull): run_pull orchestrator with per-connector failure isolation" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `pull` CLI command

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_pull.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_pull.py`:

```python
from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.discovery.connectors.base import RawJob

runner = CliRunner()


class _Conn:
    name = "greenhouse"

    def fetch(self, search, limit=None):
        return [RawJob("greenhouse", "https://gh/1", "Acme", "Engineer", "Remote", "a real jd")]


def test_pull_runs_enabled_connectors_and_reports(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    connectors_file = tmp_path / "connectors.yaml"
    connectors_file.write_text("greenhouse:\n  enabled: true\n", encoding="utf-8")
    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "load_connectors_config", lambda path: object())
    monkeypatch.setattr(cli, "build_connectors", lambda cfg, settings: [_Conn()])
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(tmp_path / "runs.json"))

    result = runner.invoke(cli.app, ["pull", "--db-url", db_url, "--connectors", str(connectors_file)])

    assert result.exit_code == 0, result.output
    assert "greenhouse" in result.output
    assert "1" in result.output


def test_pull_reports_missing_connectors_config(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    missing = tmp_path / "missing.yaml"

    result = runner.invoke(cli.app, ["pull", "--db-url", db_url, "--connectors", str(missing)])

    assert result.exit_code == 1
    assert "No connectors config found" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_pull.py -v`
Expected: FAIL — `AttributeError: module 'resume_tailor_harness.cli' has no attribute 'build_connectors'`.

- [ ] **Step 3: Implement — imports + constants**

In `src/resume_tailor_harness/cli.py`, add near the other discovery imports:

```python
from resume_tailor_harness.discovery.connectors.config import load_connectors_config
from resume_tailor_harness.discovery.connectors.registry import build_connectors
from resume_tailor_harness.discovery.connectors.runner import run_pull
```

Add a default path constant near `DEFAULT_SEARCH`:

```python
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"
```

- [ ] **Step 4: Implement — the command**

Add this command after `scrape_cmd` in `src/resume_tailor_harness/cli.py`:

```python
@app.command("pull")
def pull_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run every enabled connector, dedupe into raw jobs, and report per-source counts."""
    if not Path(connectors_path).exists():
        typer.echo(
            f"No connectors config found at {connectors_path}. "
            "Copy config/connectors.yaml.example to config/connectors.yaml and edit it."
        )
        raise typer.Exit(code=1)
    search_config = load_search_config(search)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_connectors(connectors_config, get_settings())
    if not connectors:
        typer.echo("No connectors enabled. Edit connectors.yaml (and .env) to enable some.")
        raise typer.Exit(code=0)
    engine = _engine(db_url)
    with get_session(engine) as session:
        totals = run_pull(session, connectors, search_config, CONNECTOR_RUNS_PATH, limit=limit)
    for name in (c.name for c in connectors):
        typer.echo(f"  {name:<12} +{totals.get(name, 0)}")
    typer.echo(f"Pull complete. Added {sum(totals.values())} new job(s).")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_pull.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_pull.py
git commit -m "feat(pull): pull CLI command (all enabled connectors)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `sources` CLI command (connector health)

**Files:**

- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_cli_sources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_sources.py`:

```python
from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.discovery.connectors.telemetry import record_run

runner = CliRunner()


def test_sources_lists_recorded_runs(tmp_path, monkeypatch):
    runs_path = tmp_path / "runs.json"
    record_run(runs_path, "greenhouse", added=4, error=None)
    record_run(runs_path, "adzuna", added=0, error="HTTPError: 429")
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(runs_path))

    result = runner.invoke(cli.app, ["sources"])

    assert result.exit_code == 0, result.output
    assert "greenhouse" in result.output and "4" in result.output
    assert "adzuna" in result.output and "429" in result.output


def test_sources_handles_no_history(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONNECTOR_RUNS_PATH", str(tmp_path / "none.json"))
    result = runner.invoke(cli.app, ["sources"])
    assert result.exit_code == 0
    assert "No connector runs recorded" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_sources.py -v`
Expected: FAIL — `typer` reports no such command `sources` (exit code != 0).

- [ ] **Step 3: Implement**

Add the import near the other connector imports in `src/resume_tailor_harness/cli.py`:

```python
from resume_tailor_harness.discovery.connectors.telemetry import read_runs
```

Add this command after `pull_cmd`:

```python
@app.command("sources")
def sources_cmd() -> None:
    """Show each connector's last run: when, jobs added, and last error."""
    runs = read_runs(CONNECTOR_RUNS_PATH)
    if not runs:
        typer.echo("No connector runs recorded yet. Run `resume-tailor-harness pull` first.")
        raise typer.Exit(code=0)
    for name, info in sorted(runs.items()):
        status = info.get("error") or f"+{info.get('added', 0)} added"
        typer.echo(f"  {name:<12} {info.get('last_run', '-'):<22} {status}")
```

- [ ] **Step 4: Run test, then the full suite**

Run: `uv run pytest tests/test_cli_sources.py -v`
Expected: PASS (2 tests).

Run: `uv run pytest -q`
Expected: ALL pass.

Run: `uv run resume-tailor-harness pull --help && uv run resume-tailor-harness sources --help`
Expected: help text for both, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_sources.py
git commit -m "feat(pull): sources connector-health command" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

**Spec coverage (§5.7, §5.8, Decision #7):** `pull` runs all enabled connectors in canonical order (order comes from `build_connectors`, Plan 2) and prints per-source counts — Task 3; `sources` health view — Task 4; telemetry state file written by the runner, read by `sources` — Tasks 1/2/4; `scrape` retained as the LinkedIn-only alias (unchanged from Plan 1) — no task needed. Per-connector failure isolation (a spec resilience requirement, §3.5) — Task 2.

**Placeholder scan:** none — full code for telemetry, runner, and both CLI commands, with exact patch locations.

**Type consistency:** `run_pull(session, connectors, search, telemetry_path, limit=None) -> dict[str,int]` matches the CLI call and test. `record_run(path, name, added, error)` / `read_runs(path) -> dict` match every call site. `CONNECTOR_RUNS_PATH` is patched by both CLI tests and read in both commands. `build_connectors(cfg, settings)` / `load_connectors_config(path)` signatures match Plan 2.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-11-resume-tailor-harness-v2-pull-and-sources.md`. Execute via **superpowers:subagent-driven-development** or **superpowers:executing-plans**. This closes the connector backbone (Plans 1→2→3). The remaining three are independent leaves: **Plan 4 (cover letters)**, **Plan 5 (Gmail auto-status)**, **Plan 6 (analytics)** — buildable in any order.
