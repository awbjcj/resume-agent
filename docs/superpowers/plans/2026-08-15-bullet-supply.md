# Bullet Supply Implementation Plan

> **Execution:** Implement directly with red-green-refactor TDD. This implementation is deliberately inline; do not delegate tasks to subagents.

**Goal:** Make the Profile Coach able to actually raise a role's bullet supply — its elicited bullets must land on the role they describe, its agenda must be driven by measured gaps, and its questions must be grounded in the user's own unmined documents.

**Architecture:** A coach note gains a deterministic `owner_id` and is written to the corpus as `mode="synthesis"` with `anchor=<owner_id>`, which routes it through the existing pinned-anchor pipeline that forces `stub.id` to the anchor target and merges by id — bypassing the `_same_experience` heuristic that a coach note cannot satisfy. The opening agenda is seeded in code from Spec A's `owner_depth()` rather than invented by the model. Documents that contributed zero bullets become bounded question material.

**Tech Stack:** Python 3, pydantic v2, FastAPI, Typer CLI, pytest (offline — all agent calls faked), ruff.

## Implementation audit amendment (2026-08-15)

The approved design specification is authoritative. The following corrections
supersede any conflicting detail in the task text below:

- Write the `approve_draft()` anchored/unanchored behavior test before changing
  note intake. The existing merge-only regression is useful coverage, but it
  cannot be the red test because pinned synthesis merge already works.
- A seeded topic describes the **source supply** gap, not a rendered count:
  its explanation says the owner has `{source_total} of {target}` source
  bullets and that the resume can only use facts the profile holds.
- `unmined_sources()` counts every `FactItem.source_ref` in `ProfileFacts`, not
  only selected top-level collections. Its bounded context includes the
  required policy sentence, truncates a document rather than dropping the
  boundary document, and degrades unreadable input to an empty optional block.
- Keep the 12 KB cap inclusive of the fixed header in production. Tests using
  smaller injected budgets may exercise header-only degradation rather than
  require an excerpt that cannot fit safely.
- `CoachTopicOut.ownerId` is an additive API-contract parity field only; no
  new web UI is introduced. Model-added topics remain unanchored and preserve
  the literal-mode `_same_experience` behavior exactly.
- Replace live coach/user-data/API-spend acceptance with offline fixture tests.
  Any real coach session is opt-in manual acceptance and not part of the suite.

## DEPENDENCY: Spec A must ship first

This plan calls `owner_depth()`, `evidence_owners()`, `OwnerRef`, and `SUPPLY_TARGET` from `src/resume_agent/profile/depth.py`. **That module does not exist yet.** It is created by Spec A:

- Spec: `docs/superpowers/specs/2026-08-15-bullet-depth-design.md`
- Plan: `docs/superpowers/plans/2026-08-15-bullet-depth.md` (Tasks 6 and 8 create `profile/depth.py`)

**Tasks 1–4 are independent of Spec A and can ship first.** They touch only the coach topic model, note intake, and merge — Task 4 in particular fixes a live defect and has standalone value.

**Tasks 5–9 are blocked on Spec A.** Each carries a blocked marker naming what it needs:

| Task | Needs from Spec A |
| --- | --- |
| 5 | `owner_depth`, `OwnerSupply`, `SUPPLY_TARGET` (A Task 8) |
| 6 | Task 5 |
| 7 | `evidence_owners` (A Task 6) **and** `Project.highlights: list[Bullet]` (A Task 2) — before A, a highlight is a bare `str` with no `source_ref`, so "which document produced this bullet" is unanswerable for projects |
| 8 | `owner_depth`, `SUPPLY_TARGET`, and Task 7 |
| 9 | everything |

## Global Constraints

- Tests run offline with no API key and no network: `.venv/Scripts/python.exe -m pytest`. All agent calls are faked.
- Lint with `ruff check` — must be clean before every commit.
- `pyproject.toml` sets `asyncio_mode = "auto"`; an `async def test_*` needs no `@pytest.mark.asyncio`.
- **Fact-lock is absolute.** A coach note is never a claim source. Its bullets must trace to the user's own words.
- **Unmined document text is question material, never claimable fact.** This rule must appear verbatim in the prompt that carries the block. Without it the coach reads a *target* ("reduce reporting effort by ≥50%") and drafts a note asserting it as an *outcome*.
- **Backward compatibility.** Stored coach session JSON must still load — `owner_id` defaults to `""`. Stored `sources.json` manifests must still validate.
- **An unanchored note keeps today's behavior exactly.** Model-added topics carry no `owner_id`; their notes stay `mode="literal"` and merge through `_same_experience` unchanged.
- Deterministic ground-truth blocks are never wrapped in `prompt_blocks.untrusted()`. The unmined block is the user's own uploaded documents, not third-party text.

## File Structure

**Modified**
| File | Change |
| --- | --- |
| `src/resume_agent/profile/coach_store.py:17-23` | `CoachTopic.owner_id` |
| `src/resume_agent/profile/coach.py:92-99` | `_make_topic` carries `owner_id` |
| `src/resume_agent/profile/coach.py:111-140` | `normalize_opening` accepts seeded topics |
| `src/resume_agent/profile/coach.py:288` | `profile_overview` states target + aspects |
| `src/resume_agent/profile/intake.py:25-38` | `_stage_and_add` / `add_note_source` take `anchor` |
| `src/resume_agent/services/profile_coach.py:149-183` | `run_opening_turn` seeds the agenda |
| `src/resume_agent/services/profile_coach.py:301-325` | `approve_draft` passes the anchor |
| `src/resume_agent/api/schemas/coach.py:26-32` | `CoachTopicOut.owner_id` |
| `src/resume_agent/profile/depth.py` | `depth_topics`, `UnminedSource`, `unmined_sources`, `unmined_block` |

**Created**
| File | Responsibility |
| --- | --- |
| `tests/test_coach_anchored_notes.py` | The end-to-end anchoring regression |
| `tests/test_profile_depth_topics.py` | Agenda seeding |
| `tests/test_profile_unmined.py` | Unmined-source selection and the bounded block |

