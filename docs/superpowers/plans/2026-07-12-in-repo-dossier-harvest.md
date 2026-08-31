# In-Repo Dossier Harvesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sync_github_sources` discovers `*dossier*.md` files in a repo's root, materializes each as its own project-mode source doc (one Project fact per dossier), and replaces the README virtual doc for that repo.

**Architecture:** All changes live in `src/resume_tailor_harness/profile/github_harvest.py`. Dossier candidates are picked from the existing root listing by filename, validated by `repo_url:` frontmatter matching the harvested repo, and written verbatim (30 KB cap) as `github--<repo>--<stem>.md` docs with `mode="project"`, `origin="github"`. The extraction pipeline (`extract_project_fragments`), manifest, and upload-supersession logic are untouched — a repo with N dossiers yields N docs, hence N Project facts.

**Tech Stack:** Python 3.13, httpx (`MockTransport` in tests), pytest.

**Spec:** `docs/superpowers/specs/2026-07-12-in-repo-dossier-harvest-design.md`

## Global Constraints

- Per dossier file cap: 30 KB (`_MAX_FILE_BYTES`, existing constant).
- Max 5 dossiers per repo (`_MAX_DOSSIERS = 5`), alphabetical by casefolded filename; overflow recorded in `HarvestReport.warnings`.
- Repo root listing only — no subdirectory calls.
- A dossier whose `repo_url` does not normalize to the harvested repo's URL is skipped with a warning; missing/invalid frontmatter is skipped silently.
- Zero valid dossiers → behavior byte-for-byte identical to today (README virtual doc).
- Manual-upload supersession unchanged: `dossier_repo_urls` scans only `origin == "upload"` docs.
- Test command: `.venv/Scripts/python.exe -m pytest` (offline; agents and browser faked). Lint: `ruff check`.
- Windows: use forward slashes in commands; git commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Dossier candidate selection from the root listing

**Files:**

- Modify: `src/resume_tailor_harness/profile/github_harvest.py` (near `_pick_doc_entries`, line ~85)
- Test: `tests/test_profile_github_harvest.py`

**Interfaces:**

- Produces: `_MAX_DOSSIERS: int = 5`; `_is_dossier_name(name: str) -> bool`; `_pick_dossier_entries(listing: list[dict]) -> tuple[list[str], list[str]]` returning `(selected, overflow)` — both deterministically alphabetical by casefolded name (then original spelling), `selected` capped at `_MAX_DOSSIERS`. `_pick_doc_entries` remains unchanged so zero valid dossiers preserve today's fallback behavior exactly.
- Consumes: existing `_CONTEXT_DOC_NAMES`, listing dicts shaped `{"name": str, "type": "file"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_github_harvest.py`:

```python
from resume_tailor_harness.profile.github_harvest import (
    _pick_doc_entries,
    _pick_dossier_entries,
)


def listing(*names: str) -> list[dict]:
    return [{"name": name, "type": "file"} for name in names]


def test_pick_dossier_entries_matches_caps_and_sorts():
    selected, overflow = _pick_dossier_entries(
        listing(
            "README.md",
            "zeta-dossier.md",
            "Alpha-Dossier.md",
            "dossier-notes.md",
            "b-dossier.md",
            "c-dossier.md",
            "d-dossier.md",
            "dossier.txt",
            "CHANGELOG.md",
        )
    )
    assert selected == [
        "Alpha-Dossier.md",
        "b-dossier.md",
        "c-dossier.md",
        "d-dossier.md",
        "dossier-notes.md",
    ]
    assert overflow == ["zeta-dossier.md"]


def test_pick_dossier_entries_ignores_directories():
    selected, overflow = _pick_dossier_entries(
        [{"name": "x-dossier.md", "type": "dir"}]
    )
    assert selected == [] and overflow == []


def test_pick_doc_entries_keeps_existing_readme_fallback_behavior():
    names = _pick_doc_entries(listing("README.md", "readme-dossier.md", "claude.md"))
    assert names == ["readme-dossier.md", "README.md", "claude.md"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py -k dossier_entries_or_doc_entries -v` — actually run the three by name:

`.venv/Scripts/python.exe -m pytest "tests/test_profile_github_harvest.py::test_pick_dossier_entries_matches_caps_and_sorts" "tests/test_profile_github_harvest.py::test_pick_dossier_entries_ignores_directories" "tests/test_profile_github_harvest.py::test_pick_doc_entries_excludes_dossier_names" -v`

