# Architecture / Performance / Stability Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement all 6 candidates from the 2026-07-07 architecture review: WAL + busy-timeout pragmas at the engine seam, one profile-build seam shared by CLI and API, one fragment cache walk with per-mode producers, concurrent per-document fragment production, industry normalization scoped to touched rows, and transactional bulk mutations behind the Board seam.

**Architecture:** Every change deepens an existing seam without changing its public interface — callers and the wire contract stay untouched, so the existing suite doubles as the conformance check. The fragment work gives the profile corpus the same deep Harvest/Producer shape discovery already has (one walk owning cache/staleness/failure policy, per-mode producers supplying the genuine variation), then reuses the established `gather_isolated` + `acall`-semaphore fan-out. The DB work applies the proven batched-gate pattern (`progressed_job_ids` + `job_has_progress`) to the mutation side and hardens SQLite for the API's multi-writer reality.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy (SQLite), FastAPI, Typer, agno, asyncio, pytest (offline suite — all agents/browsers faked).

## Global Constraints

- Test command: `.venv/Scripts/python.exe -m pytest` (offline — no API key, no network). Lint: `ruff check`.
- No new dependencies.
- The wire format (camelCase Pydantic schemas) must not change — no task may alter `contracts/openapi.json`.
- Core invariants from CLAUDE.md hold: fact-lock provenance, source-priority upgrade-not-drop, `has_progress` (or its batched mirror `job_has_progress` + `progressed_job_ids`) as the single irreversible-path gate, worker-owns-its-session.
- The LLM semaphore is acquired **only** inside `llm_runner.acall` (the leaf) — Task 4 must not add a second acquisition site.
- Existing tests are conformance gates: if a pre-existing test fails, fix the code, never the test (exceptions are called out explicitly per task).
- Commit after every task (style: present-tense third person, e.g. "Batches board bulk mutations into one commit").

## Source findings this plan is built on (verified 2026-07-07)

| #   | Finding                                                                                                                                                                                                                                                                                                                  | Evidence                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| 1   | File-backed engines are a bare `create_engine(url)` — default rollback journal, no explicit busy timeout — while the API runs concurrent writers (RunManager default pool of 2, a per-kind suggestion pool, the request threadpool). Batched ingest (task 2 of the 2026-07-02 plan) holds the write lock longer per txn. | `src/resume_agent/db.py:38-52`, `api/app.py:95-101`, `api/runs/manager.py:118`    |
| 2   | The agents→`build_corpus_profile`→`save_facts`→`build_matrix`→`save_matrix` orchestration is implemented twice: `cli.py` `profile_build` and `services/profile_build.run_corpus_build`. The API router already calls the service.                                                                                        | `cli.py:118-199`, `services/profile_build.py:10-55`, `api/routers/profile.py:97`  |
| 3   | `extract_fragments` and `extract_synthesis_fragments` are twin ~50-line walks: sha check, manifest bump, meta match → cache hit, error → stale fallback, atomic save, status vocabulary — differing only in meta shape and the produce step.                                                                             | `profile/fragments.py:140-261`                                                    |
| 4   | The profile build walks documents serially; a synthesis doc costs up to 4 sequential LLM calls (synthesize → entail → repair → entail). Discovery/tailor already fan out via `gather_isolated` with the semaphore in `acall`. Every profile test fake already implements `arun` (delegating to `run`).                   | `profile/fragments.py`, `profile/synthesis.py:352-382`, `tests/test_profile_*.py` |
| 5   | `_normalize_job_industries` loads **every** `Job` (archived included) on every extract and rebuilds every row's criteria dict twice; SQLAlchemy's scalar-history equality check bounds the writes, but load/parse/flush-compare is O(table) per discover run.                                                            | `discovery/pipeline.py:137-193` (sole caller: `run_extract`, pipeline.py:98)      |
| 6   | `bulk_apply` re-runs the mutation-side N+1: `get_job` (1 query) + `has_progress` (≤4 queries) per job, plus one COMMIT per row via `set_stage`/`archive_job`/`delete_job` — a crash mid-loop leaves a half-applied bulk. `prune_run` has the same shape.                                                                 | `services/board.py:354-407`, `tracking/repository.py:439-449`                     |