**No new module.** `depth_topics` and `unmined_sources` join `profile/depth.py` because they answer the same question it already owns — what does the profile hold, and where is it short. Spec A establishes that module as the supply-side seam; splitting supply measurement across two files would put the coach's input in one place and the CLI's in another.

---

### Task 1: `CoachTopic.owner_id`

**Files:**
- Modify: `src/resume_agent/profile/coach_store.py:17-23`
- Modify: `src/resume_agent/profile/coach.py:92-99`
- Modify: `src/resume_agent/api/schemas/coach.py:26-32`
- Test: `tests/test_coach_store.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `CoachTopic.owner_id: str` (default `""`), and `CoachTopicOut.owner_id` serialized as `ownerId`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coach_store.py (append)
from resume_agent.profile.coach import NewTopic, _make_topic
from resume_agent.profile.coach_store import CoachTopic


def test_owner_id_defaults_to_empty_so_stored_sessions_still_load():
    topic = CoachTopic.model_validate(
        {"id": "t1", "gap": "thin role", "status": "open"}
    )
    assert topic.owner_id == ""


def test_make_topic_leaves_owner_id_empty_for_model_proposed_topics():
    """A model-added topic has no owner, so its note stays unanchored."""
    topic = _make_topic(1, NewTopic(gap="tell me about scale", why_it_matters="x"))
    assert topic.owner_id == ""


def test_make_topic_accepts_an_explicit_owner_for_seeded_topics():
    topic = _make_topic(
        3, NewTopic(gap="thin role", why_it_matters="x"), owner_id="exp_umich"
    )
    assert topic.id == "t3"
    assert topic.owner_id == "exp_umich"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_coach_store.py -v`
Expected: FAIL with `AttributeError: 'CoachTopic' object has no attribute 'owner_id'`

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/profile/coach_store.py`:

```python
class CoachTopic(ExtensibleModel):
    id: str = ""
    gap: str = ""
    why_it_matters: str = ""
    related_ref: str = ""
    # The evidence owner this topic is about, set ONLY on deterministically
    # seeded topics. It becomes the corpus anchor when the topic's note is
    # approved, which is what makes elicited bullets land on the right role.
    # A model-proposed topic leaves it empty and its note stays unanchored.
    owner_id: str = ""
    status: Literal["open", "drafted", "saved", "skipped"] = "open"
    note_doc_id: str | None = None
```

In `src/resume_agent/profile/coach.py`:

```python
def _make_topic(
    index: int, topic: NewTopic | TopicUpdate, *, owner_id: str = ""
) -> CoachTopic:
    return CoachTopic(
        id=f"t{index}",
        gap=topic.gap.strip(),
        why_it_matters=topic.why_it_matters.strip(),
        related_ref=topic.related_ref.strip(),
        owner_id=owner_id,
    )
```

In `src/resume_agent/api/schemas/coach.py`, add to `CoachTopicOut` after `related_ref`:

```python
    owner_id: str = ""
```

`CamelModel` serializes it as `ownerId`. Verify `session_view` / `_camel_turn` in `services/profile_coach.py` does not enumerate topic fields explicitly — if it does, add `owner_id` there too.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Regenerate contracts and commit**

```bash
.venv/Scripts/python.exe scripts/export_openapi.py
bash scripts/gen_ts_client.sh
git add src/resume_agent/profile/coach_store.py src/resume_agent/profile/coach.py src/resume_agent/api/schemas/coach.py tests/test_coach_store.py web/src/lib/api/schema.ts
git commit -m "feat(coach): carry an evidence owner on seeded topics"
```

---

### Task 2: Anchored note intake

**Files:**
- Modify: `src/resume_agent/profile/intake.py:25-38`
- Test: `tests/test_profile_intake.py` (append)

**Interfaces:**
- Consumes: `add_source(profile_dir, file_path, primary=False, mode=None, anchor=None, origin="upload")` — already accepts `anchor` at `corpus.py:166`.
- Produces: `add_note_source(profile_dir, title, text, *, anchor: str | None = None) -> SourceDoc`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_intake.py (append)
from resume_agent.profile.corpus import add_source, load_manifest
from resume_agent.profile.intake import add_note_source


def _seed_primary(tmp_path, monkeypatch):
    """A manifest needs exactly one primary literal source to validate."""
    resume = tmp_path / "resume.md"
    resume.write_text("# Resume\n\nAptiv Corporation\n", encoding="utf-8")
    add_source(tmp_path, resume, primary=True)


def test_an_anchored_note_is_stored_as_synthesis_with_its_anchor(tmp_path, monkeypatch):
    _seed_primary(tmp_path, monkeypatch)
    doc = add_note_source(tmp_path, "Impact at Aptiv", "I cut triage time.", anchor="exp_aptiv")
    assert doc.mode == "synthesis"
    assert doc.anchor == "exp_aptiv"
    stored = next(d for d in load_manifest(tmp_path).docs if d.id == doc.id)
    assert stored.mode == "synthesis"
    assert stored.anchor == "exp_aptiv"


def test_an_unanchored_note_keeps_todays_literal_behavior(tmp_path, monkeypatch):
    _seed_primary(tmp_path, monkeypatch)
    doc = add_note_source(tmp_path, "Some note", "Something happened.")
    assert doc.mode == "literal"
    assert doc.anchor is None


def test_an_empty_anchor_string_is_treated_as_no_anchor(tmp_path, monkeypatch):
    """SourceManifest rejects an anchor on a literal doc, so '' must not slip
    through as a truthy-looking anchor value."""
    _seed_primary(tmp_path, monkeypatch)
    doc = add_note_source(tmp_path, "Some note", "Something happened.", anchor="")
    assert doc.mode == "literal"
    assert doc.anchor is None
```

If the existing tests in this repo need a tenant context to write under `tmp_path`, copy the fixture the neighbouring corpus tests use (`resolve_tenant_path` is applied inside `corpus.py`, so a test that writes to a bare `tmp_path` may need it).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_intake.py -v`
Expected: FAIL with `TypeError: add_note_source() got an unexpected keyword argument 'anchor'`

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/profile/intake.py`:

```python
def _stage_and_add(
    profile_dir: str | Path,
    filename: str,
    body: str,
    *,
    anchor: str | None = None,
) -> SourceDoc:
    """Stage a generated markdown body and register it.

    An anchored document goes in as `synthesis`, not `literal`, and that is the
    whole point rather than an implementation detail. The synthesis path pins
    every entry to `doc.anchor` (`synthesis.py:320`), builds Experience stubs
    whose `id` IS the anchor target (`synthesis.py:474`), and merges by id
    (`merge.py:522`). Literal mode instead falls to `_same_experience`, which
    needs an exact company match plus title-token overlap with confirmed date
    overlap - conditions a coach note cannot meet, so its bullets would land as
    a duplicate role.

    Synthesis also VERIFIES each claim against the source excerpts, and a coach
    note's source text is the user's verbatim quotes. Literal mode does not.
    """
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / filename
        staged.write_text(body, encoding="utf-8", newline="\n")
        mode = "synthesis" if anchor else "literal"
        return add_source(profile_dir, staged, mode=mode, anchor=anchor or None)


def add_note_source(
    profile_dir: str | Path,
    title: str,
    text: str,
    *,
    anchor: str | None = None,
) -> SourceDoc:
    if not text.strip():
        raise ValueError("note text is empty")
    if len(text) > 100_000:
        raise ValueError("note text is too large")
    heading = (title.strip() or "Note")[:200]
    body = f"# {heading}\n\n{text.strip()}\n"
    return _stage_and_add(
        profile_dir,
        f"note--{_slug(heading, 'note')}.md",
        body,
        anchor=anchor or None,
    )
```

`anchor or None` normalizes `""` to `None` at both layers, which matters because `SourceManifest.validate_docs` raises `anchor on {id} requires synthesis mode` for any non-`None` anchor on a literal document.

Check `add_url_source` (the other `_stage_and_add` caller in this module) still compiles — it passes no `anchor` and keeps literal mode.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/intake.py tests/test_profile_intake.py
git commit -m "feat(profile): route anchored notes through synthesis intake"
```

---

### Task 3: `approve_draft` passes the anchor

**Files:**
- Modify: `src/resume_agent/services/profile_coach.py:301-325`
- Test: `tests/test_profile_coach_service.py` (append)

**Interfaces:**
- Consumes: `add_note_source(..., anchor=...)` (Task 2); `CoachTopic.owner_id` (Task 1).
- Produces: no signature change to `approve_draft`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_coach_service.py (append)
from resume_agent.profile.corpus import load_manifest
from resume_agent.services.profile_coach import approve_draft


def test_approving_a_seeded_topics_draft_anchors_the_note(coach_workspace):
    """coach_workspace: a profile dir with a primary source, one session whose
    topic t1 has owner_id='exp_umich', and a pending draft for t1. Build it
    with the same helpers the existing tests in this file use."""
    doc_id = approve_draft(
        coach_workspace.root,
        coach_workspace.session_id,
        "t1",
        title="Teaching impact",
        summary="Ran the verification lab for 120 students.",
        quotes=["I ran the verification lab for about 120 students each term."],
    )
    doc = next(d for d in load_manifest(coach_workspace.root).docs if d.id == doc_id)
    assert doc.mode == "synthesis"
    assert doc.anchor == "exp_umich"


def test_approving_a_model_added_topics_draft_leaves_the_note_unanchored(coach_workspace):
    doc_id = approve_draft(
        coach_workspace.root,
        coach_workspace.session_id,
        "t2",                      # owner_id == "" on this topic
        title="Something else",
        summary="A thing happened.",
        quotes=["A thing happened, specifically."],
    )
    doc = next(d for d in load_manifest(coach_workspace.root).docs if d.id == doc_id)
    assert doc.mode == "literal"
    assert doc.anchor is None
```

Read the existing tests in this file first and reuse their workspace fixture rather than inventing `coach_workspace`; the session must be created through `create_session` so its JSON shape is real.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach_service.py -k anchor -v`
Expected: FAIL — `doc.mode` is `"literal"` and `doc.anchor` is `None` for the seeded topic.

- [ ] **Step 3: Write minimal implementation**

In `approve_draft` (`services/profile_coach.py:301`), inside the existing `with coach_lock():` block, after the `draft is None` / `draft["status"]` guards:

```python
        topic = next(
            (row for row in session["topics"] if row["id"] == topic_id), None
        )
        # A missing topic yields no anchor rather than an error: the draft
        # lookup above already rejects an unknown topic_id, so this branch is
        # unreachable in practice and must not add a second failure mode.
        anchor = (topic or {}).get("owner_id") or None
        doc = add_note_source(
            root, f"Coach — {title.strip() or topic_id}", body, anchor=anchor
        )
        set_draft_status(root, session_id, topic_id, "saved", note_doc_id=doc.id)
        return doc.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/profile_coach.py tests/test_profile_coach_service.py
git commit -m "feat(coach): anchor an approved note to its topic's evidence owner"
```

---

### Task 4: The anchoring regression test

**Files:**
- Create: `tests/test_coach_anchored_notes.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: nothing consumed by later tasks.

This task adds no production code. It exists because the defect this whole spec addresses is an *integration* failure: each unit can be correct while the elicited bullet still lands on the wrong role. This is the test that proves the loop closes, and it is the single most important test in the plan.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coach_anchored_notes.py
"""The elicited bullet must land on the role it is about.

Before this change a coach note was stored as `mode="literal"` with no anchor,
so merge fell to `_same_experience` (merge.py:181): an exact normalized company
match, then either an exact title match or >=50% title-token overlap WITH
confirmed date overlap. A note saying "At Aptiv I cut triage time 40%" yields
title tokens {triage, engineer} against {vehicle, system, triage, engineer,
technical, lead, vsda, team} - Jaccard ~0.22 - and states no dates, so
`_date_ranges_overlap` returns None and the overlap branch cannot fire either.
The bullets landed as a DUPLICATE role.
"""

from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.profile.corpus import SourceDoc
from resume_agent.profile.merge import apply_synthesis_fragments


