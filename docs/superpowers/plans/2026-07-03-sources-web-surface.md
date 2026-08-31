# Profile Sources Web Surface (Phase B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dashboard manages the profile source corpus — upload with mode/anchor, edit, remove, rebuild with a live run — replacing the wizard-era single-resume build path with the corpus build.

**Architecture:** New corpus-backed endpoints under `/api/profile/sources` (+ `/api/profile/skeleton` for anchor dropdowns) live beside the existing wizard `/api/profile/documents` surface. `POST /api/profile/build` switches from the legacy single-resume `build_profile` to `build_corpus_profile` (auto-registering the wizard's latest resume as the primary source when the corpus is empty, mirroring the CLI's `migrate_legacy`). The web settings Profile page swaps its `DocumentManager` for a corpus `SourceManager` and renders the build report from the run result.

**Tech Stack:** FastAPI + CamelModel schemas, `openapi-typescript` contract regen (`bash scripts/gen_ts_client.sh`), React + TanStack Query + zustand run store, vitest.

**Spec:** `docs/superpowers/specs/2026-07-03-supporting-material-synthesis-design.md` (§10)
**Depends on:** Phase A plan `2026-07-03-synthesis-ingest-pipeline.md` (corpus `mode`/`anchor`, `update_source`, `profile_skeleton`, `BuildReport.anchor_decisions/verification_drops`, agent builders) — all Phase A tasks must be merged first.

## Global Constraints

- Backend tests offline: `.venv/Scripts/python.exe -m pytest`; lint `ruff check`. Web tests: `cd web && npx vitest run`.
- Wire format is **camelCase** via `CamelModel`; every route change regenerates `contracts/openapi.json` + `contracts/ts/api.ts` with `bash scripts/gen_ts_client.sh` — `tests/api/test_openapi_contract.py` is the drift gate and must pass in the same commit.
- Errors use the `{ "error": { code, message, details? } }` envelope via `ApiException`.
- Long ops are Runs: kind `"profile-build"`, `singleton_key="profile-build"` (already enforced — a second build while one is active is rejected by `RunManager.submit`).
- Run workers never touch the request DB session; the profile build is file-based and needs no session.
- Commit messages: end with the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_01XuwaqQLRg5q574SxcLmDck` trailers.

---

### Task 1: Sources + skeleton API endpoints

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/profile.py`
- Modify: `src/resume_tailor_harness/api/routers/profile.py`
- Modify: `contracts/openapi.json`, `contracts/ts/api.ts` (regenerated)
- Test: `tests/api/test_profile_sources.py` (new)

**Interfaces:**