Task order is safest-first. Tasks 3→4 are sequential (4 rewrites 3's produce loop); everything else is independent.

---

### Task 1: WAL + busy timeout at the engine seam

**Files:**

- Modify: `src/resume_agent/db.py:38-52` (`make_engine` file-SQLite branch)
- Test: `tests/test_db.py` (append)

**Interfaces:**

- Consumes: nothing new.
- Produces: `make_engine(url)` — signature and return type unchanged. New behavior: every connection to a **file** SQLite database gets `journal_mode=WAL`, `busy_timeout=30000`, `synchronous=NORMAL`. In-memory engines (the `StaticPool` branch) and non-SQLite URLs are untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
def test_file_sqlite_gets_wal_and_busy_timeout(tmp_path):
    from resume_agent.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    init_db(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db.py::test_file_sqlite_gets_wal_and_busy_timeout -v`
Expected: FAIL — journal_mode is `delete`, busy_timeout is `0` (SQLAlchemy passes no `timeout`; the pragma default is 0 even though the driver blocks ~5s).

- [ ] **Step 3: Implement the pragma hook**

In `src/resume_agent/db.py`, add the import:

```python
from sqlalchemy import event
```

Add above `make_engine`:

```python
def _enable_sqlite_write_concurrency(engine: Engine) -> None:
    """WAL + busy timeout on every connection to a file-backed SQLite DB.

    The API runs several writer threads (RunManager pools + the request
    threadpool) against one file; WAL lets readers proceed under a writer,
    and the busy timeout turns lock contention into a bounded wait instead
    of an immediate 'database is locked' error.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
```

Change the tail of `make_engine` (the non-memory return) to:

```python
    engine = create_engine(resolved, echo=False)
    if resolved.startswith("sqlite"):
        _enable_sqlite_write_concurrency(engine)
    return engine
```

- [ ] **Step 4: Run the new test, then the DB/migration suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db.py tests/test_migrate.py tests/test_migrate_lifecycle.py tests/api -v`
Expected: all PASS. (WAL creates `-wal`/`-shm` sidecar files next to the DB — nothing in the suite asserts directory contents, but if a test does, the fix is to filter to `*.db`.)

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/db.py tests/test_db.py
git commit -m "Enables WAL and busy timeout for file-backed SQLite engines"
```

---

### Task 2: One profile-build seam — CLI delegates to run_corpus_build

**Files:**

- Modify: `src/resume_agent/services/profile_build.py` (reporter becomes optional; return gains `matrixRows`)
- Modify: `src/resume_agent/cli.py:118-199` (`profile_build` body delegates)
- Test: `tests/test_cli_profile.py` (existing tests are the conformance gate; append one delegation test)

**Interfaces:**

- Consumes: `run_corpus_build(reporter, *, profile_dir, github_username, facts_out) -> dict` (existing; the API router at `api/routers/profile.py:97` passes reporter positionally — that call shape must keep working).
- Produces: `run_corpus_build(reporter=None, *, profile_dir, github_username, facts_out) -> dict` — reporter now optional (None → no progress writes); returned dict gains `"matrixRows": int` (additive key; the run-result payload is a free-form dict, no OpenAPI change). CLI `profile build` flags and output lines unchanged.

- [ ] **Step 1: Make the reporter optional and add matrixRows**

In `src/resume_agent/services/profile_build.py`, change the signature and guard every reporter call:

```python
def run_corpus_build(
    reporter=None,
    *,
    profile_dir: Path,
    github_username: str | None,
    facts_out: str | Path,
) -> dict:
```

Wrap the three reporter calls:

```python
    if reporter is not None:
        reporter.begin(3, "Extracting and merging source documents")
```

```python
    if reporter is not None:
        reporter.step(1, label="Saving facts.json")
```

```python
    if reporter is not None:
        reporter.step(2, label="Building skill matrix")
```

```python
    if reporter is not None:
        reporter.step(3, label="Saved matrix.json")
```

(The `reporter.step(3, ...)` call currently sits before the return; keep it there.) Add to the returned dict, right after `"projects"`:

```python
        "matrixRows": len(matrix.rows),
```

- [ ] **Step 2: Replace the CLI orchestration with the service call**

In `src/resume_agent/cli.py`, inside `profile_build`, replace the lazy-import block

```python
    from resume_agent.profile.build import build_corpus_profile
    from resume_agent.profile.corpus import migrate_legacy
    from resume_agent.profile.inference import build_inference_agent
    from resume_agent.profile.matrix import build_matrix, load_overrides, save_matrix
    from resume_agent.profile.merge import build_bullet_dedup_agent
    from resume_agent.profile.synthesis import build_entailment_agent, build_synthesis_agent
    from resume_agent.taxonomy.clusters import load_cluster_map
```

with

```python
    from resume_agent.profile.corpus import migrate_legacy
    from resume_agent.services.profile_build import run_corpus_build
```

Keep the key gate, the `--out` binding check, the `--refresh` check, and the `migrate_legacy` echo exactly as they are. Then replace everything from `facts, report = build_corpus_profile(` down to the final `typer.echo(f"  WARNING: {warning}")` loop with:

```python
    report = run_corpus_build(
        None,
        profile_dir=Path(dir),
        github_username=cast(str | None, cfg.get("github_username")),
        facts_out=out,
    )
    typer.echo(
        f"Wrote {report['experiences']} experiences and "
        f"{report['projects']} projects to {out}"
    )
    typer.echo(f"Matrix: {report['matrixRows']} skills")
    for doc_id, status in report["docStatus"].items():
        typer.echo(f"  {doc_id}: {status}")
    for conflict in report["conflicts"]:
        typer.echo(f"  CONFLICT: {conflict}")
    for name in report["inferred"]:
        typer.echo(f"  inferred: {name}")
    for line in report["anchorDecisions"]:
        typer.echo(f"  anchor: {line}")
    for line in report["verificationDrops"]:
        typer.echo(f"  DROPPED: {line}")
    for warning in report["warnings"]:
        typer.echo(f"  WARNING: {warning}")
```

If `save_facts` is now unused in `cli.py`, remove its import (check with `ruff check` — other commands may still use it).

- [ ] **Step 3: Run the existing CLI conformance tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_profile.py -v`
Expected: all PASS **unmodified**. They already monkeypatch the source modules (`resume_agent.profile.build.build_corpus_profile`, the four builder functions), which the service's lazy imports resolve at call time — so the same patches govern the new path. If a test fails, the delegation has a semantic drift — fix the CLI/service, never the test.

- [ ] **Step 4: Write the delegation drift test**

Append to `tests/test_cli_profile.py` (add `from pathlib import Path` to the imports if absent):

```python
def test_profile_build_delegates_to_the_service(tmp_path, monkeypatch):
    calls = {}

    def fake_run(reporter, *, profile_dir, github_username, facts_out):
        calls["reporter"] = reporter
        calls["github_username"] = github_username
        calls["facts_out"] = str(facts_out)
        return {
            "experiences": 0, "projects": 0, "matrixRows": 0,
            "docStatus": {}, "conflicts": [], "anchorDecisions": [],
            "verificationDrops": [], "inferred": [], "warnings": [],
        }

    monkeypatch.setattr(
        cli, "get_settings",
        lambda: type("S", (), {"cheap_model": "cheap", "mid_model": "mid"})(),
    )
    monkeypatch.setattr(cli, "resolve_api_key", lambda model: "sk-test")
    monkeypatch.setattr(
        "resume_agent.services.profile_build.run_corpus_build", fake_run
    )

    sources = _write_sources(tmp_path)
    profile_dir = tmp_path / "profile"
    out = profile_dir / "facts.json"
    result = runner.invoke(
        cli.app,
        ["profile", "build", "--sources", str(sources),
         "--dir", str(profile_dir), "--out", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert calls["reporter"] is None
    assert calls["github_username"] == "ada"
    assert calls["facts_out"] == str(out)
```

- [ ] **Step 5: Run the new test + API profile suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_profile.py tests/test_profile_build.py tests/api -v`
Expected: all PASS (the API path pins the reporter-passing call shape).

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/cli.py src/resume_agent/services/profile_build.py tests/test_cli_profile.py
git commit -m "Routes the CLI profile build through the single service seam"
```

---

### Task 3: One fragment cache walk with per-mode producers

**Files:**

- Modify: `src/resume_agent/profile/fragments.py` (replace the twin walks; public signatures unchanged)
- Test: `tests/test_profile_fragments.py` (existing tests are the conformance gate; append one shared-walk test)

**Interfaces:**

- Consumes: `extract_profile_facts`, `assign_fact_ids`, `synthesize_document`, `fragment_to_facts`, `read_document_text`, `SourceDoc`, `save_manifest` (all already imported by fragments.py).
- Produces (from `resume_agent.profile.fragments`):
  - `Produced` dataclass: `facts: ProfileFacts`, `evidence: dict | None = None`, `drops: list[str] | None = None`.
  - `FragmentProducer` dataclass: `selects: Callable[[SourceDoc], bool]`, `expected_meta: Callable[[SourceDoc, str], dict]`, `produce: Callable[[SourceDoc, str], Produced]`.
  - `extract_fragments(profile_dir, manifest, agent)` and `extract_synthesis_fragments(profile_dir, manifest, skeleton, synthesis_agent, entailment_agent)` — **signatures, `FragmentResult` shape, status vocabulary, and cache/meta file formats unchanged**.
  - Task 4 relies on: the walk's two-phase structure (cache pre-pass building a `_Pending` list, then a produce loop) and the exact names `_Pending`, `_record_failure`, `_apply_produced`, `_save_produced`, `_literal_meta`, `_synthesis_meta`.

- [ ] **Step 1: Baseline the fragment tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_fragments.py -v`
Expected: PASS (these must still pass, unmodified, after the rewrite).

- [ ] **Step 2: Rewrite fragments.py around one walk**

Replace everything in `src/resume_agent/profile/fragments.py` from `def _meta_matches(` through the end of `extract_synthesis_fragments` (keep the module docstring, imports, `CacheStatus`, `FragmentResult`, `_paths`, `evidence_path`, `load_fragment`, `_atomic_write`) with:

```python
def _literal_meta(sha256: str) -> dict:
    return {
        "sha256": sha256,
        "prompt_version": PROMPT_VERSION,
        "converter_version": CONVERTER_VERSION,
    }


def _synthesis_meta(doc: SourceDoc, sha256: str) -> dict:
    return {
        "sha256": sha256,
        "synthesis_prompt_version": SYNTHESIS_PROMPT_VERSION,
        "converter_version": CONVERTER_VERSION,
        "mode": doc.mode,
        "anchor": doc.anchor,
    }


def _meta_equals(meta_path: Path, expected: dict) -> bool:
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return metadata == expected


def _expected_meta(doc: SourceDoc, sha256: str) -> dict:
    if doc.mode == "synthesis":
        return _synthesis_meta(doc, sha256)
    return _literal_meta(sha256)


def fragment_cache_status(profile_dir: str | Path, doc: SourceDoc) -> CacheStatus:
    fragment_path, meta_path = _paths(profile_dir, doc.id)
    try:
        observed_sha = hashlib.sha256(doc_path(profile_dir, doc).read_bytes()).hexdigest()
    except OSError:
        return "stale" if fragment_path.exists() else "missing"
    if observed_sha != doc.sha256:
        return "source-changed"
    if _meta_equals(meta_path, _expected_meta(doc, observed_sha)) and load_fragment(
        profile_dir, doc.id
    ):
        return "cached"
    return "stale" if fragment_path.exists() or meta_path.exists() else "missing"


@dataclass
class Produced:
    """What one producer yields for one document."""

    facts: ProfileFacts
    evidence: dict | None = None
    drops: list[str] | None = None


@dataclass(frozen=True)
class FragmentProducer:
    """One extraction mode behind the fragment cache walk.

    The walk owns everything both modes used to copy — sha check, manifest
    bump, meta match, cache hit, error -> stale fallback, atomic save, status
    vocabulary. A producer supplies only the genuine variation: which docs it
    selects, the meta that keys their cache entries, and the produce step.
    """

    selects: Callable[[SourceDoc], bool]
    expected_meta: Callable[[SourceDoc, str], dict]
    produce: Callable[[SourceDoc, str], Produced]


@dataclass
class _Pending:
    doc: SourceDoc
    text: str
    meta: dict
    source_changed: bool


def _record_failure(
    result: FragmentResult, profile_dir: str | Path, doc: SourceDoc, exc: BaseException
) -> None:
    """Fall back to the previous fragment when a doc can't be (re)produced."""
    previous = load_fragment(profile_dir, doc.id)
    if previous is None:
        result.status[doc.id] = f"failed: {exc}"
    else:
        result.fragments[doc.id] = previous
        result.status[doc.id] = f"stale: {exc}"


def _save_produced(
    profile_dir: str | Path, doc_id: str, produced: Produced, meta: dict
) -> None:
    fragment_path, meta_path = _paths(profile_dir, doc_id)
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(fragment_path, produced.facts.model_dump_json(indent=2) + "\n")
    if produced.evidence is not None:
        _atomic_write(
            evidence_path(profile_dir, doc_id),
            json.dumps(produced.evidence, indent=2, sort_keys=True) + "\n",
        )
    _atomic_write(meta_path, json.dumps(meta, sort_keys=True) + "\n")


def _apply_produced(
    result: FragmentResult, profile_dir: str | Path, item: _Pending, produced: Produced
) -> None:
    _save_produced(profile_dir, item.doc.id, produced, item.meta)
    result.fragments[item.doc.id] = produced.facts
    result.status[item.doc.id] = "source-changed" if item.source_changed else "extracted"
    if produced.drops is not None:
        result.drops[item.doc.id] = produced.drops


def _walk_fragments(
    profile_dir: str | Path, manifest: SourceManifest, producer: FragmentProducer
) -> FragmentResult:
    """Cache pre-pass over the producer's docs, then produce what's missing."""
    result = FragmentResult()
    manifest_changed = False
    pending: list[_Pending] = []
    for doc in manifest.docs:
        if not producer.selects(doc):
            continue
        _, meta_path = _paths(profile_dir, doc.id)
        source_path = doc_path(profile_dir, doc)
        try:
            observed_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except OSError as exc:
            _record_failure(result, profile_dir, doc, exc)
            continue
        source_changed = observed_sha != doc.sha256
        if source_changed:
            doc.sha256 = observed_sha
            manifest_changed = True
        expected = producer.expected_meta(doc, observed_sha)
        if _meta_equals(meta_path, expected):
            cached = load_fragment(profile_dir, doc.id)
            if cached is not None:
                result.fragments[doc.id] = cached
                result.status[doc.id] = "cached"
                continue
        try:
            text = read_document_text(source_path)
        except Exception as exc:
            _record_failure(result, profile_dir, doc, exc)
            continue
        pending.append(_Pending(doc, text, expected, source_changed))

    for item in pending:
        try:
            produced = producer.produce(item.doc, item.text)
        except Exception as exc:
            _record_failure(result, profile_dir, item.doc, exc)
            continue
        _apply_produced(result, profile_dir, item, produced)

    if manifest_changed:
        save_manifest(manifest, profile_dir)
    return result


def extract_fragments(
    profile_dir: str | Path, manifest: SourceManifest, agent: Runner
) -> FragmentResult:
    """Extract literal-mode documents, reusing valid cached fragments."""

    def _produce(doc: SourceDoc, text: str) -> Produced:
        return Produced(facts=assign_fact_ids(extract_profile_facts(text, agent), doc.id))

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode != "synthesis",
            expected_meta=lambda doc, sha: _literal_meta(sha),
            produce=_produce,
        ),
    )