def _merged() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="exp_umich",
                company="College of Engineering, University of Michigan",
                title="Graduate Student Instructor for Systems Requirement "
                "Development & Verification",
                bullets=[Bullet(id="b1", text="Taught the verification module")],
            )
        ],
    )


def _note_fragment() -> ProfileFacts:
    """What synthesis produces for an anchored note: an Experience stub whose
    id IS the anchor target (synthesis.py:474), carrying only new bullets."""
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="exp_umich",          # the anchor, not a guessed identity
                company="",
                title="",
                bullets=[
                    Bullet(id="n1", text="Ran the verification lab for 120 students"),
                    Bullet(id="n2", text="Rewrote the grading rubric for the final project"),
                ],
            )
        ],
    )


def _anchored_doc() -> SourceDoc:
    return SourceDoc(
        id="note-teaching",
        filename="note--coach-teaching-impact.md",
        sha256="0" * 64,
        added_at="2026-08-15T00:00:00Z",
        mode="synthesis",
        anchor="exp_umich",
    )


def test_anchored_note_bullets_land_on_the_target_role():
    merged = _merged()
    apply_synthesis_fragments(merged, [(_anchored_doc(), _note_fragment())])
    assert len(merged.experience) == 1, "a second Experience means the anchor was ignored"
    texts = [bullet.text for bullet in merged.experience[0].bullets]
    assert "Ran the verification lab for 120 students" in texts
    assert "Rewrote the grading rubric for the final project" in texts


def test_anchored_note_creates_no_duplicate_role_and_no_fallback_project():
    merged = _merged()
    apply_synthesis_fragments(merged, [(_anchored_doc(), _note_fragment())])
    assert len(merged.experience) == 1
    assert merged.projects == [], "an unmatched anchor falls back to a project (merge.py:527)"


def test_anchored_note_raises_the_roles_bullet_count():
    merged = _merged()
    before = len(merged.experience[0].bullets)
    apply_synthesis_fragments(merged, [(_anchored_doc(), _note_fragment())])
    assert len(merged.experience[0].bullets) == before + 2


def test_a_repeated_note_does_not_duplicate_bullets():
    """merge.py:540 dedups by normalized text; re-running a build must be safe."""
    merged = _merged()
    apply_synthesis_fragments(merged, [(_anchored_doc(), _note_fragment())])
    apply_synthesis_fragments(merged, [(_anchored_doc(), _note_fragment())])
    assert len(merged.experience[0].bullets) == 3
```

Read `apply_synthesis_fragments` (`merge.py:506`) for its exact parameter names and the real shape of the `(doc, fragment)` pairs — the fragment may be a `SynthesizedFragment` rather than a bare `ProfileFacts`. Build `_note_fragment` to match the real type; the assertions above do not depend on which it is.

- [ ] **Step 2: Run test to verify it behaves as expected**

Run: `.venv/Scripts/python.exe -m pytest tests/test_coach_anchored_notes.py -v`
Expected: PASS, given Tasks 2 and 3.

To confirm the test has teeth, temporarily change `_anchored_doc()` to `mode="literal", anchor=None` and re-run: `test_anchored_note_creates_no_duplicate_role_and_no_fallback_project` must FAIL. **Revert that change before committing.**

- [ ] **Step 3: Commit**

```bash
git add tests/test_coach_anchored_notes.py
git commit -m "test(coach): prove anchored note bullets reach their role"
```

---

### Task 5: Deterministic agenda seeding

> **BLOCKED until Spec A Task 8 is merged** — needs `owner_depth`, `evidence_owners`, and `SUPPLY_TARGET` in `profile/depth.py`.

**Files:**
- Modify: `src/resume_agent/profile/depth.py`
- Test: `tests/test_profile_depth_topics.py`

**Interfaces:**
- Consumes: `owner_depth(facts, target=SUPPLY_TARGET) -> list[OwnerSupply]` and `SUPPLY_TARGET: int = 10` (Spec A); `CoachTopic` (Task 1); `AGENDA_CAP = 12` (`coach.py:38`).
- Produces: `depth_topics(facts: ProfileFacts, target: int = SUPPLY_TARGET, cap: int = AGENDA_CAP) -> list[CoachTopic]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_depth_topics.py
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Project
from resume_agent.profile.depth import depth_topics


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="exp_full", company="Aptiv", title="Lead",
                bullets=[Bullet(id=f"a{n}", text=str(n), aspect="impact") for n in range(11)],
            ),
            Experience(
                id="exp_thin", company="UMich", title="GSI",
                bullets=[Bullet(id=f"u{n}", text=str(n), aspect="technical") for n in range(4)],
            ),
        ],
        projects=[
            Project(
                id="prj_thin", name="Signal Plot",
                highlights=[Bullet(id=f"h{n}", text=str(n)) for n in range(6)],
            ),
            Project(id="prj_empty", name="bao-birthday", highlights=[]),
        ],
    )


def test_only_below_target_owners_seed_a_topic():
    ids = [topic.owner_id for topic in depth_topics(_facts())]
    assert "exp_full" not in ids
    assert "exp_thin" in ids
    assert "prj_thin" in ids


def test_a_zero_bullet_owner_never_seeds_a_topic():
    """It is furthest below target, but it is not a profile entry yet - the
    decision it needs is whether it belongs on a resume, not an interview.
    On the live profile this is the difference between 10 topics and 19
    against a cap of 12."""
    assert "prj_empty" not in [topic.owner_id for topic in depth_topics(_facts())]


def test_topics_are_in_resume_order_with_sequential_ids():
    topics = depth_topics(_facts())
    assert [t.owner_id for t in topics] == ["exp_thin", "prj_thin"]
    assert [t.id for t in topics] == ["t1", "t2"]


def test_the_gap_text_names_the_count_the_target_and_the_missing_aspects():
    thin = next(t for t in depth_topics(_facts()) if t.owner_id == "exp_thin")
    assert "4" in thin.gap and "10" in thin.gap
    assert "impact" in thin.gap
    assert "technical" not in thin.gap.split("no evidence yet for")[1]