Expected: ImportError (`_pick_dossier_entries` not defined).

- [ ] **Step 3: Implement**

In `src/resume_tailor_harness/profile/github_harvest.py`, add below `_CONTEXT_DOC_NAMES`:

```python
_MAX_DOSSIERS = 5


def _is_dossier_name(name: str) -> bool:
    folded = name.casefold()
    return folded.endswith(".md") and "dossier" in folded
```

Leave `_pick_doc_entries` unchanged and add `_pick_dossier_entries`:

```python
def _pick_dossier_entries(listing: list[dict]) -> tuple[list[str], list[str]]:
    """Return (selected, overflow) dossier-named root files, alphabetical and capped."""
    names = sorted(
        (
            name
            for entry in listing
            if entry.get("type") == "file"
            and isinstance((name := entry.get("name")), str)
            and _is_dossier_name(name)
        ),
        key=lambda name: (name.casefold(), name),
    )
    return names[:_MAX_DOSSIERS], names[_MAX_DOSSIERS:]
```

- [ ] **Step 4: Run tests to verify they pass**

Same command as Step 2. Expected: 3 passed. Then run the whole file: `.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py -v` — all pass (no regression).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/github_harvest.py tests/test_profile_github_harvest.py
git commit -m "Adds dossier candidate selection to GitHub harvest listing

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Dossier filenames and conservative failure keep-set

**Files:**

- Modify: `src/resume_tailor_harness/profile/github_harvest.py` (`_filename_for`, line ~191)
- Test: `tests/test_profile_github_harvest.py`

**Interfaces:**

- Produces: `_unique_filename(candidate: str, identity: str, profile_dir, *, force_suffix: bool = False) -> str` (shared deterministic conflict resolution); `_dossier_filename(repo: dict, entry: str, profile_dir, *, force_suffix: bool = False) -> str` → `github--<repo-slug>--<entry-stem-slug>.md`, with stable suffixes based on the original entry name when sanitized dossier stems collide; `_github_docs_for(profile_dir, repo_url: str | None) -> set[str]` → filenames of github-origin docs whose frontmatter `repo_url` normalizes to `repo_url`.
- Consumes: `_SAFE_REPO_NAME`, `GITHUB_DOC_PREFIX`, `load_manifest`, `doc_path`, `frontmatter_repo_url`, `normalize_repo_url` (all already imported).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_github_harvest.py`:

```python
from resume_tailor_harness.profile.github_harvest import _dossier_filename, _github_docs_for


def test_dossier_filename_slugs_and_dodges_upload_conflicts(tmp_path):
    profile_dir = profile(tmp_path)
    value = repo("My.Repo")
    assert (
        _dossier_filename(value, "API Gateway-dossier.md", profile_dir)
        == "github--my.repo--api-gateway-dossier.md"
    )
    conflict = tmp_path / "github--my.repo--api-gateway-dossier.md"
    conflict.write_text("upload", encoding="utf-8")
    add_source(profile_dir, conflict)
    resolved = _dossier_filename(value, "API Gateway-dossier.md", profile_dir)
    assert resolved.startswith("github--my.repo--api-gateway-dossier-")
    assert resolved != "github--my.repo--api-gateway-dossier.md"