def extract_synthesis_fragments(
    profile_dir: str | Path,
    manifest: SourceManifest,
    skeleton: list[dict],
    synthesis_agent: Runner,
    entailment_agent: Runner,
) -> FragmentResult:
    """Synthesize registered synthesis-mode documents, reusing valid caches."""

    def _produce(doc: SourceDoc, text: str) -> Produced:
        fragment, drops = synthesize_document(
            doc, text, skeleton, synthesis_agent, entailment_agent
        )
        facts, evidence = fragment_to_facts(doc, fragment, skeleton)
        return Produced(facts=facts, evidence=evidence, drops=drops)

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode == "synthesis",
            expected_meta=_synthesis_meta,
            produce=_produce,
        ),
    )
```

Add to the imports at the top: `from dataclasses import dataclass, field` is already there (drop `field` if now unused); add `from collections.abc import Callable`.

Behavioral notes encoded above — verify, don't re-derive:

- The old literal `_meta_matches` was a 3-key subset check; `_meta_equals` is full equality. Files written by the current `_save` contain exactly those 3 keys, so equality holds for every existing cache. Same for synthesis (already full equality).
- `drops` parity: the old synthesis walk recorded `result.drops[doc.id]` unconditionally (even `[]`); the old literal walk never did. `Produced.drops=None` (literal) vs `drops` list (synthesis) preserves both.
- The evidence file is written only when `evidence is not None` — literal parity (never wrote one).
- Manifest sha bumps still persist even when production later fails (pre-pass sets them; save happens at the end regardless).

- [ ] **Step 3: Add the shared-walk test**

Append to `tests/test_profile_fragments.py`:

```python
def test_walk_stale_fallback_is_shared_by_both_modes(tmp_path):
    # Literal doc: fail after a good extraction -> previous fragment survives.
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    good = ProfileFacts(contact=Contact(name="Ada"))
    extract_fragments(profile_dir, manifest, _FakeAgent(good))
    (tmp_path / "profile" / "sources" / "resume.txt").write_text("Ada v2", "utf-8")
    result = extract_fragments(
        profile_dir, load_manifest(profile_dir), _FakeAgent(None, fail=True)
    )
    assert result.status[doc_id].startswith("stale:")
    assert result.fragments[doc_id].contact.name == "Ada"