def test_seeding_respects_the_agenda_cap():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id=f"e{n}", company=f"C{n}", title="T",
                bullets=[Bullet(id=f"b{n}", text="x")],
            )
            for n in range(20)
        ],
    )
    assert len(depth_topics(facts, cap=12)) == 12


def test_a_profile_with_no_gaps_seeds_nothing():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e1", company="C", title="T",
                bullets=[Bullet(id=f"b{n}", text=str(n)) for n in range(12)],
            )
        ],
    )
    assert depth_topics(facts) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_depth_topics.py -v`
Expected: FAIL with `ImportError: cannot import name 'depth_topics'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/profile/depth.py`:

```python
from resume_agent.profile.coach_store import CoachTopic

# Mirrors coach.AGENDA_CAP. Imported rather than restated would be circular -
# coach.py imports from this module - so the default is passed by the caller in
# services/profile_coach.py and this value is only the standalone fallback.
_DEFAULT_CAP = 12


def depth_topics(
    facts: ProfileFacts,
    target: int = SUPPLY_TARGET,
    cap: int = _DEFAULT_CAP,
) -> list[CoachTopic]:
    """Seed the coach agenda from measured supply gaps.

    An owner holding ZERO bullets never seeds a topic even though it is
    furthest below target. It is not a thin entry; it is not yet a profile
    entry, and the decision it needs is whether it belongs on a resume at all -
    not a depth interview. Measured on the live profile, seeding every
    below-target owner produced 19 topics against a cap of 12, with two
    zero-highlight repos taking slots and the model receiving none.
    """
    topics: list[CoachTopic] = []
    for row in owner_depth(facts, target=target):
        if row.meets_target or row.source_total == 0:
            continue
        missing = ", ".join(row.aspects_missing)
        aspect_clause = f"; no evidence yet for {missing}" if missing else ""
        topics.append(
            CoachTopic(
                id=f"t{len(topics) + 1}",
                owner_id=row.id,
                gap=(
                    f"{row.label} has {row.source_total} of {target} source "
                    f"bullets{aspect_clause}"
                ),
                why_it_matters=(
                    f"a role with {row.source_total} bullets renders "
                    f"{row.source_total}; the resume can only show what the "
                    "profile holds"
                ),
                related_ref=row.id,
            )
        )
        if len(topics) >= cap:
            break
    return topics
```

> **Import-cycle check:** `profile/depth.py` importing `profile/coach_store.py` must not create a cycle. `coach_store.py` imports from `models/` and the sessions substrate; it must not import `profile/depth.py`. If it does, move `depth_topics` into `profile/coach.py` instead and keep `owner_depth` where it is.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/depth.py tests/test_profile_depth_topics.py
git commit -m "feat(coach): seed the agenda from measured supply gaps"
```

---

### Task 6: Wire seeded topics into the opening turn

> **BLOCKED until Task 5.**

**Files:**
- Modify: `src/resume_agent/profile/coach.py:111-140`
- Modify: `src/resume_agent/services/profile_coach.py:149-183`
- Test: `tests/test_profile_coach.py` (append)

**Interfaces:**
- Consumes: `depth_topics` (Task 5); `_make_topic(index, topic, *, owner_id="")` (Task 1).
- Produces: `normalize_opening(turn, strict=True, *, seeded: list[CoachTopic] | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_coach.py (append)
import pytest

from resume_agent.profile.coach import NewTopic, OpeningTurn, normalize_opening
from resume_agent.profile.coach_store import CoachTopic
from resume_agent.sessions.turns import TurnRejected


def _seeded() -> list[CoachTopic]:
    return [CoachTopic(id="t1", gap="UMich has 4 of 10", owner_id="exp_umich")]


def test_seeded_topics_come_first_and_model_topics_are_appended():
    turn = OpeningTurn(
        message="Let's start.",
        action="ask",
        topic_id="t1",
        topics=[NewTopic(gap="tell me about scale", why_it_matters="x")],
    )
    topics, _ = normalize_opening(turn, True, seeded=_seeded())
    assert [t.id for t in topics] == ["t1", "t2"]
    assert topics[0].owner_id == "exp_umich"
    assert topics[1].owner_id == ""


def test_a_turn_proposing_no_topics_is_accepted_when_seeded_topics_exist():
    """The old rejection assumed the model was the only source of an agenda."""
    turn = OpeningTurn(message="Let's start.", action="ask", topic_id="t1", topics=[])
    topics, _ = normalize_opening(turn, True, seeded=_seeded())
    assert [t.id for t in topics] == ["t1"]


def test_an_empty_agenda_from_both_sources_is_still_rejected():
    turn = OpeningTurn(message="Let's start.", action="ask", topics=[])
    with pytest.raises(TurnRejected):
        normalize_opening(turn, True, seeded=[])


def test_the_combined_agenda_respects_the_cap():
    seeded = [CoachTopic(id=f"t{n}", gap=f"g{n}", owner_id=f"o{n}") for n in range(1, 13)]
    turn = OpeningTurn(
        message="Let's start.", action="ask", topic_id="t1",
        topics=[NewTopic(gap="extra", why_it_matters="x")],
    )
    topics, _ = normalize_opening(turn, True, seeded=seeded)
    assert len(topics) == 12
    assert all(t.owner_id for t in topics), "seeded topics take precedence"


def test_seeding_is_optional_so_existing_callers_are_unchanged():
    turn = OpeningTurn(
        message="Let's start.", action="ask", topic_id="t1",
        topics=[NewTopic(gap="tell me about scale", why_it_matters="x")],
    )
    topics, _ = normalize_opening(turn, True)
    assert [t.id for t in topics] == ["t1"]
    assert topics[0].owner_id == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach.py -k seeded -v`
Expected: FAIL with `TypeError: normalize_opening() got an unexpected keyword argument 'seeded'`

- [ ] **Step 3: Write minimal implementation**

Replace `normalize_opening` in `src/resume_agent/profile/coach.py`:

```python
def normalize_opening(
    turn: OpeningTurn,
    strict: bool = True,
    *,
    seeded: list[CoachTopic] | None = None,
) -> tuple[list[CoachTopic], ValidatedTurn]:
    del strict
    message = turn.message.strip()
    if not message:
        raise TurnRejected("empty message")
    if turn.action != "ask":
        raise TurnRejected("opening action must be ask")
    # Seeded topics are deterministic measurement and take precedence; the
    # model's proposals fill whatever the cap leaves. Ids are renumbered
    # positionally across the COMBINED list so `t{n}` stays unique and dense.
    base = list(seeded or [])[:AGENDA_CAP]
    topics = [topic.model_copy(update={"id": f"t{n}"}) for n, topic in enumerate(base, 1)]
    room = AGENDA_CAP - len(topics)
    raw_topics = [topic for topic in turn.topics if topic.gap.strip()][:room]
    topics.extend(
        _make_topic(index, topic)
        for index, topic in enumerate(raw_topics, len(topics) + 1)
    )
    if not topics:
        # Reachable only when the profile has no measured gaps AND the model
        # proposed nothing - a legitimate "nothing to work on" state, not a
        # malformed turn.
        raise TurnRejected("opening turn produced no agenda")
    topic_id = turn.topic_id.strip() or topics[0].id
    if topic_id not in {topic.id for topic in topics}:
        valid = ", ".join(topic.id for topic in topics)
        raise TurnRejected(f"unknown topic: {topic_id!r} (valid ids: {valid})")
    return topics, ValidatedTurn(
        coach_turn=CoachTurnRecord(
            role="coach",
            kind="question",
            text=message,
            topic_id=topic_id,
            research_actions=_actions(turn),
        )
    )
```

In `run_opening_turn` (`services/profile_coach.py:149`), compute the seed and bind it. `format_with_retry` calls `validate(formatted, True)` **positionally** (`sessions/turns.py:262`), so a keyword-only `seeded` binds cleanly through `partial`:

```python
from functools import partial

from resume_agent.profile.depth import depth_topics
from resume_agent.profile.store import load_facts

    facts_path = root / "facts.json"
    seeded = depth_topics(load_facts(facts_path)) if facts_path.exists() else []
    agenda_block = (
        "\n\nSEEDED AGENDA (deterministic; these topics are already on the "
        "agenda - ask about them, do not re-propose them):\n"
        + "\n".join(f"- {topic.id}: {topic.gap}" for topic in seeded)
        if seeded
        else ""
    )
    prompt = (
        f"{_overview(root, engine)}{agenda_block}\n\n"
        "This is the opening turn. Propose any additional high-value topics "
        "the seeded agenda misses, and ask the first question."
    )
    ...
    topics, validated = format_with_retry(
        formatter,
        notes,
        OpeningTurn,
        partial(normalize_opening, seeded=seeded),
        label="COACH NOTES",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/coach.py src/resume_agent/services/profile_coach.py tests/test_profile_coach.py
git commit -m "feat(coach): open sessions on a gap-seeded agenda"
```

---

### Task 7: Unmined sources

> **BLOCKED until Spec A Tasks 2 and 6 are merged** — `_fact_totals` reads bullets through `evidence_owners`, and before Spec A a `Project.highlights` entry is a bare `str` carrying no `source_ref`, so "which document produced this project bullet" cannot be answered at all.

**Files:**
- Modify: `src/resume_agent/profile/depth.py`
- Test: `tests/test_profile_unmined.py`

**Interfaces:**
- Consumes: `load_facts`, `load_manifest`, `read_document_text`, `doc_path`.
- Produces:
  - `UnminedSource` — pydantic model: `doc_id: str`, `filename: str`, `fact_total: int`
  - `unmined_sources(profile_dir: Path | str) -> list[UnminedSource]`
  - `unmined_block(profile_dir: Path | str, budget: int = 12_000) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_unmined.py
from resume_agent.profile.depth import unmined_block, unmined_sources


def test_a_document_contributing_no_bullets_is_unmined(profile_workspace):
    """profile_workspace: a profile dir whose facts.json has bullets with
    source_ref='resume-1' only, and a manifest listing resume-1 (resume.md),
    goals-2026 (0 facts), and goals-2025 (skills only, no bullets). Build it
    with the helpers the neighbouring profile tests already use."""
    ids = [row.doc_id for row in unmined_sources(profile_workspace)]
    assert ids == ["goals-2026", "goals-2025"]
    assert "resume-1" not in ids


def test_rows_are_ranked_zero_fact_first(profile_workspace):
    rows = unmined_sources(profile_workspace)
    assert rows[0].doc_id == "goals-2026"
    assert rows[0].fact_total == 0
    assert rows[1].fact_total > 0


def test_a_document_contributing_only_skills_is_still_unmined(profile_workspace):
    """Skills are not bullets. A doc can enrich the matrix and still yield no
    achievement the resume can show."""
    assert "goals-2025" in [row.doc_id for row in unmined_sources(profile_workspace)]


def test_the_block_respects_its_budget(profile_workspace):
    block = unmined_block(profile_workspace, budget=200)
    assert len(block) <= 400          # header plus one truncated document
    assert "goals-2026" in block or "2026" in block


def test_the_budget_truncates_rather_than_drops(profile_workspace):
    """A large first document must not starve the block entirely."""
    assert unmined_block(profile_workspace, budget=50).strip() != ""


def test_an_unreadable_document_degrades_to_an_empty_block(profile_workspace):
    """Optional context never fails a turn - the same rule _market_gaps_report
    follows at coach.py:320."""
    for path in (profile_workspace / "sources").glob("*"):
        path.unlink()
    assert unmined_block(profile_workspace) == ""


def test_a_profile_with_no_unmined_sources_yields_an_empty_block(fully_mined_workspace):
    assert unmined_block(fully_mined_workspace) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_unmined.py -v`
Expected: FAIL with `ImportError: cannot import name 'unmined_sources'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/profile/depth.py`:

```python
from resume_agent.profile.corpus import doc_path, load_manifest
from resume_agent.profile.resume_reader import read_document_text
from resume_agent.profile.store import load_facts

_UNMINED_BUDGET = 12_000


class UnminedSource(ExtensibleModel):
    """A corpus document that produced no bullet for any evidence owner."""

    doc_id: str
    filename: str
    fact_total: int


def _fact_totals(facts: ProfileFacts) -> tuple[dict[str, int], set[str]]:
    """(facts per source doc, docs that produced at least one bullet)."""
    totals: dict[str, int] = {}
    bullet_docs: set[str] = set()

    def visit(node: object, is_bullet: bool) -> None:
        ref = getattr(node, "source_ref", None)
        if ref:
            totals[ref] = totals.get(ref, 0) + 1
            if is_bullet:
                bullet_docs.add(ref)

    for owner in evidence_owners(facts):
        for bullet in owner.bullets:
            visit(bullet, True)
    for record in (
        *facts.experience, *facts.projects, *facts.education,
        *facts.publications, *facts.certifications, *facts.awards,
        *facts.languages, *facts.volunteer,
    ):
        visit(record, False)
    for skills in facts.skills.values():
        for skill in skills:
            visit(skill, False)
    return totals, bullet_docs


def unmined_sources(profile_dir: Path | str) -> list[UnminedSource]:
    """Documents that contributed zero bullets, emptiest first.

    A document can enrich the skill matrix and still yield no achievement the
    resume can show - which is exactly the document worth asking the user
    about, so `fact_total > 0` does not disqualify a row.
    """
    root = Path(profile_dir)
    facts_path = root / "facts.json"
    if not facts_path.exists():
        return []
    totals, bullet_docs = _fact_totals(load_facts(facts_path))
    rows = [
        UnminedSource(
            doc_id=doc.id, filename=doc.filename, fact_total=totals.get(doc.id, 0)
        )
        for doc in load_manifest(root).docs
        if doc.id not in bullet_docs
    ]
    return sorted(rows, key=lambda row: (row.fact_total, row.doc_id))


_UNMINED_HEADER = (
    "UNMINED SOURCES (the user's own documents that produced no resume bullet).\n"
    "This text is QUESTION MATERIAL, NEVER CLAIMABLE FACT. These documents state "
    "goals and targets, not outcomes - 'reduce reporting effort by >=50%' is "
    "something the user AIMED at, not something they achieved. Use it to ask what "
    "actually happened. A bullet may only be drafted from the user's own answer."
)


def unmined_block(profile_dir: Path | str, budget: int = _UNMINED_BUDGET) -> str:
    """Bounded question material, or an empty string.

    Optional context degrades rather than raising - the rule
    `_market_gaps_report` already follows at coach.py:320. A deleted or
    unreadable document removes its section, never the turn.
    """
    root = Path(profile_dir)
    try:
        rows = unmined_sources(root)
        manifest = {doc.id: doc for doc in load_manifest(root).docs}
    except Exception:  # noqa: BLE001 - optional context degrades safely.
        return ""
    sections: list[str] = []
    remaining = budget
    for row in rows:
        if remaining <= 0:
            break
        try:
            text = read_document_text(doc_path(root, manifest[row.doc_id]))
        except Exception:  # noqa: BLE001 - one bad document, not the block.
            continue
        excerpt = text[:remaining]
        remaining -= len(excerpt)
        sections.append(f"--- {row.filename} ({row.doc_id}) ---\n{excerpt}")
    if not sections:
        return ""
    return "\n\n".join([_UNMINED_HEADER, *sections])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_unmined.py -v && ruff check`
Expected: PASS.

Then confirm against real data:

```bash
.venv/Scripts/python.exe -c "
from resume_agent.profile.depth import unmined_sources
for row in unmined_sources('data/users/9127fd59b364/profile'):
    print(row.fact_total, row.doc_id)
"
```

Expected: `2026-goal-setting` with 0, then `2025-goal-setting` with 6. No `resume-38978903`, no GitHub dossier.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/depth.py tests/test_profile_unmined.py
git commit -m "feat(profile): surface documents that produced no resume bullet"
```

---

### Task 8: Ground the coach in unmined sources

> **BLOCKED until Spec A Task 8 and this plan's Task 7.**

**Files:**
- Modify: `src/resume_agent/profile/coach.py:288` (`profile_overview`)
- Test: `tests/test_profile_coach.py` (append)

**Interfaces:**
- Consumes: `unmined_block(profile_dir, budget=12_000) -> str` (Task 7); `owner_depth` (Spec A, for the target line).
- Produces: no signature change to `profile_overview`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_coach.py (append)
from resume_agent.profile.coach import profile_overview


def test_overview_states_the_supply_target_not_just_a_count(profile_workspace):
    text = profile_overview(profile_workspace)
    assert "4 bullets" in text
    assert "of 10" in text or "target 10" in text


def test_overview_names_missing_aspects_per_owner(profile_workspace):
    text = profile_overview(profile_workspace)
    line = next(line for line in text.splitlines() if "exp_umich" in line)
    assert "missing" in line.lower()


def test_overview_carries_the_unmined_block_with_its_never_claimable_rule(profile_workspace):
    text = profile_overview(profile_workspace)
    assert "UNMINED SOURCES" in text
    assert "NEVER CLAIMABLE FACT" in text


def test_the_unmined_block_is_not_fenced_as_untrusted(profile_workspace):
    """That fence is for third-party text; these are the user's own uploads."""
    text = profile_overview(profile_workspace)
    start = text.index("UNMINED SOURCES")
    assert "[BEGIN UNTRUSTED CONTENT" not in text[max(0, start - 300) : start]


def test_a_workspace_with_no_unmined_sources_omits_the_block(fully_mined_workspace):
    assert "UNMINED SOURCES" not in profile_overview(fully_mined_workspace)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_coach.py -k overview -v`
Expected: FAIL — the overview prints bare counts and carries no unmined block.

- [ ] **Step 3: Write minimal implementation**

In `profile_overview` (`coach.py:288`), replace the experience/project fact lines with target-aware ones built from `owner_depth`, and append the unmined block:

```python
    from resume_agent.profile.depth import SUPPLY_TARGET, owner_depth, unmined_block

    fact_lines: list[str] = []
    facts_path = root / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        for row in owner_depth(facts):
            missing = (
                f" | missing aspects: {', '.join(row.aspects_missing)}"
                if row.aspects_missing
                else ""
            )
            fact_lines.append(
                f"{row.kind} {row.id}: {row.label} | {row.source_total} bullets "
                f"of {SUPPLY_TARGET}{missing}"
            )
```