def test_github_docs_for_matches_by_frontmatter_url(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(standard_handler([repo("mine"), repo("other")]))
    sync_github_sources(profile_dir, "me", client=gh)
    http.close()
    assert _github_docs_for(profile_dir, "github.com/me/mine") == {
        f"{GITHUB_DOC_PREFIX}mine.md"
    }
    assert _github_docs_for(profile_dir, None) == set()


def test_dossier_filename_keeps_sanitized_stem_collisions_distinct(tmp_path):
    profile_dir = profile(tmp_path)
    value = repo("mono")
    first = _dossier_filename(
        value, "api dossier.md", profile_dir, force_suffix=True
    )
    second = _dossier_filename(
        value, "api-dossier.md", profile_dir, force_suffix=True
    )
    assert first.startswith(f"{GITHUB_DOC_PREFIX}mono--api-dossier-")
    assert second.startswith(f"{GITHUB_DOC_PREFIX}mono--api-dossier-")
    assert second != first
```

Note: `normalize_repo_url` (in `src/resume_tailor_harness/profile/github_ingest.py`) strips scheme and casefolds, so `"https://github.com/me/mine"` → `"github.com/me/mine"` — the expected value above is exact.

- [ ] **Step 2: Run tests to verify they fail**

`.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py::test_dossier_filename_slugs_and_dodges_upload_conflicts tests/test_profile_github_harvest.py::test_github_docs_for_matches_by_frontmatter_url -v`

Expected: ImportError (`_dossier_filename` not defined).

- [ ] **Step 3: Implement**

Refactor `_filename_for` to share conflict resolution, and add the two helpers:

```python
def _slug(value: object, fallback: str) -> str:
    name = value if isinstance(value, str) else fallback
    return _SAFE_REPO_NAME.sub("-", name.casefold()).strip("-") or fallback


def _unique_filename(
    candidate: str,
    identity: str,
    profile_dir: str | Path,
    *,
    force_suffix: bool = False,
) -> str:
    conflict = next(
        (
            doc
            for doc in load_manifest(profile_dir).docs
            if doc.filename.casefold() == candidate.casefold() and doc.origin != "github"
        ),
        None,
    )
    if conflict is None and not force_suffix:
        return candidate
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    stem, _, _ = candidate.rpartition(".md")
    return f"{stem}-{suffix}.md"


def _filename_for(repo: dict, profile_dir: str | Path) -> str:
    slug = _slug(repo.get("name"), "repo")
    identity = normalize_repo_url(repo.get("html_url")) or slug
    return _unique_filename(f"{GITHUB_DOC_PREFIX}{slug}.md", identity, profile_dir)


def _dossier_filename(
    repo: dict,
    entry: str,
    profile_dir: str | Path,
    *,
    force_suffix: bool = False,
) -> str:
    repo_slug = _slug(repo.get("name"), "repo")
    entry_slug = _slug(Path(entry).stem, "dossier")
    identity = f"{normalize_repo_url(repo.get('html_url')) or repo_slug}#{entry}"
    return _unique_filename(
        f"{GITHUB_DOC_PREFIX}{repo_slug}--{entry_slug}.md",
        identity,
        profile_dir,
        force_suffix=force_suffix,
    )


def _github_docs_for(profile_dir: str | Path, repo_url: str | None) -> set[str]:
    """Filenames of github-origin docs belonging to repo_url, by frontmatter identity."""
    if repo_url is None:
        return set()
    names: set[str] = set()
    for doc in load_manifest(profile_dir).docs:
        if doc.origin != "github":
            continue
        try:
            url = normalize_repo_url(frontmatter_repo_url(doc_path(profile_dir, doc).read_bytes()))
        except OSError:
            continue
        if url == repo_url:
            names.add(doc.filename)
    return names
```

`_filename_for`'s observable behavior is unchanged — existing tests must still pass.

- [ ] **Step 4: Run tests to verify they pass**

`.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py -v` — all pass.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/github_harvest.py tests/test_profile_github_harvest.py
git commit -m "Adds dossier filename scheme and per-repo doc lookup helpers

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Harvest-loop integration — fetch, validate, replace, keep

**Files:**

- Modify: `src/resume_tailor_harness/profile/github_harvest.py` (`sync_github_sources`, lines ~259-315)
- Test: `tests/test_profile_github_harvest.py`

**Interfaces:**

- Consumes: `_pick_dossier_entries` (Task 1), `_dossier_filename` / `_github_docs_for` (Task 2), existing `_truncate_utf8`, `_atomic_write`, `render_virtual_doc`, `add_source`, `sources_dir`.
- Produces: `_write_source(profile_dir, filename: str, data: bytes, repo_name: str, report: HarvestReport, kept: set[str]) -> None` — shared write+register block used by both README and dossier paths. Dossier docs registered `mode="project"`, `origin="github"`, verbatim content capped at `_MAX_FILE_BYTES`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_github_harvest.py`:

```python
DOSSIER = "---\nrepo_url: https://github.com/me/{repo}\n---\n# Project: {name}\n"


def mono_handler(repos: list[dict], files: dict[str, str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/users/me/repos":
            return httpx.Response(200, json=repos)
        if path.endswith("/contents"):
            return httpx.Response(
                200, json=[{"name": name, "type": "file"} for name in files]
            )
        for name, text in files.items():
            if path.endswith(f"/contents/{name}"):
                return httpx.Response(200, text=text)
        if path.endswith("/languages"):
            return httpx.Response(200, json={"Python": 100})
        return httpx.Response(404)

    return handler


def dossier(repo_name: str, project: str) -> str:
    return DOSSIER.format(repo=repo_name, name=project)


def test_dossiers_replace_readme_doc_and_yield_one_doc_each(tmp_path):
    profile_dir = profile(tmp_path)
    plain, plain_http = github(standard_handler([repo("mono")]))
    sync_github_sources(profile_dir, "me", client=plain)
    plain_http.close()
    assert any(
        doc.filename == f"{GITHUB_DOC_PREFIX}mono.md"
        for doc in load_manifest(profile_dir).docs
    )

    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "README.md": "# readme",
                "api-dossier.md": dossier("mono", "API Gateway"),
                "ui-dossier.md": dossier("mono", "UI Dashboard"),
            },
        )
    )
    report = sync_github_sources(profile_dir, "me", client=gh)
    filenames = {doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"}
    assert filenames == {
        f"{GITHUB_DOC_PREFIX}mono--api-dossier.md",
        f"{GITHUB_DOC_PREFIX}mono--ui-dossier.md",
    }
    assert f"{GITHUB_DOC_PREFIX}mono.md" in report.removed
    docs = [doc for doc in load_manifest(profile_dir).docs if doc.origin == "github"]
    assert all(doc.mode == "project" for doc in docs)
    assert "me/mono" in report.languages

    again = sync_github_sources(profile_dir, "me", client=gh)
    assert again.written == []
    http.close()


def test_dossier_without_frontmatter_falls_back_to_readme(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {"README.md": "# readme", "notes-dossier.md": "# just notes"},
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    filenames = {doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"}
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono.md"}
    content = (profile_dir / "sources" / f"{GITHUB_DOC_PREFIX}mono.md").read_text(encoding="utf-8")
    assert "notes-dossier" not in content
    http.close()


def test_foreign_repo_url_dossier_skipped_with_warning(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {"README.md": "# readme", "stolen-dossier.md": dossier("elsewhere", "X")},
        )
    )
    report = sync_github_sources(profile_dir, "me", client=gh)
    filenames = {doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"}
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono.md"}
    assert any("stolen-dossier.md" in warning for warning in report.warnings)
    http.close()


def test_dossier_overflow_warns_and_keeps_first_five(tmp_path):
    profile_dir = profile(tmp_path)
    files = {"README.md": "# readme"}
    for letter in "abcdef":
        files[f"{letter}-dossier.md"] = dossier("mono", letter)
    gh, http = github(mono_handler([repo("mono")], files))
    report = sync_github_sources(profile_dir, "me", client=gh)
    github_docs = [doc for doc in load_manifest(profile_dir).docs if doc.origin == "github"]
    assert len(github_docs) == 5
    assert not any("f-dossier" in doc.filename for doc in github_docs)
    assert any("f-dossier.md" in warning for warning in report.warnings)
    http.close()


def test_per_repo_failure_keeps_previous_dossier_docs(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")], {"api-dossier.md": dossier("mono", "API Gateway")}
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    http.close()

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/me/repos":
            return httpx.Response(200, json=[repo("mono")])
        return httpx.Response(500)

    broken, broken_http = github(failing)
    report = sync_github_sources(profile_dir, "me", client=broken)
    assert "mono" in report.failures
    assert report.removed == []
    filenames = {doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"}
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono--api-dossier.md"}
    broken_http.close()


def test_dossier_content_written_verbatim_and_capped(tmp_path):
    profile_dir = profile(tmp_path)
    text = dossier("mono", "API Gateway") + "x" * 40_000
    gh, http = github(mono_handler([repo("mono")], {"api-dossier.md": text}))
    sync_github_sources(profile_dir, "me", client=gh)
    written = (
        profile_dir / "sources" / f"{GITHUB_DOC_PREFIX}mono--api-dossier.md"
    ).read_bytes()
    assert written.startswith(b"---\nrepo_url: https://github.com/me/mono")
    assert len(written) <= 30_000
    http.close()
```

- [ ] **Step 2: Run tests to verify they fail**

`.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py -k "dossiers_replace or falls_back_to_readme or foreign_repo_url or overflow_warns or keeps_previous_dossier or verbatim_and_capped" -v`

Expected: all 6 FAIL (dossier files are currently invisible to the harvest, so manifests contain only the README doc).

- [ ] **Step 3: Implement**

In `github_harvest.py`, extract the write/register block into a module-level helper (place above `sync_github_sources`):

```python
def _write_source(
    profile_dir: str | Path,
    filename: str,
    data: bytes,
    repo_name: str,
    report: HarvestReport,
    kept: set[str],
) -> None:
    target = sources_dir(profile_dir) / filename
    if not target.exists() or target.read_bytes() != data:
        _atomic_write(target, data)
        report.written.append(filename)
    kept.add(filename)
    if not any(doc.filename == filename for doc in load_manifest(profile_dir).docs):
        created = add_source(profile_dir, target, mode="project", origin="github")
        if created.origin != "github" or created.filename != filename:
            target.unlink(missing_ok=True)
            report.failures[repo_name] = "virtual document duplicated an upload source"
            kept.discard(filename)
```

Then rewrite the per-repo body of the `for item in selected:` loop:

```python
        for item in selected:
            name = item.get("name") if isinstance(item.get("name"), str) else ""
            owner_value = item.get("owner")
            login = owner_value.get("login") if isinstance(owner_value, dict) else None
            owner = login if isinstance(login, str) else username
            repo_url = normalize_repo_url(item.get("html_url"))
            if not name or repo_url in dossiers:
                continue
            try:
                listing = github.fetch_root_listing(owner, name)
                dossier_entries, overflow = _pick_dossier_entries(listing)
                for skipped in overflow:
                    report.warnings.append(
                        f"{name}: dossier {skipped} skipped (max {_MAX_DOSSIERS} per repo)"
                    )
                dossier_files: list[tuple[str, str]] = []
                for entry in dossier_entries:
                    text = github.fetch_raw_file(owner, name, entry)
                    if text is None:
                        continue
                    entry_url = normalize_repo_url(
                        frontmatter_repo_url(text.encode("utf-8"))
                    )
                    if entry_url is None:
                        continue
                    if entry_url != repo_url:
                        report.warnings.append(
                            f"{name}: dossier {entry} targets a different repository; skipped"
                        )
                        continue
                    dossier_files.append((entry, text))
                files: list[tuple[str, str]] = []
                if not dossier_files:
                    for entry in _pick_doc_entries(listing):
                        text = github.fetch_raw_file(owner, name, entry)
                        if text is not None:
                            files.append((entry, text))
                    if not files:
                        continue
                languages = github.fetch_languages(owner, name)
            except httpx.HTTPStatusError as error:
                if _is_rate_limited(error):
                    report.warnings.append(_rate_limit_warning())
                    stopped_early = True
                    break
                report.failures[name] = str(error)
                kept |= _github_docs_for(profile_dir, repo_url)
                continue
            except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
                report.failures[name] = str(error)
                kept |= _github_docs_for(profile_dir, repo_url)
                continue

            full_name = item.get("full_name")
            report.languages[
            full_name if isinstance(full_name, str) else f"{owner}/{name}"
            ] = languages
            if dossier_files:
                slug_counts: dict[str, int] = {}
                for entry, _text in dossier_files:
                    entry_slug = _slug(Path(entry).stem, "dossier")
                    slug_counts[entry_slug] = slug_counts.get(entry_slug, 0) + 1
                for entry, text in dossier_files:
                    entry_slug = _slug(Path(entry).stem, "dossier")
                    _write_source(
                        profile_dir,
                        _dossier_filename(
                            item,
                            entry,
                            profile_dir,
                            force_suffix=slug_counts[entry_slug] > 1,
                        ),
                        _truncate_utf8(text, _MAX_FILE_BYTES).encode("utf-8"),
                        name,
                        report,
                        kept,
                    )
            else:
                _write_source(
                    profile_dir,
                    _filename_for(item, profile_dir),
                    render_virtual_doc(item, files, languages).encode("utf-8"),
                    name,
                    report,
                    kept,
                )
```

Notes for the implementer:

- The old `filename = _filename_for(item, profile_dir)` pre-computation and `kept.add(filename)` failure lines are replaced by `kept |= _github_docs_for(profile_dir, repo_url)`, which conservatively keeps README **and** dossier docs from prior syncs (both carry `repo_url` frontmatter).
- The trailing cleanup loop (`doc.origin == "github" and doc.filename not in kept` → remove) is untouched; it is what deletes the stale `github--<repo>.md` when dossiers now exist, and stale dossier docs when a dossier is deleted upstream.
- `_remove_local_superseded` and `dossier_repo_urls` are untouched.

- [ ] **Step 4: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest` — expected: all pass (new tests plus zero regressions; the 5 pre-existing harvest tests must still pass unchanged).
Run: `ruff check` — expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/github_harvest.py tests/test_profile_github_harvest.py
git commit -m "Harvests in-repo dossier files as per-project GitHub sources

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Upload supersession covers harvested dossier docs

**Files:**

- Test: `tests/test_profile_github_harvest.py` (behavioral regression only — no production change expected)

**Interfaces:**

- Consumes: `mono_handler`/`dossier` helpers (Task 3), existing `dossier_repo_urls` / `_remove_local_superseded` code paths.

- [ ] **Step 1: Write the test**

```python
def test_uploaded_dossier_supersedes_all_harvested_repo_docs(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "api-dossier.md": dossier("mono", "API Gateway"),
                "ui-dossier.md": dossier("mono", "UI Dashboard"),
            },
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    assert sum(doc.origin == "github" for doc in load_manifest(profile_dir).docs) == 2

    upload = tmp_path / "mine-dossier.md"
    upload.write_text(dossier("mono", "Authoritative"), encoding="utf-8")
    add_source(profile_dir, upload)

    report = sync_github_sources(profile_dir, "me", client=gh)
    assert sorted(report.superseded) == [
        f"{GITHUB_DOC_PREFIX}mono--api-dossier.md",
        f"{GITHUB_DOC_PREFIX}mono--ui-dossier.md",
    ]
    assert not any(doc.origin == "github" for doc in load_manifest(profile_dir).docs)
    http.close()
```

- [ ] **Step 2: Run it**

`.venv/Scripts/python.exe -m pytest tests/test_profile_github_harvest.py::test_uploaded_dossier_supersedes_all_harvested_repo_docs -v`

Expected: PASS with no production change (`_remove_local_superseded` already removes every github-origin doc whose frontmatter URL matches an upload, and the loop `continue` skips re-harvest). If it FAILS, the defect is real — fix inside `sync_github_sources` per the spec ("upload wins whole repo") rather than weakening the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_profile_github_harvest.py
git commit -m "Covers upload supersession over harvested dossier docs

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: project-dossier skill monorepo clause and developer docs

**Files:**

- Modify: `.claude/skills/project-dossier/SKILL.md`
- Modify: `CLAUDE.md` (Known design notes → "GitHub depth is two-tier; dossiers win" bullet)

**Interfaces:**

- Consumes: behavior shipped in Tasks 1-3 (root-only discovery, `*dossier*.md` naming, shared `repo_url`).

- [ ] **Step 1: Update SKILL.md**

In `.claude/skills/project-dossier/SKILL.md`, after the "Output contract" intro paragraph (before the frontmatter block), add:

```markdown
When the repository contains multiple distinct projects (a monorepo), write
one `<project-slug>-dossier.md` per project at the repository root. Every
dossier uses the same `repo_url` (the repository's canonical URL); each file
describes exactly one project in its `# Project:` section.
```

And extend the "Handoff" section after the existing command block:

```markdown
Committing dossiers to the repository root also works without the manual
`profile add`: `resume-tailor-harness profile sync-github` discovers root files named
`*dossier*.md` (up to 5 per repository, 30 KB each), validates their
`repo_url` frontmatter, and ingests each as its own project source, replacing
the auto-harvested README document. A manual upload still overrides
everything harvested for that repository.
```

- [ ] **Step 2: Update CLAUDE.md**

In the "GitHub depth is two-tier; dossiers win" bullet, after the sentence ending "supersedes the auto-document for the same normalized repository URL.", insert:

```markdown
Harvest also discovers root files named `*dossier*.md` (max 5 per repo, 30 KB
each) whose `repo_url` frontmatter matches the repo; each becomes its own
`github--<repo>--<stem>.md` project source and replaces that repo's README
virtual doc. Manual uploads still supersede all harvested docs for the repo.
```

- [ ] **Step 3: Verify and commit**

Run: `.venv/Scripts/python.exe -m pytest` and `ruff check` — both clean (docs-only change; confirms nothing drifted).

```bash
git add .claude/skills/project-dossier/SKILL.md CLAUDE.md
git commit -m "Documents in-repo dossier harvesting in skill and dev reference

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