```

(If an equivalent stale-fallback test already exists for the literal mode, this pins that the consolidated walk kept it; keep both.)

- [ ] **Step 4: Run conformance + the build/CLI suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_fragments.py tests/test_profile_build.py tests/test_cli_profile.py tests/test_profile_corpus.py -v`
Expected: all PASS with zero edits to pre-existing tests.

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/profile/fragments.py tests/test_profile_fragments.py
git commit -m "Collapses the twin fragment walks into one cache walk with per-mode producers"
```

---

### Task 4: Concurrent per-document fragment production

**Files:**

- Modify: `src/resume_agent/profile/extractor.py` (add `aextract_profile_facts`)
- Modify: `src/resume_agent/profile/synthesis.py` (split `_verify` into shared helpers; add `_averify`, `asynthesize_document`, `_expect_fragment`)
- Modify: `src/resume_agent/profile/fragments.py` (producer `produce` goes async; the serial produce loop becomes a `gather_isolated` fan-out)
- Test: `tests/test_profile_fragments.py` (append a concurrency probe test)

**Interfaces:**

- Consumes: `gather_isolated(items, fn) -> list[Result]` (`concurrency.py:28`), `acall(agent, prompt, *, sem)` and `run_with_cleanup(operation, *runners)` (`llm_runner.py`), `Settings.llm_concurrency`.
- Produces:
  - `aextract_profile_facts(resume_text: str, agent: Runner, *, sem: asyncio.Semaphore) -> ProfileFacts` in `profile.extractor`.
  - `asynthesize_document(doc, doc_text, skeleton, synthesis_agent, entailment_agent, *, sem) -> tuple[SynthesizedFragment, list[str]]` in `profile.synthesis`. Sync `synthesize_document` stays (tests call it directly).
  - `FragmentProducer.produce: Callable[[SourceDoc, str, asyncio.Semaphore], Awaitable[Produced]]` and a new field `runners: tuple[Any, ...] = ()`; `extract_fragments` / `extract_synthesis_fragments` signatures unchanged.
- Invariants: the semaphore permit is acquired only inside `acall` (the leaf), so a synthesis doc's 4 nested calls cannot deadlock the fan-out; results apply and the manifest saves on the loop thread, in doc order.

- [ ] **Step 1: Write the failing concurrency test**

Append to `tests/test_profile_fragments.py` (the file's `_FakeAgent` already has `arun`; this probe measures overlap):

```python
def test_synthesis_docs_are_produced_concurrently(tmp_path):
    import asyncio as aio

    class _Probe:
        def __init__(self, content):
            self._content = content
            self.active = 0
            self.max_active = 0

        def run(self, prompt):
            return _FakeResult(self._content)

        async def arun(self, prompt):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await aio.sleep(0.02)
            self.active -= 1
            return _FakeResult(self._content)

    profile_dir = _setup(tmp_path)
    for name in ("deck-a.pptx", "deck-b.pptx"):
        deck = tmp_path / name
        deck.write_bytes(b"deck bytes " + name.encode())
        add_source(profile_dir, deck, mode="synthesis")

    fragment = SynthesizedFragment(
        entries=[
            SynthesizedEntry(
                kind="project",
                title="Probe",
                claims=[SynthesizedClaim(text="did work", support=["deck bytes"])],
            )
        ]
    )
    synthesis = _Probe(fragment)
    entailment = _Probe(
        ClaimVerdicts(verdicts=[ClaimVerdict(index=0, verdict="supported")])
    )
    result = extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), [], synthesis, entailment
    )
    statuses = {
        doc.id: result.status.get(doc.id)
        for doc in load_manifest(profile_dir).docs
        if doc.mode == "synthesis"
    }
    assert all(status == "extracted" for status in statuses.values()), statuses
    assert synthesis.max_active >= 2  # the two docs' synthesis calls overlapped
```

Notes for the implementer: `.pptx` is in `SUPPORTED_SUFFIXES` and defaults to synthesis mode; `read_document_text` must be able to read the fake deck — if the markitdown reader rejects the fake bytes, monkeypatch it instead: `monkeypatch.setattr("resume_agent.profile.fragments.read_document_text", lambda path: "deck bytes " + Path(path).name)` (add `monkeypatch` to the test's parameters and `from pathlib import Path` to the imports). The deterministic checks pass because the claim has a support excerpt found in that text and no numbers/proper nouns beyond "Probe" (which is the entry title, not claim text).

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_fragments.py::test_synthesis_docs_are_produced_concurrently -v`
Expected: FAIL — the serial walk gives `max_active == 1` (or a TypeError if the sync walk calls `run` — either way it fails before the assertion passes).

- [ ] **Step 3: Add the async extractor sibling**

In `src/resume_agent/profile/extractor.py`, add `import asyncio` and extend the `llm_runner` import with `acall`, then append:

```python
async def aextract_profile_facts(
    resume_text: str, agent: Runner, *, sem: asyncio.Semaphore
) -> ProfileFacts:
    """Async sibling of extract_profile_facts for the fragment fan-out."""
    result = await acall(agent, resume_text, sem=sem)
    facts = result.content
    if not isinstance(facts, ProfileFacts):
        raise TypeError(f"Expected ProfileFacts from agent, got {type(facts).__name__}")
    return facts
```

- [ ] **Step 4: Split synthesis verification and add the async siblings**

In `src/resume_agent/profile/synthesis.py`, add `import asyncio` and extend the `llm_runner` import with `acall`. Add above `_verify`:

```python
def _expect_fragment(content: object) -> SynthesizedFragment:
    if not isinstance(content, SynthesizedFragment):
        raise TypeError(
            f"Expected SynthesizedFragment from agent, got {type(content).__name__}"
        )
    return content


def _deterministic_pass(
    fragment: SynthesizedFragment, source_text: str
) -> tuple[
    dict[tuple[int, int], str],
    list[tuple[tuple[int, int], SynthesizedClaim]],
    dict[int, dict[str, str]],
]:
    failures: dict[tuple[int, int], str] = {}
    pending: list[tuple[tuple[int, int], SynthesizedClaim]] = []
    for entry_index, claim_index, entry, claim in _all_claims(fragment):
        reasons = deterministic_failures(claim, source_text)
        if reasons:
            failures[(entry_index, claim_index)] = "; ".join(reasons)
        else:
            pending.append(((entry_index, claim_index), claim))
    tech_failures: dict[int, dict[str, str]] = {}
    for entry_index, entry in enumerate(fragment.entries):
        bad = _tech_failures(entry.tech, source_text)
        if bad:
            tech_failures[entry_index] = bad
    return failures, pending, tech_failures


def _entailment_payload(pending: list[tuple[tuple[int, int], SynthesizedClaim]]) -> str:
    return json.dumps(
        [
            {"index": index, "claim": claim.text, "support": claim.support}
            for index, (_, claim) in enumerate(pending)
        ]
    )


def _apply_verdicts(
    content: object,
    pending: list[tuple[tuple[int, int], SynthesizedClaim]],
    failures: dict[tuple[int, int], str],
) -> None:
    if not isinstance(content, ClaimVerdicts):
        raise TypeError(f"Expected ClaimVerdicts from agent, got {type(content).__name__}")
    verdicts = {verdict.index: verdict for verdict in content.verdicts}
    for index, (key, _) in enumerate(pending):
        verdict = verdicts.get(index)
        if verdict is None or verdict.verdict != "supported":
            failures[key] = (
                verdict.reason if verdict and verdict.reason else "not confirmed by verifier"
            )
```