Then, where the overview's blocks are assembled, add the unmined section last:

```python
    unmined = unmined_block(root)
    blocks = [...existing blocks...]
    if unmined:
        blocks.append(unmined)
    return "\n\n".join(blocks)
```

The block carries its own self-describing header and is inserted **verbatim**, never wrapped in `prompt_blocks.untrusted()` — the same treatment the coverage block gets in the tailor prompts, and for the same reason: a fence would contradict the instruction to use it.

The per-owner metric count (`3 with metrics`, from `_METRIC`) is dropped: `owner_depth`'s aspect breakdown supersedes it, and "has a digit in it" was a proxy for the `impact` aspect that the aspect vocabulary now measures directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/coach.py tests/test_profile_coach.py
git commit -m "feat(coach): ground questions in unmined sources and supply targets"
```

---

### Task 9: Documentation and end-to-end verification

**Files:**
- Modify: `src/resume_agent/profile/CLAUDE.md`
- Modify: `src/resume_agent/sessions/CLAUDE.md`

- [ ] **Step 1: Verify the whole suite**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
cd web && npm test && npm run typecheck && npm run lint
```

Expected: all green. Record the actual counts — do not claim a number you did not read.

- [ ] **Step 2: Verify one real coaching loop**

```bash
.venv/Scripts/python.exe -m resume_agent.cli profile coach
```

Confirm, in order:
1. The opening agenda lists the thin roles — UMich (4), Varian (5), CIM (3), MAXIEYE (3), Aptiv (9) — and **not** `bao-birthday`, `personal-website`, or any other zero-highlight repo.
2. The coach's questions reference the goal documents' actual initiatives (triage dashboards, reuse targets, Jira agent).
3. Answer one question and approve the draft. Then confirm the note was anchored:

```bash
.venv/Scripts/python.exe -c "
from resume_agent.profile.corpus import load_manifest
for d in load_manifest('data/users/9127fd59b364/profile').docs:
    if d.filename.startswith('note--'):
        print(d.id, d.mode, d.anchor)
"
```

Expected: `mode=synthesis` with a non-null `anchor` naming the role you discussed.

4. Rebuild and confirm the bullet landed on that role and created no duplicate:

```bash
.venv/Scripts/python.exe -c "
import json
d = json.load(open('data/users/9127fd59b364/profile/facts.json', encoding='utf-8'))
print(len(d['experience']), 'experiences')
for e in d['experience']:
    print(' ', e['id'], e['company'][:30], len(e.get('bullets', [])))
"
```

Expected: still **5** experiences, with the discussed role's count risen. Six experiences means the anchor was ignored.

- [ ] **Step 3: Update the module references**

In `src/resume_agent/profile/CLAUDE.md`:

```markdown
- **An anchored coach note rides synthesis, and that is load-bearing.** An
  approved draft becomes a corpus *document*, not a fact, so what attaches it
  to a role is the merge step. As `mode="literal"` it fell to
  `_same_experience`, which needs an exact company match plus title-token
  overlap **with confirmed date overlap** — conditions a coach note cannot
  meet, so its bullets landed as a duplicate role. It went unnoticed because
  no coach session or saved note had ever existed. A note carrying a topic's
  `owner_id` is now written as `mode="synthesis"` with `anchor=<owner_id>`,
  where `_apply_pinned_anchor` forces `stub.id` to the anchor target and merge
  attaches by id. Synthesis additionally verifies each claim against the
  note's verbatim user quotes; literal mode does not. An unanchored note
  (model-added topic, no `owner_id`) keeps the literal path unchanged.
- **The coach agenda is measured, not invented.** `depth_topics` seeds one
  topic per below-target evidence owner from `owner_depth`; the model appends
  to it rather than proposing the whole agenda. An owner with **zero** bullets
  never seeds a topic even though it is furthest below target — it is not a
  thin entry but a non-entry, and seeding every below-target owner produced 19
  topics against `AGENDA_CAP` 12, with zero-highlight repos taking slots and
  the model getting none.
- **Unmined source text is question material, never claimable fact.** The two
  goal-setting documents produced 0 bullets from 7.3 KB because every statement
  in them is a forward-looking target ("achieve ≥60% reuse"), not an outcome —
  fact-lock working correctly. Re-extracting them could only yield nothing
  again or launder a target into a claim, so `unmined_block` feeds them to the
  coach as questions under an explicit never-claimable rule, bounded at 12 KB
  and degrading to empty on any read failure. The user's answer is the fact.
```

In `src/resume_agent/sessions/CLAUDE.md`, add one line noting that a coach topic now carries an `owner_id` that becomes a corpus anchor on approval, and that stored sessions predating it default to `""`.

- [ ] **Step 4: Commit**

```bash
git add src/resume_agent/profile/CLAUDE.md src/resume_agent/sessions/CLAUDE.md
git commit -m "docs: record the coach anchoring and agenda-seeding invariants"
```

---

## Verification Checklist

Confirm each with real command output, not inference:

- [ ] `.venv/Scripts/python.exe -m pytest -q` passes; note the count.
- [ ] `ruff check` clean; `cd web && npm test && npm run typecheck && npm run lint` pass.
- [ ] A stored pre-change coach session JSON loads with `owner_id == ""`.
- [ ] An anchored note is stored `mode="synthesis"` with a non-null anchor.
- [ ] An unanchored note is still stored `mode="literal"` with `anchor=None`.
- [ ] **Anchored note bullets land on the target role and create no duplicate** (Task 4).
- [ ] `unmined_sources` returns both goal documents, zero-fact first, and no dossier.
- [ ] The seeded agenda excludes every zero-bullet owner.
- [ ] The unmined block appears in the coach prompt carrying `NEVER CLAIMABLE FACT`, unfenced.
- [ ] A real coach session end-to-end leaves the experience count at 5.
- [ ] `git log --oneline` shows one commit per task.