- Consumes (Phase A): `corpus.load_manifest / add_source / update_source / remove_source / _UNSET`, `fragments.fragment_cache_status`, `synthesis.profile_skeleton`, `store.load_facts`.
- Produces (wire, camelCase): `SourceOut{id, filename, mode, primary, anchor, addedAt, fragmentStatus}`, `SourcePatch{mode?, anchor?, primary?}`, `SkeletonEntryOut{id, kind, label}`; routes `GET/POST /api/profile/sources`, `PATCH/DELETE /api/profile/sources/{doc_id}`, `GET /api/profile/skeleton`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_profile_sources.py`:

```python
"""Corpus-backed sources CRUD + anchor skeleton."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.models.profile import Contact, Experience, ProfileFacts, Project
from resume_tailor_harness.profile.store import save_facts


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c, tmp_path / "data"


def _upload(client, name="resume.txt", content=b"experience text", **fields):
    return client.post(
        "/api/profile/sources",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
        data=fields,
    )


def test_upload_and_list_with_defaults(client):
    c, _ = client
    resp = _upload(c)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == "literal"
    assert body["primary"] is True  # first source auto-promotes

    deck = _upload(c, name="deck.md", content=b"Cut latency 30%", mode="synthesis")
    assert deck.status_code == 201
    assert deck.json()["mode"] == "synthesis"

    listed = c.get("/api/profile/sources").json()
    assert [s["filename"] for s in listed] == ["resume.txt", "deck.md"]
    assert all("fragmentStatus" in s for s in listed)


def test_first_source_cannot_be_synthesis(client):
    c, _ = client
    resp = _upload(c, name="deck.md", mode="synthesis")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert c.get("/api/profile/sources").json() == []


def test_bad_extension_and_oversize_rejected(client):
    c, _ = client
    assert _upload(c, name="malware.exe").status_code == 422
    assert _upload(c, content=b"x" * (15 * 1024 * 1024 + 1)).status_code == 422


def test_patch_mode_anchor_primary(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="deck.md", mode="synthesis").json()["id"]

    patched = c.patch(f"/api/profile/sources/{doc_id}", json={"anchor": "exp1"})
    assert patched.status_code == 200
    assert patched.json()["anchor"] == "exp1"

    cleared = c.patch(f"/api/profile/sources/{doc_id}", json={"anchor": None})
    assert cleared.json()["anchor"] is None

    literal = c.patch(f"/api/profile/sources/{doc_id}", json={"mode": "literal"})
    assert literal.json()["mode"] == "literal"

    promoted = c.patch(f"/api/profile/sources/{doc_id}", json={"primary": True})
    assert promoted.json()["primary"] is True

    assert c.patch("/api/profile/sources/nope", json={}).status_code == 404


def test_patch_synthesis_primary_rejected(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="deck.md", mode="synthesis").json()["id"]
    resp = c.patch(f"/api/profile/sources/{doc_id}", json={"primary": True})
    assert resp.status_code == 422


def test_delete_source(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="notes.md").json()["id"]
    assert c.delete(f"/api/profile/sources/{doc_id}").status_code == 204
    assert c.delete(f"/api/profile/sources/{doc_id}").status_code == 404


def test_skeleton_lists_anchor_candidates(client):
    c, data_dir = client
    assert c.get("/api/profile/skeleton").json() == []

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer")],
        projects=[Project(id="proj1", name="Engine")],
    )
    save_facts(facts, data_dir / "profile" / "facts.json")

    rows = c.get("/api/profile/skeleton").json()
    assert {"id": "exp1", "kind": "experience", "label": "Acme — Engineer"} in rows
    assert {"id": "proj1", "kind": "project", "label": "Engine"} in rows
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_sources.py -v`
Expected: FAIL — 404s (routes don't exist).

- [ ] **Step 3: Implement**

Add to `src/resume_tailor_harness/api/schemas/profile.py`:

```python
class SourceOut(CamelModel):
    id: str
    filename: str
    mode: str
    primary: bool
    anchor: str | None = None
    added_at: str
    fragment_status: str


class SourcePatch(CamelModel):
    mode: str | None = None
    anchor: str | None = None
    primary: bool | None = None


class SkeletonEntryOut(CamelModel):
    id: str
    kind: str
    label: str
```

In `src/resume_tailor_harness/api/routers/profile.py`, add imports:

```python
import re
import tempfile
from pathlib import Path

from resume_tailor_harness.api.schemas.profile import (
    DocumentOut,
    SkeletonEntryOut,
    SourceOut,
    SourcePatch,
)
from resume_tailor_harness.profile.corpus import (
    _UNSET,
    add_source,
    load_manifest,
    remove_source,
    update_source,
)
from resume_tailor_harness.profile.fragments import fragment_cache_status
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.profile.synthesis import profile_skeleton
```

and the endpoints:

```python
_MAX_SOURCE_BYTES = 15 * 1024 * 1024
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _profile_dir(request: Request) -> Path:
    return request.app.state.data_dir / "profile"


def _source_out(profile_dir: Path, doc) -> SourceOut:
    return SourceOut(
        id=doc.id, filename=doc.filename, mode=doc.mode, primary=doc.primary,
        anchor=doc.anchor, added_at=doc.added_at,
        fragment_status=fragment_cache_status(profile_dir, doc),
    )


@router.get("/profile/sources", response_model=list[SourceOut])
def list_sources(request: Request):
    profile_dir = _profile_dir(request)
    return [_source_out(profile_dir, doc) for doc in load_manifest(profile_dir).docs]


@router.post("/profile/sources", response_model=SourceOut, status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    mode: str | None = Form(None),
    anchor: str | None = Form(None),
    primary: bool = Form(False),
):
    content = await file.read()
    if len(content) > _MAX_SOURCE_BYTES:
        raise ApiException(422, "VALIDATION_ERROR", "File exceeds the 15 MB limit")
    name = _UNSAFE_CHARS.sub("_", Path(file.filename or "upload").name) or "upload"
    profile_dir = _profile_dir(request)
    try:
        # add_source copies the staged file into sources/ under its original name.
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / name
            staged.write_bytes(content)
            doc = add_source(
                profile_dir, staged, primary=primary,
                mode=mode, anchor=anchor,  # type: ignore[arg-type]
            )
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    return _source_out(profile_dir, doc)


@router.patch("/profile/sources/{doc_id}", response_model=SourceOut)
def patch_source(doc_id: str, payload: SourcePatch, request: Request):
    profile_dir = _profile_dir(request)
    anchor = payload.anchor if "anchor" in payload.model_fields_set else _UNSET
    try:
        doc = update_source(
            profile_dir, doc_id, mode=payload.mode,  # type: ignore[arg-type]
            anchor=anchor, primary=payload.primary,
        )
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    if doc is None:
        raise ApiException(404, "NOT_FOUND", f"No source '{doc_id}'")
    return _source_out(profile_dir, doc)


@router.delete("/profile/sources/{doc_id}", status_code=204)
def delete_source(doc_id: str, request: Request, purge: bool = False):
    try:
        doc = remove_source(_profile_dir(request), doc_id, purge=purge)
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    if doc is None:
        raise ApiException(404, "NOT_FOUND", f"No source '{doc_id}'")


@router.get("/profile/skeleton", response_model=list[SkeletonEntryOut])
def get_skeleton(request: Request):
    facts_path = _profile_dir(request) / "facts.json"
    if not facts_path.exists():
        return []
    facts = load_facts(facts_path)
    rows: list[SkeletonEntryOut] = []
    for row in profile_skeleton(facts):
        label = (
            f"{row['company']} — {row['title']}"
            if row["kind"] == "experience"
            else row["name"]
        )
        rows.append(SkeletonEntryOut(id=row["id"], kind=row["kind"], label=label))
    return rows
```

Note: `update_source` requires a Phase A change if `primary=False` demotion was disallowed there — it was (only `primary=True` acts), which matches `SourcePatch.primary: bool | None` where `None`/`False` are no-ops.

- [ ] **Step 4: Run tests, regenerate the contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_sources.py -v`
Expected: PASS.

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS (contract files updated in-tree).

- [ ] **Step 5: Run the full suite and commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: PASS.

```bash
git add src/resume_tailor_harness/api/schemas/profile.py src/resume_tailor_harness/api/routers/profile.py contracts/ tests/api/test_profile_sources.py
git commit -m "Serves the profile source corpus over the API with anchor skeleton"
```

---

### Task 2: Build run uses the corpus pipeline

**Files:**

- Modify: `src/resume_tailor_harness/services/profile_build.py`
- Modify: `src/resume_tailor_harness/api/routers/profile.py` (`launch_profile_build`)
- Test: `tests/api/test_profile_build_run.py`

**Interfaces:**

- Consumes: Phase A `build_corpus_profile(..., synthesis_agent, entailment_agent)`, agent builders, `matrix.build_matrix/load_overrides/save_matrix`, `taxonomy.clusters.load_cluster_map`, `corpus.add_source/load_manifest`.
- Produces: `profile_build.run_corpus_build(reporter, *, profile_dir: Path, github_username: str | None, facts_out: str | Path) -> dict` returning camelCase-keyed report (`experiences`, `projects`, `docStatus`, `conflicts`, `anchorDecisions`, `verificationDrops`, `inferred`, `warnings`). `run_profile_build` is deleted (its only caller was this router).

- [ ] **Step 1: Update the tests (failing first)**

In `tests/api/test_profile_build_run.py`, replace both monkeypatched names and add an auto-registration test:

```python
def test_build_with_non_anthropic_key_launches_run(tmp_path, monkeypatch):
    """profile build uses Settings.mid_model, which may be a non-Anthropic
    provider (see llm_runner.split_provider) — any configured LLM key, not
    specifically ANTHROPIC_API_KEY, must satisfy the precondition."""
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-oai-test-abcd1234\nMID_MODEL=openai:gpt-4.1\n",
                    encoding="utf-8")
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=env, data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
            data={"docType": "resume"},
        )
        from resume_tailor_harness.services import profile_build

        monkeypatch.setattr(
            profile_build, "run_corpus_build",
            lambda reporter, **kwargs: {"experiences": 1, "projects": 0, "warnings": []},
        )
        resp = client.post("/api/profile/build")
        assert resp.status_code == 202


def test_build_launches_run(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )

    from resume_tailor_harness.services import profile_build

    def fake_run(reporter, **kwargs):
        return {"experiences": 2, "projects": 1, "warnings": []}

    monkeypatch.setattr(profile_build, "run_corpus_build", fake_run)
    resp = client.post("/api/profile/build")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "profile-build"
    assert body["runId"]


def test_build_registers_wizard_resume_as_primary_source(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )
    from resume_tailor_harness.services import profile_build

    monkeypatch.setattr(
        profile_build, "run_corpus_build",
        lambda reporter, **kwargs: {"experiences": 0, "projects": 0, "warnings": []},
    )
    assert client.post("/api/profile/build").status_code == 202

    sources = client.get("/api/profile/sources").json()
    assert len(sources) == 1
    assert sources[0]["primary"] is True and sources[0]["mode"] == "literal"


def test_build_with_registered_sources_skips_document_store(client, monkeypatch):
    """A corpus source satisfies the precondition without any wizard document."""
    import io as _io

    client.post(
        "/api/profile/sources",
        files={"file": ("resume.txt", _io.BytesIO(b"experience"), "text/plain")},
    )
    from resume_tailor_harness.services import profile_build

    monkeypatch.setattr(
        profile_build, "run_corpus_build",
        lambda reporter, **kwargs: {"experiences": 0, "projects": 0, "warnings": []},
    )
    assert client.post("/api/profile/build").status_code == 202
```

Keep `test_build_without_resume_is_400` and `test_build_without_key_is_400` unchanged.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_build_run.py -v`
Expected: FAIL — `run_corpus_build` doesn't exist; `/api/profile/sources` empty after build.

- [ ] **Step 3: Implement**

Replace the body of `src/resume_tailor_harness/services/profile_build.py`:

```python
"""Profile build use-case: source corpus (+ GitHub) -> facts.json + matrix.json."""

from __future__ import annotations

from pathlib import Path

from resume_tailor_harness.profile.store import save_facts


def run_corpus_build(
    reporter,
    *,
    profile_dir: Path,
    github_username: str | None,
    facts_out: str | Path,
) -> dict:
    from resume_tailor_harness.profile.build import build_corpus_profile
    from resume_tailor_harness.profile.inference import build_inference_agent
    from resume_tailor_harness.profile.matrix import build_matrix, load_overrides, save_matrix
    from resume_tailor_harness.profile.merge import build_bullet_dedup_agent
    from resume_tailor_harness.profile.synthesis import (
        build_entailment_agent,
        build_synthesis_agent,
    )
    from resume_tailor_harness.taxonomy.clusters import load_cluster_map

    reporter.begin(3, "Extracting and merging source documents")
    facts, report = build_corpus_profile(
        profile_dir,
        github_username=github_username,
        dedup_agent=build_bullet_dedup_agent(),
        inference_agent=build_inference_agent(),
        synthesis_agent=build_synthesis_agent(),
        entailment_agent=build_entailment_agent(),
    )
    reporter.step(1, label="Saving facts.json")
    save_facts(facts, str(facts_out))
    reporter.step(2, label="Building skill matrix")
    matrix = build_matrix(
        facts,
        load_cluster_map(Path(profile_dir) / "cluster_map.json"),
        load_overrides(Path(profile_dir) / "overrides.yaml"),
    )
    save_matrix(matrix, Path(facts_out).with_name("matrix.json"))
    reporter.step(3, label="Saved matrix.json")
    return {
        "experiences": len(facts.experience),
        "projects": len(facts.projects),
        "docStatus": dict(report.doc_status),
        "conflicts": list(report.conflicts),
        "anchorDecisions": list(report.anchor_decisions),
        "verificationDrops": list(report.verification_drops),
        "inferred": list(report.inferred_added),
        "warnings": list(report.warnings),
    }
```

(`run_profile_build`, `build_profile`, and `validate_profile` imports go away — the corpus build's own report replaces the legacy validation warnings.)

In `src/resume_tailor_harness/api/routers/profile.py`, rework `launch_profile_build`'s precondition block (keep the LLM-key gate comment and check exactly as-is), replacing the `resume_path` logic:

```python
    profile_dir = _profile_dir(request)
    manifest = load_manifest(profile_dir)
    if not manifest.docs:
        resume_path = _docs(request).latest_resume_path()
        if resume_path is None:
            raise ApiException(400, "SETUP_INCOMPLETE",
                               "Upload a resume document before building the profile")
        # One-time migration mirroring the CLI's migrate_legacy: the wizard's
        # newest resume becomes the corpus primary.
        add_source(profile_dir, resume_path, primary=True)
    profile_cfg = request.app.state.config_store.get("profile")
    github_username = profile_cfg.github_username
    facts_out = request.app.state.data_dir / "profile" / "facts.json"

    def work(reporter):
        return profile_build.run_corpus_build(
            reporter, profile_dir=profile_dir,
            github_username=github_username, facts_out=facts_out,
        )
```

- [ ] **Step 4: Run the full suite, regen contract if OpenAPI changed, commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: PASS (this task adds no routes, so the contract should be unchanged; if the drift gate complains, run `bash scripts/gen_ts_client.sh` and include the regenerated files).

```bash
git add src/resume_tailor_harness/services/profile_build.py src/resume_tailor_harness/api/routers/profile.py tests/api/test_profile_build_run.py
git commit -m "Runs the web profile build through the corpus pipeline"
```

---

### Task 3: Web source manager (hooks + component + page swap)

**Files:**

- Create: `web/src/features/profile-sources/use-sources.ts`
- Create: `web/src/features/profile-sources/SourceManager.tsx`
- Create: `web/src/features/profile-sources/SourceManager.test.tsx`
- Modify: `web/src/features/settings/pages/ProfileSettingsPage.tsx` (swap `DocumentManager` → `SourceManager`)

**Interfaces:**

- Consumes: Task 1 endpoints via the regenerated `web/src/lib/api/schema.ts`; `api/getToken/unwrap` from `@/lib/api/client` (same pattern as `use-documents.ts`).
- Produces: `ProfileSource` type, hooks `useSources() / useUploadSource() / usePatchSource() / useDeleteSource() / useSkeleton()`, `<SourceManager />`. The wizard's `DocumentManager` stays untouched (setup flow still uses `/api/profile/documents`).

- [ ] **Step 1: Write the hooks**

Create `web/src/features/profile-sources/use-sources.ts`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, getToken, unwrap } from "@/lib/api/client";

export type ProfileSource = {
  id: string;
  filename: string;
  mode: "literal" | "synthesis";
  primary: boolean;
  anchor: string | null;
  addedAt: string;
  fragmentStatus: string;
};

export type SkeletonEntry = { id: string; kind: string; label: string };

export function useSources() {
  return useQuery({
    queryKey: ["profile-sources"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/sources", {} as never)) as Promise<
        ProfileSource[]
      >,
  });
}

export function useSkeleton() {
  return useQuery({
    queryKey: ["profile-skeleton"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/skeleton", {} as never)) as Promise<
        SkeletonEntry[]
      >,
  });
}

async function postSource(file: File, mode?: string): Promise<ProfileSource> {
  const form = new FormData();
  form.append("file", file);
  if (mode) form.append("mode", mode);
  const headers: HeadersInit = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${window.location.origin}/api/profile/sources`, {
    method: "POST",
    body: form,
    headers,
  });
  const body = await resp.json();
  if (!resp.ok) throw new Error(body?.error?.message ?? "Upload failed");
  return body as ProfileSource;
}

export function useUploadSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, mode }: { file: File; mode?: string }) =>
      postSource(file, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-sources"] });
      toast.success("Source added");
    },
    onError: (err: Error) => toast.error(err.message),
  });
}

export function usePatchSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...patch
    }: { id: string } & Partial<
      Pick<ProfileSource, "mode" | "anchor" | "primary">
    >) =>
      unwrap(
        api.PATCH("/api/profile/sources/{doc_id}", {
          params: { path: { doc_id: id } },
          body: patch,
        } as never),
      ) as Promise<ProfileSource>,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-sources"] }),
    onError: (err: Error) => toast.error(err.message),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/profile/sources/{doc_id}", {
          params: { path: { doc_id: id } },
        } as never),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-sources"] }),
    onError: (err: Error) => toast.error(err.message),
  });
}
```

- [ ] **Step 2: Write the failing component test**

Create `web/src/features/profile-sources/SourceManager.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sources: [
    {
      id: "r1",
      filename: "resume.pdf",
      mode: "literal",
      primary: true,
      anchor: null,
      addedAt: "2026-07-03",
      fragmentStatus: "cached",
    },
    {
      id: "d1",
      filename: "deck.pptx",
      mode: "synthesis",
      primary: false,
      anchor: null,
      addedAt: "2026-07-03",
      fragmentStatus: "missing",
    },
  ],
  skeleton: [{ id: "exp1", kind: "experience", label: "Acme — Engineer" }],
  patch: vi.fn(),
  remove: vi.fn(),
  upload: vi.fn(),
}));

vi.mock("./use-sources", () => ({
  useSources: () => ({ data: mocks.sources, isLoading: false }),
  useSkeleton: () => ({ data: mocks.skeleton }),
  useUploadSource: () => ({ mutate: mocks.upload, isPending: false }),
  usePatchSource: () => ({ mutate: mocks.patch, isPending: false }),
  useDeleteSource: () => ({ mutate: mocks.remove, isPending: false }),
}));

import { SourceManager } from "./SourceManager";

describe("SourceManager", () => {
  it("lists sources with mode and primary markers", () => {
    render(<SourceManager />);
    expect(screen.getByText("resume.pdf")).toBeInTheDocument();
    expect(screen.getByText("deck.pptx")).toBeInTheDocument();
    expect(screen.getByText(/primary/i)).toBeInTheDocument();
  });

  it("changes a source's anchor through the skeleton dropdown", async () => {
    render(<SourceManager />);
    const anchorSelect = screen.getByLabelText(/anchor for deck.pptx/i);
    await userEvent.selectOptions(anchorSelect, "exp1");
    expect(mocks.patch).toHaveBeenCalledWith({ id: "d1", anchor: "exp1" });
  });

  it("deletes a source", async () => {
    render(<SourceManager />);
    await userEvent.click(
      screen.getByRole("button", { name: /remove deck.pptx/i }),
    );
    expect(mocks.remove).toHaveBeenCalledWith("d1");
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npx vitest run src/features/profile-sources`
Expected: FAIL — `SourceManager` module not found.

- [ ] **Step 4: Implement the component and swap it into the page**

Create `web/src/features/profile-sources/SourceManager.tsx` (plain semantic controls — native `select` keeps the anchor/mode editors accessible and easily testable; match surrounding Tailwind utility styling):

```tsx
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import {
  useDeleteSource,
  usePatchSource,
  useSkeleton,
  useSources,
  useUploadSource,
} from "./use-sources";

const MODES = ["literal", "synthesis"] as const;

export function SourceManager() {
  const { data: sources, isLoading } = useSources();
  const { data: skeleton } = useSkeleton();
  const upload = useUploadSource();
  const patch = usePatchSource();
  const remove = useDeleteSource();
  const fileInput = useRef<HTMLInputElement>(null);

  if (isLoading || !sources) return <Skeleton className="h-32 w-full" />;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">Source documents</div>
          <p className="text-sm text-muted-foreground">
            Resumes extract literally; decks and write-ups are synthesized and
            verified against their own text.
          </p>
        </div>
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,.pptx,.xlsx,.html"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate({ file });
            e.target.value = "";
          }}
        />
        <Button
          variant="outline"
          disabled={upload.isPending}
          onClick={() => fileInput.current?.click()}
        >
          Add document
        </Button>
      </div>
      <ul className="flex flex-col divide-y rounded-md border">
        {sources.map((source) => (
          <li key={source.id} className="flex flex-wrap items-center gap-3 p-3">
            <span className="min-w-40 text-sm font-medium">
              {source.filename}
            </span>
            {source.primary ? (
              <span className="rounded bg-muted px-2 py-0.5 text-xs">
                primary
              </span>
            ) : (
              <select
                aria-label={`mode for ${source.filename}`}
                className="rounded border bg-background p-1 text-xs"
                value={source.mode}
                onChange={(e) =>
                  patch.mutate({
                    id: source.id,
                    mode: e.target.value as "literal" | "synthesis",
                  })
                }
              >
                {MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </select>
            )}
            {source.mode === "synthesis" ? (
              <select
                aria-label={`anchor for ${source.filename}`}
                className="rounded border bg-background p-1 text-xs"
                value={source.anchor ?? ""}
                onChange={(e) =>
                  patch.mutate({
                    id: source.id,
                    anchor: e.target.value || null,
                  })
                }
              >
                <option value="">auto-anchor</option>
                {(skeleton ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.label}
                  </option>
                ))}
              </select>
            ) : null}
            <span className="ml-auto text-xs text-muted-foreground">
              {source.fragmentStatus}
            </span>
            {!source.primary ? (
              <Button
                variant="ghost"
                size="sm"
                aria-label={`remove ${source.filename}`}
                onClick={() => remove.mutate(source.id)}
              >
                Remove
              </Button>
            ) : null}
          </li>
        ))}
        {sources.length === 0 ? (
          <li className="p-3 text-sm text-muted-foreground">
            No sources yet — add your resume first; it becomes the primary.
          </li>
        ) : null}
      </ul>
    </div>
  );
}
```

In `web/src/features/settings/pages/ProfileSettingsPage.tsx`, replace the `DocumentManager` import and usage:

```tsx
import { SourceManager } from "@/features/profile-sources/SourceManager";
```

and swap `<DocumentManager />` for `<SourceManager />` (delete the now-unused `DocumentManager` import; the component itself stays for the setup wizard).

- [ ] **Step 5: Run web tests and commit**

Run: `cd web && npx vitest run src/features/profile-sources src/features/settings`
Expected: PASS.

```bash
git add web/src/features/profile-sources/ web/src/features/settings/pages/ProfileSettingsPage.tsx
git commit -m "Manages profile corpus sources from the settings page"
```

---

### Task 4: Build report panel + end-to-end verification

**Files:**

- Create: `web/src/features/profile-sources/BuildReportPanel.tsx`
- Create: `web/src/features/profile-sources/BuildReportPanel.test.tsx`
- Modify: `web/src/features/settings/pages/ProfileSettingsPage.tsx`

**Interfaces:**

- Consumes: `useRunStore` from `@/lib/runs/store` (run `result` carries Task 2's camelCase report keys); Task 3's page layout.
- Produces: `<BuildReportPanel />` rendering the newest completed `profile-build` run's report.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/profile-sources/BuildReportPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";

import { BuildReportPanel } from "./BuildReportPanel";

describe("BuildReportPanel", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("renders nothing without a completed build", () => {
    const { container } = render(<BuildReportPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows anchors, drops, and warnings from the run result", () => {
    useRunStore.getState().upsert({
      runId: "r1",
      kind: "profile-build",
      status: "succeeded",
      percent: 100,
      phase: "done",
      current: 3,
      total: 3,
      etaText: null,
      result: {
        experiences: 3,
        projects: 2,
        anchorDecisions: ["deck-1: +2 bullets on Acme/Engineer"],
        verificationDrops: [
          "deck-1: 'Cut latency 45%' — number '45%' not in source",
        ],
        warnings: ["skill inference failed: boom"],
      },
    });
    render(<BuildReportPanel />);
    expect(
      screen.getByText(/\+2 bullets on Acme\/Engineer/),
    ).toBeInTheDocument();
    expect(screen.getByText(/45%/)).toBeInTheDocument();
    expect(screen.getByText(/skill inference failed/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npx vitest run src/features/profile-sources/BuildReportPanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `web/src/features/profile-sources/BuildReportPanel.tsx`:

```tsx
import { useRunStore } from "@/lib/runs/store";

type BuildReport = {
  experiences?: number;
  projects?: number;
  anchorDecisions?: string[];
  verificationDrops?: string[];
  conflicts?: string[];
  warnings?: string[];
};

function Section({
  title,
  lines,
  tone,
}: {
  title: string;
  lines: string[];
  tone?: "warn";
}) {
  if (lines.length === 0) return null;
  return (
    <div>
      <div className="text-xs font-medium uppercase text-muted-foreground">
        {title}
      </div>
      <ul
        className={`mt-1 flex flex-col gap-0.5 text-sm ${tone === "warn" ? "text-destructive" : ""}`}
      >
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export function BuildReportPanel() {
  const runs = useRunStore((s) => s.runs);
  const latest = Object.values(runs)
    .filter((run) => run.kind === "profile-build" && run.status === "succeeded")
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))[0];
  if (!latest?.result) return null;
  const report = latest.result as BuildReport;

  return (
    <div className="flex flex-col gap-3 rounded-md border p-3">
      <div className="text-sm font-medium">
        Last build: {report.experiences ?? 0} experiences,{" "}
        {report.projects ?? 0} projects
      </div>
      <Section title="Anchor decisions" lines={report.anchorDecisions ?? []} />
      <Section
        title="Dropped claims"
        lines={report.verificationDrops ?? []}
        tone="warn"
      />
      <Section title="Conflicts" lines={report.conflicts ?? []} />
      <Section title="Warnings" lines={report.warnings ?? []} tone="warn" />
    </div>
  );
}
```

In `ProfileSettingsPage.tsx`, render `<BuildReportPanel />` directly below the rebuild-button row:

```tsx
import { BuildReportPanel } from "@/features/profile-sources/BuildReportPanel";
```

```tsx
      </div>
      <BuildReportPanel />
    </div>
  );
```

- [ ] **Step 4: Full verification and commit**

Run, in order:

1. `cd web && npx vitest run` — all web tests pass.
2. `cd web && npm run build` — typecheck + build clean.
3. `.venv/Scripts/python.exe -m pytest` — backend green.
4. `ruff check` — clean.

```bash
git add web/src/features/profile-sources/ web/src/features/settings/pages/ProfileSettingsPage.tsx
git commit -m "Surfaces the profile build report on the settings page"
```

---

## Final verification

- [ ] `.venv/Scripts/python.exe -m pytest && ruff check` — green.
- [ ] `cd web && npx vitest run && npm run build` — green.
- [ ] `bash scripts/gen_ts_client.sh` produces no diff (contracts committed in sync).
- [ ] Manual smoke (optional, needs an API key): `resume-tailor-harness serve`, open Settings → Profile — upload a deck, set its anchor, rebuild, watch the run and report panel.