Replace the body of `_verify` (keep its docstring) with:

```python
    failures, pending, tech_failures = _deterministic_pass(fragment, source_text)
    if pending:
        content = entailment_agent.run(_entailment_payload(pending)).content
        _apply_verdicts(content, pending, failures)
    return failures, tech_failures
```

In `synthesize_document`, replace both inline `isinstance` checks with `_expect_fragment` (i.e. `fragment = _expect_fragment(content).model_copy(deep=True)` and `fragment = _expect_fragment(repaired).model_copy(deep=True)`). Then append the async siblings after `synthesize_document`:

```python
async def _averify(
    fragment: SynthesizedFragment,
    source_text: str,
    entailment_agent: Runner,
    *,
    sem: asyncio.Semaphore,
) -> tuple[dict[tuple[int, int], str], dict[int, dict[str, str]]]:
    failures, pending, tech_failures = _deterministic_pass(fragment, source_text)
    if pending:
        content = (await acall(entailment_agent, _entailment_payload(pending), sem=sem)).content
        _apply_verdicts(content, pending, failures)
    return failures, tech_failures


async def asynthesize_document(
    doc: SourceDoc,
    doc_text: str,
    skeleton: list[dict],
    synthesis_agent: Runner,
    entailment_agent: Runner,
    *,
    sem: asyncio.Semaphore,
) -> tuple[SynthesizedFragment, list[str]]:
    """Async sibling of synthesize_document for the fragment fan-out."""
    content = (
        await acall(synthesis_agent, compose_synthesis_input(doc_text, skeleton), sem=sem)
    ).content
    fragment = _expect_fragment(content).model_copy(deep=True)
    _apply_pinned_anchor(fragment, doc)

    failures, tech_failures = await _averify(fragment, doc_text, entailment_agent, sem=sem)
    if failures or tech_failures:
        repaired = (
            await acall(
                synthesis_agent,
                _repair_prompt(doc_text, skeleton, fragment, failures, tech_failures),
                sem=sem,
            )
        ).content
        fragment = _expect_fragment(repaired).model_copy(deep=True)
        _apply_pinned_anchor(fragment, doc)
        failures, tech_failures = await _averify(fragment, doc_text, entailment_agent, sem=sem)

    drops = _drop_failed(fragment, failures, tech_failures)
    return fragment, drops
```

- [ ] **Step 5: Fan out the walk's produce loop**

In `src/resume_agent/profile/fragments.py`:

1. Add imports: `import asyncio`, `from collections.abc import Awaitable, Callable` (replacing the bare `Callable` import), `from typing import Any`, plus

```python
from resume_agent.concurrency import gather_isolated
from resume_agent.config import get_settings
from resume_agent.llm_runner import Runner, run_with_cleanup
from resume_agent.profile.extractor import (
    PROMPT_VERSION,
    aextract_profile_facts,
    extract_profile_facts,
)
from resume_agent.profile.synthesis import (
    SYNTHESIS_PROMPT_VERSION,
    asynthesize_document,
    fragment_to_facts,
    synthesize_document,
)
```

(merge with the existing import lines; `synthesize_document`/`extract_profile_facts` stay imported only if still referenced — after this step they are not, so drop them).

1. Change `FragmentProducer`:

```python
@dataclass(frozen=True)
class FragmentProducer:
    """One extraction mode behind the fragment cache walk.

    ``produce`` is async and awaits its LLM calls through ``acall`` so the
    walk can fan documents out; ``runners`` are closed by run_with_cleanup
    when the fan-out's event loop shuts down.
    """

    selects: Callable[[SourceDoc], bool]
    expected_meta: Callable[[SourceDoc, str], dict]
    produce: Callable[[SourceDoc, str, asyncio.Semaphore], Awaitable[Produced]]
    runners: tuple[Any, ...] = ()
```

1. In `_walk_fragments`, replace the serial produce loop

```python
    for item in pending:
        try:
            produced = producer.produce(item.doc, item.text)
        except Exception as exc:
            _record_failure(result, profile_dir, item.doc, exc)
            continue
        _apply_produced(result, profile_dir, item, produced)
```

with

```python
    if pending:
        sem = asyncio.Semaphore(get_settings().llm_concurrency)
        produced_results = asyncio.run(
            run_with_cleanup(
                gather_isolated(
                    pending,
                    lambda item: producer.produce(item.doc, item.text, sem),
                ),
                *producer.runners,
            )
        )
        for item, res in zip(pending, produced_results):
            if not res.ok or res.value is None:
                _record_failure(
                    result,
                    profile_dir,
                    item.doc,
                    res.error if res.error is not None else RuntimeError("produce failed"),
                )
                continue
            _apply_produced(result, profile_dir, item, res.value)
```

1. Rewrite the two public producers:

```python
def extract_fragments(
    profile_dir: str | Path, manifest: SourceManifest, agent: Runner
) -> FragmentResult:
    """Extract literal-mode documents, reusing valid cached fragments."""

    async def _produce(doc: SourceDoc, text: str, sem: asyncio.Semaphore) -> Produced:
        facts = assign_fact_ids(await aextract_profile_facts(text, agent, sem=sem), doc.id)
        return Produced(facts=facts)

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode != "synthesis",
            expected_meta=lambda doc, sha: _literal_meta(sha),
            produce=_produce,
            runners=(agent,),
        ),
    )


def extract_synthesis_fragments(
    profile_dir: str | Path,
    manifest: SourceManifest,
    skeleton: list[dict],
    synthesis_agent: Runner,
    entailment_agent: Runner,
) -> FragmentResult:
    """Synthesize registered synthesis-mode documents, reusing valid caches."""

    async def _produce(doc: SourceDoc, text: str, sem: asyncio.Semaphore) -> Produced:
        fragment, drops = await asynthesize_document(
            doc, text, skeleton, synthesis_agent, entailment_agent, sem=sem
        )
        facts, evidence = fragment_to_facts(doc, fragment, skeleton)
        return Produced(facts=facts, evidence=evidence, drops=drops)

    return _walk_fragments(
        profile_dir,
        manifest,
        FragmentProducer(
            selects=lambda doc: doc.mode == "synthesis",
            expected_meta=_synthesis_meta,
            produce=_produce,
            runners=(synthesis_agent, entailment_agent),
        ),
    )
```

- [ ] **Step 6: Run the concurrency test, then the whole profile + build surface**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_fragments.py tests/test_profile_synthesis.py tests/test_profile_build.py tests/test_cli_profile.py tests/api -v`
Expected: all PASS. Every existing fake agent already implements `arun` (verified 2026-07-07), so the async switch is transparent to them. `_FakeAgent` objects have no `.model` attribute, so `run_with_cleanup`'s `aclose_runner` is a no-op for fakes.

- [ ] **Step 7: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/profile/extractor.py src/resume_agent/profile/synthesis.py src/resume_agent/profile/fragments.py tests/test_profile_fragments.py
git commit -m "Fans fragment production out per document with the shared LLM semaphore"
```

---

### Task 5: Scope industry normalization to touched rows

**Files:**

- Modify: `src/resume_agent/discovery/pipeline.py:98,106-193` (`run_extract` call site, `_prepare_industry_fields`, `_normalize_job_industries`)
- Test: `tests/test_discovery_pipeline.py` (existing tests are the conformance gate; append one scoping test)

**Interfaces:**

- Consumes: `_INDUSTRY_RETRY_KEY`, `_STALE_SIC_KEYS`, `canonical_industry`, `normalize_company`, `normalize_industry`, `merge_industry_taxonomy` (all already in pipeline.py).
- Produces: `_normalize_job_industries(session, classifier, taxonomy_path, batch)` — gains a required `batch: list[Job]` parameter (its only caller is `run_extract`). `_prepare_industry_fields(job, taxonomy)` return type unchanged (`str | None`), but it now assigns `job.criteria_json` **only when the rebuilt dict differs**.
- Invariant preserved: absence-as-retry — a job whose industry could not be classified keeps its `_industry_candidate` marker and is re-attempted on every future run (the scope query selects exactly those rows).

- [ ] **Step 1: Write the failing scoping test**

Append to `tests/test_discovery_pipeline.py` (reuse the file's existing engine/session fixtures and `Job` import; if it has none, build one inline with `make_engine("sqlite://")` + `init_db` + `Session(engine)`):

```python
def test_industry_normalization_skips_untouched_rows(session, tmp_path):
    from resume_agent.discovery.pipeline import _normalize_job_industries
    from resume_agent.taxonomy.industries import IndustryTaxonomy, save_industry_taxonomy

    taxonomy_path = tmp_path / "industries.json"
    save_industry_taxonomy(
        IndustryTaxonomy(aliases={"fintech": "Fintech"}, companies={}), taxonomy_path
    )

    # An already-settled row: its raw alias WOULD canonicalize if walked.
    settled = Job(
        source="greenhouse", company="OldCo", title="Engineer", jd_text="jd",
        status="shortlisted", criteria_json={"industry": "fintech"},
    )
    # A row still carrying the retry marker: must stay in scope.
    pending = Job(
        source="greenhouse", company="RetryCo", title="Engineer", jd_text="jd",
        status="shortlisted",
        criteria_json={"industry": None, "_industry_candidate": "fintech"},
    )
    session.add(settled)
    session.add(pending)
    session.commit()

    _normalize_job_industries(session, None, taxonomy_path, batch=[])
    session.commit()
    session.refresh(settled)
    session.refresh(pending)

    # Out of scope: the settled row was not rewritten.
    assert settled.criteria_json["industry"] == "fintech"
    # In scope: the pending marker resolved against the taxonomy.
    assert pending.criteria_json["industry"] == "Fintech"
    assert "_industry_candidate" not in pending.criteria_json
```

Note: `IndustryTaxonomy` construction must match its real model — check `taxonomy/industries.py` for the field names (`aliases`, `companies`); if it requires more fields, supply their defaults.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py -v -k skips_untouched`
Expected: FAIL — the current full-table walk rewrites `settled.criteria_json["industry"]` to `"Fintech"` (and the signature has no `batch` parameter — a TypeError also counts as the expected failure).

- [ ] **Step 3: Guard the assignment in \_prepare_industry_fields**

In `src/resume_agent/discovery/pipeline.py`, change the last two lines of `_prepare_industry_fields` from

```python
    job.criteria_json = criteria
    return candidate
```

to

```python
    if criteria != job.criteria_json:
        job.criteria_json = criteria
    return candidate
```

- [ ] **Step 4: Scope the walk**

Replace the signature and the two full-table walks in `_normalize_job_industries`:

```python
def _normalize_job_industries(
    session: Session,
    classifier: Runner | None,
    taxonomy_path: Path | str,
    batch: list[Job],
) -> None:
    taxonomy = load_industry_taxonomy(taxonomy_path)
    jobs = _industry_scope(session, batch)
```

(the rest of the function body keeps its exact logic, but iterates `jobs` as before — the final loop becomes:)

```python
    for job in jobs:
        _prepare_industry_fields(job, taxonomy)
        session.add(job)
```

(`session.add` of an unchanged persistent row is a no-op; the guarded assignment in Step 3 is what keeps unchanged rows out of the flush.) Add the scope helper above it:

```python
def _industry_scope(session: Session, batch: list[Job]) -> list[Job]:
    """Rows this pass can change: the batch just extracted, plus rows still
    carrying a pending retry candidate or stale SIC keys. Everything else was
    settled by a previous run and cannot be affected by a taxonomy merge."""
    criteria_text = cast(Any, Job.criteria_json).cast(String)
    revisitable = session.exec(
        select(Job).where(
            criteria_text.like(f'%"{_INDUSTRY_RETRY_KEY}"%')
            | criteria_text.like('%"sic_major"%')
        )
    ).all()
    by_id: dict[int | None, Job] = {job.id: job for job in revisitable}
    for job in batch:
        by_id.setdefault(job.id, job)
    return list(by_id.values())
```

Add the imports pipeline.py needs: `from typing import Any, cast` and `from sqlalchemy import String` (merge with existing imports; `select` is already imported from sqlmodel).

Update the sole caller in `run_extract` (pipeline.py:98):

```python
    _normalize_job_industries(session, industry_classifier, industry_taxonomy_path, batch=jobs)
```

(`jobs` is the raw-stage list `run_extract` already holds — the rows it just wrote criteria onto.)

Behavioral notes:

- SQLAlchemy's JSON serializer writes keys as `"_industry_candidate":`, so the LIKE probes match reliably on SQLite's TEXT storage of JSON columns.
- The stale-SIC sweep (`_STALE_SIC_KEYS` strip) previously rode the full-table walk; the `"sic_major"` LIKE keeps sweeping those legacy rows until none remain.
- Company-map seeding (`company_additions`) previously scanned all jobs; scoped, it seeds only from in-scope rows. Rows settled by earlier runs already contributed their company mapping when they were settled.

- [ ] **Step 5: Run the new test, then the discovery conformance suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_discovery_pipeline.py tests/test_discovery_industry.py tests/test_taxonomy_industries.py -v`
Expected: all PASS. If a pre-existing test calls `_normalize_job_industries` directly, update only its call to pass `batch=[...]` with the jobs it seeded (a signature-following edit, not a behavior edit).

- [ ] **Step 6: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "Scopes industry normalization to the extracted batch and pending retries"
```

---

### Task 6: Transactional bulk mutations behind the Board seam

**Files:**

- Modify: `src/resume_agent/tracking/repository.py:315-336,439-449` (`delete_job` splits out `delete_job_row`; `prune_run` batches)
- Modify: `src/resume_agent/services/board.py:354-407` (`bulk_apply` batches: one load, one gate, one commit)
- Test: `tests/test_services_board.py`, `tests/test_prune_run.py` (append)

**Interfaces:**

- Consumes: `progressed_job_ids(session) -> set[int]`, `job_has_progress(job, progressed) -> bool`, `utcnow()` (all already in `tracking`).
- Produces:
  - `delete_job_row(session: Session, job: Job, *, commit: bool = True) -> None` in `tracking.repository` — unguarded cascade delete; callers apply the progress gate. `delete_job(session, job_id) -> bool` keeps its guarded contract and delegates.
  - `bulk_apply(...)` — signature and `BulkResult` unchanged; now batch-loads targets, gates once, mutates in-session, commits **once** (dry-run commits nothing).
  - `prune_run(...)` — signature and `PruneReport` unchanged; archives in one commit, expires in one commit; archived rows share one `now` timestamp.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_services_board.py` (reuse the file's existing session/engine fixture and job-seeding helpers — grep for how existing bulk tests build jobs; the shape below assumes a `session` fixture and a `_job(...)` helper, adapt names to the file's own):

```python
def test_bulk_apply_commits_once(session):
    from resume_agent.services.board import BoardFilter, bulk_apply
    from resume_agent.tracking.tables import Job

    ids = []
    for i in range(3):
        job = Job(source="greenhouse", company=f"Co{i}", title="Engineer",
                  jd_text=f"jd {i}", status="shortlisted")
        session.add(job)
        session.commit()
        session.refresh(job)
        ids.append(job.id)

    commits = []
    original_commit = session.commit

    def counting_commit():
        commits.append(1)
        original_commit()

    session.commit = counting_commit  # type: ignore[method-assign]
    result = bulk_apply(
        session, board="shortlist", action="approve", scope="ids",
        board_filter=BoardFilter(), ids=ids, dry_run=False,
    )
    session.commit = original_commit  # type: ignore[method-assign]
    assert result.affected == 3
    assert len(commits) == 1


def test_bulk_apply_query_count_is_constant(session):
    from sqlalchemy import event

    from resume_agent.services.board import BoardFilter, bulk_apply
    from resume_agent.tracking.tables import Job

    def _seed(n):
        ids = []
        for i in range(n):
            job = Job(source="greenhouse", company=f"Batch{n}Co{i}", title="Engineer",
                      jd_text=f"jd {n} {i}", status="shortlisted")
            session.add(job)
            session.commit()
            session.refresh(job)
            ids.append(job.id)
        return ids

    def _selects(ids):
        counts = {"n": 0}

        def _tally(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                counts["n"] += 1

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _tally)
        try:
            bulk_apply(session, board="shortlist", action="archive", scope="ids",
                       board_filter=BoardFilter(), ids=ids, dry_run=True)
        finally:
            event.remove(engine, "before_cursor_execute", _tally)
        return counts["n"]

    small = _selects(_seed(2))
    large = _selects(_seed(10))
    assert small == large  # no per-job queries
```

Append to `tests/test_prune_run.py` (adapt to that file's fixtures):

```python
def test_prune_archives_share_one_commit_and_timestamp(session, prune_config):
    from sqlmodel import select

    from resume_agent.tracking.repository import prune_run
    from resume_agent.tracking.tables import Job

    for i in range(3):
        session.add(Job(source="greenhouse", company=f"Junk{i}", title="Engineer",
                        jd_text=f"jd {i}", status="rejected"))
    session.commit()

    commits = []
    original_commit = session.commit

    def counting_commit():
        commits.append(1)
        original_commit()

    session.commit = counting_commit  # type: ignore[method-assign]
    prune_run(session, prune_config)
    session.commit = original_commit  # type: ignore[method-assign]
    assert len(commits) <= 2  # one for archives, one for expiries

    stamps = {job.archived_at for job in session.exec(select(Job)).all() if job.archived_at}
    assert len(stamps) <= 1  # all archived rows share the run's `now`
```

(`prune_config` must be a config whose rules archive rejected zero-progress jobs — mirror however the file's existing tests construct `PruneConfig`. If it has a helper/fixture, use it; the assertion structure is what matters.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py -k "commits_once or query_count" tests/test_prune_run.py -k one_commit -v`
Expected: `test_bulk_apply_commits_once` FAILS (3 commits); `test_bulk_apply_query_count_is_constant` FAILS (per-job `get_job` + `has_progress`); the prune test FAILS (one commit per archived row).

- [ ] **Step 3: Split delete_job and batch prune_run in repository.py**

In `src/resume_agent/tracking/repository.py`, replace `delete_job` with:

```python
def delete_job_row(session: Session, job: Job, *, commit: bool = True) -> None:
    """Cascade-delete a job's children (FK-safe order) then the job itself.

    Unguarded: callers must have already applied the has_progress gate —
    delete_job() remains the guarded single-job entry point.
    """
    for model in (CoverLetter, Application, ResumeVersion):
        for child in session.exec(select(model).where(model.job_id == job.id)).all():
            session.delete(child)
    session.delete(job)
    if commit:
        session.commit()


def delete_job(session: Session, job_id: int) -> bool:
    """Hard-delete a zero-progress job and its children in one transaction.

    Returns False (and changes nothing) if the job has user progress or is
    already gone. The progress check is the single irreversible-path guard.
    """
    if has_progress(session, job_id):
        return False
    job = session.get(Job, job_id)
    if job is None:
        return False
    delete_job_row(session, job)
    return True
```

Replace `prune_run` with:

```python
def prune_run(
    session: Session, config: PruneConfig, now: datetime | None = None
) -> PruneReport:
    """Archive matching junk and expire old archived rows. Returns the tally.

    Archives land in one commit (sharing this run's ``now`` stamp); expiries
    land in a second. The batched progress gate mirrors delete_job's guard.
    """
    now = now or utcnow()
    to_archive, to_expire, skipped = _prune_plan(session, config, now)
    for row in to_archive:
        job = session.get(Job, row.job_id)
        if job is not None:
            job.archived_at = now
            session.add(job)
    session.commit()
    progressed = progressed_job_ids(session)
    for row in to_expire:
        job = session.get(Job, row.job_id)
        if job is None or job_has_progress(job, progressed):
            continue
        delete_job_row(session, job, commit=False)
    session.commit()
    return _prune_report(to_archive, to_expire, skipped, config, now)
```

(Intended behavior change: archived rows previously got per-row `utcnow()` stamps from `archive_job`; they now share the run's `now`. If a pre-existing prune test asserts distinct stamps, that expectation is what this task changes — this is the one sanctioned test edit.)

- [ ] **Step 4: Batch bulk_apply in board.py**

In `src/resume_agent/services/board.py`, add imports (merge with existing lines):

```python
from sqlmodel import Session, select

from resume_agent.tracking.repository import (
    ...existing names...,
    delete_job_row,
    job_has_progress,
    progressed_job_ids,
)
from resume_agent.tracking.tables import Application, Job, JobStatus, utcnow
```

Replace the body of `bulk_apply` (signature and docstring position unchanged):

```python
    target_ids = _target_ids(
        session, board=board, scope=scope, board_filter=board_filter, ids=ids,
    )
    id_col = cast(Any, Job.id)
    jobs = {
        job.id: job
        for job in session.exec(select(Job).where(id_col.in_(target_ids))).all()
    }
    progressed = progressed_job_ids(session)
    affected = 0
    skipped = 0
    reasons: Counter[str] = Counter()
    progress_guarded = action in {"delete", "approve", "setStatus"}

    for job_id in target_ids:
        job = jobs.get(job_id)
        if job is None:
            skipped += 1
            reasons["missing"] += 1
            continue
        if progress_guarded and job_has_progress(job, progressed):
            skipped += 1
            reasons["hasProgress"] += 1
            continue

        if dry_run:
            affected += 1
            continue

        if action == "archive":
            job.archived_at = utcnow()
            session.add(job)
        elif action == "restore":
            job.archived_at = None
            session.add(job)
        elif action == "delete":
            delete_job_row(session, job, commit=False)
        elif action == "approve":
            job.status = JobStatus.approved.value
            session.add(job)
        elif action == "setStatus":
            if status is None:
                raise ValueError("status is required for setStatus")
            job.status = status
            session.add(job)
        else:
            raise ValueError(f"Unknown bulk action {action!r}")
        affected += 1

    if not dry_run:
        session.commit()
    return BulkResult(affected=affected, skipped=skipped, reasons=dict(reasons))
```

Add `from typing import Any, cast` if `cast` is not already imported in board.py (`Any` is). Note: `select(...).where(id_col.in_(target_ids))` is bounded by SQLite's variable limit (32,766 since 3.32) — far above any realistic board selection; do not add chunking.

The single-job mutation seam (`set_stage`, `set_archived`, `delete`, `upsert_application`) stays exactly as-is — it serves the per-job routes.

- [ ] **Step 5: Run the new tests, then the board/prune/API conformance suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_board.py tests/test_prune_run.py tests/test_services_prune.py tests/test_cli_prune.py tests/test_repository.py tests/api -v`
Expected: all PASS (only the sanctioned prune-timestamp expectation may need the edit flagged in Step 3).

- [ ] **Step 6: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
git add src/resume_agent/tracking/repository.py src/resume_agent/services/board.py tests/test_services_board.py tests/test_prune_run.py
git commit -m "Batches board bulk mutations and prune into single-commit transactions"
```

---

### Task 7: Documentation sweep

**Files:**

- Modify: `CLAUDE.md` (touched claims)
- Modify: `CONTEXT.md` (new domain terms for the deepened modules)

**Interfaces:** none — docs only.

- [ ] **Step 1: Update CLAUDE.md**

1. Hot-paths table — add one row after the `profile/synthesis.py` row:
   `| src/resume_agent/profile/fragments.py | Fragment cache walk: one cache/staleness policy, per-mode producers (literal, synthesis), concurrent per-doc production |`
2. "Known design notes" — append: "**Profile build fans out per document.** `extract_fragments` / `extract_synthesis_fragments` share one cache walk; production runs concurrently via `gather_isolated` with the permit acquired only in `llm_runner.acall`. The CLI and API both build through `services/profile_build.run_corpus_build` — the single place the facts+matrix bound-artifact pair is written."
3. "Known design notes" — append: "**File SQLite runs WAL.** `make_engine` sets `journal_mode=WAL`, `busy_timeout=30000`, `synchronous=NORMAL` on every file-backed connection so the API's writer threads wait instead of failing with 'database is locked'."
4. "Known design notes" — append: "**Industry normalization is scoped.** `_normalize_job_industries` walks only the just-extracted batch plus rows with a pending `_industry_candidate` (or legacy SIC keys) — never the whole table."
5. "Board seam" description in the CONTEXT/CLAUDE board notes — append one sentence where `bulk_apply` behavior is described (or to the Known design notes if it is not): "Bulk actions are transactional: one batched load + `progressed_job_ids` gate, one commit; `delete_job_row` is the unguarded cascade shared with `delete_job` and prune."

- [ ] **Step 2: Add the new terms to CONTEXT.md**

Append a new section after "Runs & skill classification":

```markdown
## Profile corpus

**Fragment cache walk**:
The deep seam over the source manifest that owns per-document caching — sha
check, manifest bump, meta match, cache hit, error → stale fallback, atomic
save, and the status vocabulary (`cached` / `extracted` / `source-changed` /
`stale:` / `failed:`). `_walk_fragments`; both extraction modes run through it.
_Avoid_: extraction loop, cache layer

**Fragment producer**:
One extraction mode behind the Fragment cache walk: which docs it selects, the
meta dict that keys their cache entries, and the async produce step
(doc, text → Produced). The profile-corpus counterpart of a discovery
Producer — the genuine per-mode variation that stays outside the walk.
_Avoid_: extractor (reserve for the literal-mode agent), handler

**Produced fragment**:
What a Fragment producer yields for one document: the fragment's `facts`, an
optional `evidence` sidecar (synthesis only), and optional verification
`drops`. `Produced` in `profile/fragments.py`.
_Avoid_: extraction result, payload
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md CONTEXT.md
git commit -m "Documents the fragment walk seam, WAL engines, scoped industry pass, and transactional bulk"
```

---

## Final verification (after all tasks)

- [ ] Run: `.venv/Scripts/python.exe -m pytest -q` — expected: full suite PASS.
- [ ] Run: `ruff check` — expected: clean.
- [ ] Run: `git diff main --stat -- contracts/` — expected: **empty** (wire contract untouched).
- [ ] Use superpowers:requesting-code-review before merging the branch.

## Self-review notes (already applied)

- **Coverage:** review candidates — WAL→Task 1, single build seam→Task 2, fragment walk→Task 3, concurrent production→Task 4, industry scoping→Task 5, transactional bulk→Task 6; docs drift→Task 7.
- **Type consistency:** `Produced`/`FragmentProducer`/`_Pending`/`_record_failure`/`_apply_produced`/`_save_produced`/`_literal_meta`/`_synthesis_meta` defined in Task 3 are the exact names Task 4's diff edits; `aextract_profile_facts`/`asynthesize_document` signatures in Task 4's producers match their definitions; `delete_job_row`/`job_has_progress`/`progressed_job_ids` used in Task 6's board code match repository.py; `run_corpus_build(reporter=None, *, profile_dir, github_username, facts_out)` in Task 2's CLI call matches the service change and the router's existing positional-reporter call.
- **Known judgment calls:** (a) Task 4 keeps sync `synthesize_document`/`extract_profile_facts` alongside the async siblings — tests exercise them directly and the diff stays additive. (b) Task 5 keeps sweeping legacy SIC rows via a second LIKE probe rather than dropping the migration behavior. (c) Task 6 sanctions exactly one test-expectation change (shared prune archive timestamp) and calls it out inline. (d) Task 1 applies pragmas to all file SQLite engines including test tmp DBs — WAL sidecar files are harmless in tmp dirs.
