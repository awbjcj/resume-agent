# Bullet Depth Implementation Plan

> **Execution:** Implement directly with red-green-refactor TDD. This implementation is deliberately inline; do not delegate tasks to subagents.

**Goal:** Make the tailor render at least five bullets for every experience and project that has the supply to support them, and measure — separately — where the resume under-renders and where the profile under-supplies.

**Architecture:** `LengthBudget` gains floors alongside its existing caps, and a new deterministic `format_depth_plan` block hands the writer a per-owner render range already clamped to available supply, so the model never has to do the arithmetic and is never told to invent. A fixed eight-value `Aspect` vocabulary lands on `Bullet` so diversity is measurable. `Project.highlights` is promoted from `list[str]` to `list[Bullet]` so project bullets become provenance-addressable. Two reports split by audience: `profile/depth.py` measures supply for the profile owner, `tailor/depth.py` measures render for the reviser.

**Tech Stack:** Python 3, pydantic v2, FastAPI, Typer CLI, pytest (offline — all agent calls faked), ruff.

## Implementation audit amendment (2026-08-15)

The approved design specification is authoritative. The following corrections
supersede any conflicting detail in the task text below:

- Legacy `Project.highlights: list[str]` must become `Bullet` objects with
  **stable, non-empty deterministic ids at deserialization time**. Empty ids
  cannot be deferred to `assign_fact_ids`, because stored `facts.json` is read
  directly by tailor/provenance paths.
- Keep `evidence_owners()` as the complete supply accessor, but introduce one
  deterministic budget-selection helper for `format_depth_plan()` and
  `depth_report()`. It must honor the experience/project/combined caps; only
  those planned owners form the depth-plan or its score denominator.
- New fragment, synthesis, and project extraction schemas and prompts assign
  `Bullet.aspect` at extraction time. The cheap-tier classifier is an
  idempotent backfill only for `aspect is None`, including legacy or incomplete
  extraction output; it never overwrites a populated aspect.
- `format_depth_plan()` is composed locally wherever writer, reviser, and
  advisory-panel prompt input is built. It is never supplied as an empty
  placeholder or threaded through unrelated public workflow APIs.
- The approved scope excludes web UI. Keep the additive configuration schema
  fields and generated client contract, but omit the proposed settings-page
  inputs.
- Replace live tailoring/credential-dependent acceptance steps with offline
  fixture coverage. A real stored-job tailoring run is optional manual
  acceptance only and is not part of automated verification.

The implementation also updates the current Gemini rate table and verifies the
existing native Google Search integration with offline construction tests; this
cross-cutting maintenance remains outside the bullet-depth UI scope.

## Global Constraints

- Tests run offline with no API key and no network: `.venv/Scripts/python.exe -m pytest`. All agent calls are faked.
- `pyproject.toml` sets `asyncio_mode = "auto"`, so an `async def test_*` needs no `@pytest.mark.asyncio` decorator. Don't add one.
- A fake agent must satisfy the `Runner` protocol (`llm_runner.py:33`): `async def arun(self, prompt: str) -> Any`. It must return an object with a `.content` attribute, because `expect_schema` reads `result.content` — returning the schema instance directly raises `UnparsedAgentOutput`.
- Lint with `ruff check` — must be clean before every commit.
- **Fact-lock is absolute.** Every bullet traces to a fact id in `facts.json`. No task may add a code path that lets generated text bypass `check_provenance`.
- **Backward compatibility of stored data.** Every `facts.json` and every stored `ResumeVersion.content_json` written before this change must still deserialize. New model fields are optional or carry migrating validators.
- **Depth is advisory, never a gate.** Nothing in this plan may be added to `DETERMINISTIC_GATES` or to `RESERVED_REVIEWER_NAMES`.
- **Under-supply never reaches the reviser.** A profile that lacks source bullets is not a defect the reviser can fix; routing it into the tailor loop burns premium rounds on an unwinnable complaint.
- The reviewer name `bullet-depth` is deliberately *not* reserved, exactly as `must-have-coverage` is not — the deterministic measurement is kept out of gate and weighted-score selection by its runtime `DepthCritique` type, never by its name.
- Deterministic ground-truth blocks are **never** wrapped in `prompt_blocks.untrusted()`. That fence is for third-party text only.

## File Structure

**Created**
| File | Responsibility |
| --- | --- |
| `src/resume_tailor_harness/profile/aspects.py` | The closed `Aspect` vocabulary and its human-readable descriptions. No logic. |
| `src/resume_tailor_harness/profile/depth.py` | Supply-side measurement over `ProfileFacts`. Pure; imports nothing from `tailor`. |
| `src/resume_tailor_harness/tailor/depth.py` | Render-side measurement over `ResumeContent` + `ProfileFacts` + `LengthBudget`. |
| `tests/test_profile_aspects.py`, `tests/test_profile_depth.py`, `tests/test_tailor_depth.py` | Tests for the above. |

**Modified**
| File | Change |
| --- | --- |
| `src/resume_tailor_harness/models/profile.py:24-25` | `Bullet.aspect` field |
| `src/resume_tailor_harness/models/profile.py:74` | `Project.highlights: list[str]` → `list[Bullet]` + migrating validator |
| `src/resume_tailor_harness/profile/ids.py:43-44` | assign ids to project highlights |
| `src/resume_tailor_harness/profile/merge.py:59,531` | highlight merge and stub fallback |
| `src/resume_tailor_harness/profile/synthesis.py:539`, `profile/coach.py:303`, `profile/project_extractor.py:41` | highlight consumers |
| `src/resume_tailor_harness/tailor/evidence_portfolio.py:82,189` | highlight consumers |
| `src/resume_tailor_harness/tailor/provenance.py:28-29` | index project highlight ids |
| `src/resume_tailor_harness/tailor/review_config.py:43-62` | `LengthBudget` floors |
| `src/resume_tailor_harness/tailor/length.py` | `format_budget` rewrite + `format_depth_plan` |
| `src/resume_tailor_harness/tailor/tailoring.py:31-72,86-96`, `tailor/panel.py:31-43,128-148` | depth-plan prompt wiring |
| `src/resume_tailor_harness/tailor/workflow.py:118-150` | depth critique in `_deterministic_critiques` |
| `src/resume_tailor_harness/api/schemas/config.py:76-85` | new budget fields |
| `src/resume_tailor_harness/cli.py` | `profile depth` command |
| 6 × `config/review*.yaml*` | new budget keys |

**Key structural note.** `compose_tailor_input`, `compose_revise_input`, and `_panel_inputs` each *already* receive both `profile_facts` and the budget (`_panel_inputs` via `config.length_budget`). The depth plan is therefore composed locally inside each of the three, exactly as `format_budget` already is at `tailoring.py:41` and `:143`. **No new parameter is threaded through `workflow.py` or `service.py`.**

---

### Task 1: Aspect vocabulary

**Files:**
- Create: `src/resume_tailor_harness/profile/aspects.py`
- Modify: `src/resume_tailor_harness/models/profile.py:24-25`
- Test: `tests/test_profile_aspects.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Aspect` (a `Literal` type), `ASPECTS: tuple[str, ...]`, `ASPECT_DESCRIPTIONS: dict[str, str]`, and the field `Bullet.aspect: Aspect | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_aspects.py
from resume_tailor_harness.models.profile import Bullet
from resume_tailor_harness.profile.aspects import ASPECT_DESCRIPTIONS, ASPECTS


def test_aspects_are_a_closed_eight_value_vocabulary():
    assert ASPECTS == (
        "scope",
        "technical",
        "impact",
        "collaboration",
        "leadership",
        "process",
        "tooling",
        "problem",
    )


def test_every_aspect_has_a_description_for_prompts():
    assert set(ASPECT_DESCRIPTIONS) == set(ASPECTS)
    assert all(ASPECT_DESCRIPTIONS[name].strip() for name in ASPECTS)


def test_bullet_aspect_defaults_to_none_so_legacy_facts_still_load():
    bullet = Bullet(id="b1", text="Shipped the thing")
    assert bullet.aspect is None


def test_bullet_accepts_a_known_aspect_and_rejects_an_unknown_one():
    import pydantic
    import pytest

    assert Bullet(id="b1", text="x", aspect="impact").aspect == "impact"
    with pytest.raises(pydantic.ValidationError):
        Bullet(id="b1", text="x", aspect="vibes")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_aspects.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.profile.aspects'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/profile/aspects.py
"""The closed vocabulary of bullet aspects.

Four consumers share this list - the depth plan handed to the writer, the depth
report, the profile coach, and the extraction prompts - and a derived or
per-role vocabulary would let them silently disagree about the same role. A
fixed list also gives gap measurement a stable denominator, so "7 of 8 aspects
covered" is comparable across roles and over time.

Precedent: `Skill.category`'s hard/soft/domain.
"""

from typing import Literal

Aspect = Literal[
    "scope",
    "technical",
    "impact",
    "collaboration",
    "leadership",
    "process",
    "tooling",
    "problem",
]

ASPECTS: tuple[str, ...] = (
    "scope",
    "technical",
    "impact",
    "collaboration",
    "leadership",
    "process",
    "tooling",
    "problem",
)

ASPECT_DESCRIPTIONS: dict[str, str] = {
    "scope": "scale: team size, system size, users, budget, breadth of ownership",
    "technical": "what was built and how: design, implementation, architecture",
    "impact": "measured outcome: a metric, a business result, a saved cost",
    "collaboration": "cross-functional work: stakeholders, partner teams, customers",
    "leadership": "mentoring, owning, driving a decision, setting direction",
    "process": "methodology, standards, review practice, quality gates",
    "tooling": "automation, infrastructure, developer experience",
    "problem": "debugging, incident response, root cause, recovery",
}
```

In `src/resume_tailor_harness/models/profile.py`, add the import and the field:

```python
from resume_tailor_harness.profile.aspects import Aspect   # near the existing imports


class Bullet(FactItem):
    text: str
    # Optional on purpose: None means "not yet classified", so every facts.json
    # written before the aspect vocabulary existed still deserializes. An
    # unclassified bullet is invisible to the diversity rule, never an error.
    aspect: Aspect | None = None
```

> **Import-cycle check:** `profile/aspects.py` must import nothing from `resume_tailor_harness` — it is a leaf. `models/profile.py` importing from `profile/` is the one direction that works; confirm `profile/__init__.py` does not import `models.profile` at module scope. If it does, move `Aspect` into `models/profile.py` and re-export it from `profile/aspects.py` instead.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_aspects.py -v && .venv/Scripts/python.exe -m pytest -q`
Expected: new tests PASS, full suite unchanged (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/aspects.py src/resume_tailor_harness/models/profile.py tests/test_profile_aspects.py
git commit -m "feat(profile): add closed bullet aspect vocabulary"
```

---

### Task 2: Project highlights become Bullets

**Files:**
- Modify: `src/resume_tailor_harness/models/profile.py:74`
- Modify: `src/resume_tailor_harness/profile/ids.py:43-44`
- Test: `tests/test_profile_ids.py` (append), `tests/test_profile_aspects.py` (append)

**Interfaces:**
- Consumes: `Bullet` from Task 1.
- Produces: `Project.highlights: list[Bullet]`, accepting a legacy `list[str]` on input. Project highlight ids are assigned by `assign_fact_ids` using the parts `("highlight", <project_id>, <text>)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_aspects.py (append)
from resume_tailor_harness.models.profile import Project


def test_legacy_string_highlights_coerce_to_bullets():
    project = Project(id="p1", name="Signal Plot", highlights=["Did a thing", "Did another"])
    assert [bullet.text for bullet in project.highlights] == ["Did a thing", "Did another"]
    assert all(bullet.aspect is None for bullet in project.highlights)


def test_bullet_highlights_pass_through_unchanged():
    project = Project(
        id="p1",
        name="Signal Plot",
        highlights=[Bullet(id="h1", text="Did a thing", aspect="impact")],
    )
    assert project.highlights[0].id == "h1"
    assert project.highlights[0].aspect == "impact"
```

```python
# tests/test_profile_ids.py (append)
from resume_tailor_harness.models.profile import Contact, ProfileFacts, Project
from resume_tailor_harness.profile.ids import assign_fact_ids


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        projects=[Project(id="", name="Signal Plot", highlights=["one", "two"])],
    )


def test_project_highlights_get_deterministic_ids():
    first = assign_fact_ids(_facts(), "doc1")
    second = assign_fact_ids(_facts(), "doc1")
    ids = [bullet.id for bullet in first.projects[0].highlights]
    assert all(ids)
    assert len(set(ids)) == 2
    assert ids == [bullet.id for bullet in second.projects[0].highlights]


def test_identical_highlight_text_still_gets_distinct_ids():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        projects=[Project(id="", name="P", highlights=["same", "same"])],
    )
    ids = [bullet.id for bullet in assign_fact_ids(facts, "doc1").projects[0].highlights]
    assert len(set(ids)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_aspects.py tests/test_profile_ids.py -v`
Expected: FAIL — `highlights` still holds `str`, so `bullet.text` raises `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/models/profile.py`, change the field and add the migrating validator to `Project`:

```python
class Project(FactItem):
    name: str
    description: str | None = None
    role: str | None = None
    tech: list[str] = Field(default_factory=list)
    url: str | None = None
    repo_url: str | None = None
    # Promoted from list[str]. Project bullets used to carry no ids of their own,
    # so `index_facts` registered only the project id and every project bullet
    # cited the same one - the gate could not tell a faithful highlight from a
    # fabricated one. The name stays `highlights` because it is domain-accurate
    # for a project; only the element type changed.
    highlights: list[Bullet] = Field(default_factory=list)
    # ... remaining fields unchanged ...

    @field_validator("highlights", mode="before")
    @classmethod
    def _coerce_legacy_highlights(cls, value: object) -> object:
        """Accept a legacy list[str] so stored facts.json keeps loading.

        Ids are left empty here; `assign_fact_ids` owns id assignment, exactly
        as it does for experience bullets.
        """
        if not isinstance(value, list):
            return value
        return [
            {"id": "", "text": item} if isinstance(item, str) else item
            for item in value
        ]
```

Add `field_validator` to the pydantic import line at the top of the file.

In `src/resume_tailor_harness/profile/ids.py`, replace the project loop:

```python
    for project in output.projects:
        parent = ids.assign(project, "proj", project.name)
        for highlight in project.highlights:
            ids.assign(highlight, "highlight", parent, highlight.text)
```

The `_Assigner` already appends an occurrence counter to the base key, so two identical highlight texts under one project receive distinct ids.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_aspects.py tests/test_profile_ids.py -v`
Expected: PASS. The full suite will still fail — Task 3 fixes the consumers.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/models/profile.py src/resume_tailor_harness/profile/ids.py tests/test_profile_aspects.py tests/test_profile_ids.py
git commit -m "feat(profile): promote project highlights to addressable Bullet facts"
```

---

### Task 3: Update the highlight consumers

**Files:**
- Modify: `src/resume_tailor_harness/profile/merge.py:59,531`
- Modify: `src/resume_tailor_harness/profile/synthesis.py:539`
- Modify: `src/resume_tailor_harness/profile/coach.py:303`
- Modify: `src/resume_tailor_harness/profile/project_extractor.py:41`
- Modify: `src/resume_tailor_harness/tailor/evidence_portfolio.py:82,189`
- Test: `tests/test_profile_merge.py` (append)

**Interfaces:**
- Consumes: `Project.highlights: list[Bullet]` from Task 2.
- Produces: no new public names. All six sites operate on `Bullet` objects.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_merge.py (append)
from resume_tailor_harness.models.profile import (
    Bullet, Contact, Experience, ProfileFacts, Project,
)
from resume_tailor_harness.profile.merge import apply_synthesis_fragments


def test_synth_fallback_project_keeps_bullet_ids_instead_of_flattening_to_text():
    """merge.py:531 used to do highlights=[b.text for b in stub.bullets], which
    threw away ids that already existed. Promoting the field un-does that loss.

    The fallback fires when a synthesis fragment's experience stub id matches
    nothing in merged.experience (the `target is None` branch at merge.py:527).
    """
    merged = ProfileFacts(contact=Contact(name="A"))          # no experience at all
    fragment = ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="orphan",
                company="C",
                title="T",
                bullets=[Bullet(id="sb1", text="Built the pipeline", aspect="technical")],
            )
        ],
    )
    apply_synthesis_fragments(merged, [(_doc(), fragment)])   # match the real signature
    assert len(merged.projects) == 1
    assert [b.text for b in merged.projects[0].highlights] == ["Built the pipeline"]
    assert merged.projects[0].highlights[0].aspect == "technical"


def test_project_highlights_merge_by_text_without_duplicating():
    from resume_tailor_harness.profile.merge import _merge_project_highlights

    target = Project(id="p1", name="P", highlights=[Bullet(id="h1", text="Built a parser")])
    _merge_project_highlights(
        target,
        [
            Bullet(id="h2", text="built  a PARSER"),   # same after normalization
            Bullet(id="h3", text="Shipped the CLI"),
        ],
    )
    assert [b.text for b in target.highlights] == ["Built a parser", "Shipped the CLI"]
```

Read `apply_synthesis_fragments` at `merge.py:506` for its exact parameter names and the shape of the `(doc, fragment)` pairs, and build `_doc()` to match — the existing tests in this file already construct one.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_merge.py -v`
Expected: FAIL — aspect is dropped, or a `ValidationError` from the flattening.

- [ ] **Step 3: Write minimal implementation**

`profile/merge.py:531` — stop flattening, carry the bullets through:

```python
                        highlights=list(stub.bullets),
```

`profile/merge.py:59` — `_PROJECT_COLLECTIONS = ("tech", "highlights", "languages", "topics")` drives generic list-merging inside `_merge_projects` (`merge.py:277`). Highlights are now objects, not strings, so a value-identity merge on them is wrong. Remove `"highlights"` from that tuple and merge them explicitly by normalized text, mirroring how experience bullets are already deduped at `merge.py:540`:

```python
_PROJECT_COLLECTIONS = ("tech", "languages", "topics")


def _merge_project_highlights(target: Project, incoming: list[Bullet]) -> None:
    """Append highlights whose normalized text is not already present."""
    seen = {normalize_skill(bullet.text) for bullet in target.highlights}
    for bullet in incoming:
        key = normalize_skill(bullet.text)
        if key not in seen:
            target.highlights.append(bullet)
            seen.add(key)
```

Call `_merge_project_highlights` from `_merge_projects` (`merge.py:277`), right where the `_PROJECT_COLLECTIONS` loop runs. `normalize_skill` is already imported in this module (it is used by `_dedup_bullets`).

`profile/synthesis.py:539` — `highlights=[claim.text for claim in entry.claims]` becomes:

```python
                highlights=[Bullet(id="", text=claim.text) for claim in entry.claims],
```

Import `Bullet` from `resume_tailor_harness.models.profile`. Ids stay empty; `assign_fact_ids` fills them.

`profile/coach.py:303` — `len(project.highlights)` is already correct and needs no change; verify only.

`profile/project_extractor.py:41` — the prompt string mentions `highlights`. The extractor's output schema now expects objects. If it emits bare strings, the Task 2 validator coerces them, so **no change is required**; confirm by running the extractor's existing tests.

`tailor/evidence_portfolio.py:82` — `"; ".join(project.highlights)` becomes:

```python
            "; ".join(bullet.text for bullet in project.highlights),
```

`tailor/evidence_portfolio.py:189` — `len(project.highlights) or int(bool(project.description))` needs no change.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: full suite PASS, ruff clean. Any remaining failure is another highlight consumer — fix it the same way.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/ src/resume_tailor_harness/tailor/evidence_portfolio.py tests/test_profile_merge.py
git commit -m "refactor: update project highlight consumers for Bullet elements"
```

---

### Task 4: Project highlights enter the provenance index

**Files:**
- Modify: `src/resume_tailor_harness/tailor/provenance.py:28-29`
- Test: `tests/test_tailor_provenance.py` (append)

**Interfaces:**
- Consumes: `Project.highlights: list[Bullet]` from Task 2.
- Produces: `index_facts` now returns project highlight ids as keys. No signature change.

This task delivers the invariant that does not exist today.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_provenance.py (append)
from resume_tailor_harness.models.profile import Bullet, Contact, ProfileFacts, Project
from resume_tailor_harness.models.resume import ResumeContent, TailoredBullet, TailoredProject
from resume_tailor_harness.tailor.provenance import check_provenance, index_facts


def _facts_with_project() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        projects=[
            Project(
                id="p1",
                name="Signal Plot",
                highlights=[Bullet(id="h1", text="Cut plot time 80%")],
            )
        ],
    )


def _resume(bullet_provenance: str) -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="A"),
        projects=[
            TailoredProject(
                name="Signal Plot",
                provenance="p1",
                bullets=[TailoredBullet(text="Cut plot time 80%", provenance=bullet_provenance)],
            )
        ],
    )


def test_index_registers_project_highlight_ids():
    assert "h1" in index_facts(_facts_with_project())


def test_project_bullet_citing_a_real_highlight_passes():
    assert check_provenance(_resume("h1"), _facts_with_project()).ok


def test_project_bullet_citing_a_fabricated_highlight_id_fails():
    """The invariant that could not exist before highlights had ids."""
    report = check_provenance(_resume("h999"), _facts_with_project())
    assert not report.ok
    assert "h999" in report.missing
```

`ProvenanceReport` (`provenance.py:13`) exposes exactly `ok: bool`, `missing: list[str]`, and `invalid: list[str]` — an id absent from the index lands in `missing`. There is no `unknown_ids` field.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_provenance.py -k highlight -v`
Expected: FAIL — `h1` is not in the index, so even the *valid* citation is rejected.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/tailor/provenance.py`, extend the project loop in `index_facts`:

```python
    for proj in facts.projects:
        index[proj.id] = proj
        for highlight in proj.highlights:
            index[highlight.id] = highlight
```

`_referenced_uses` already emits `(bullet.provenance, "bullet")` for project bullets at line 58, so no change is needed there.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_provenance.py -v && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

> **Watch for:** existing stored resumes cite the *project* id for project bullets. That still passes — `proj.id` remains in the index. This tightens what *can* be cited without invalidating what already was.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tailor/provenance.py tests/test_tailor_provenance.py
git commit -m "feat(tailor): verify project bullets against highlight ids"
```

---

### Task 5: LengthBudget floors

**Files:**
- Modify: `src/resume_tailor_harness/tailor/review_config.py:43-62`
- Modify: `src/resume_tailor_harness/api/schemas/config.py:76-85`
- Modify: `config/review.yaml`, `config/review.yaml.example`, `config/review_deep.yaml`, `config/review_deep.yaml.example`, `config/review.early_stop.yaml`, `config/review.match_plan.yaml`
- Test: `tests/test_tailor_review_config.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `LengthBudget` fields `page_target: int`, `min_bullets_per_role: int`, `min_bullets_per_project: int`, `min_aspects_per_owner: int`, and changed defaults on `max_experiences`, `max_projects`, `max_evidence_owners`, `max_bullets_per_role`, `max_bullets_per_project`, `target_total_bullets`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_review_config.py (append)
import pydantic
import pytest

from resume_tailor_harness.tailor.review_config import LengthBudget


def test_budget_defaults_target_two_pages_with_floors():
    budget = LengthBudget()
    assert budget.page_target == 2
    assert budget.min_bullets_per_role == 5
    assert budget.max_bullets_per_role == 7
    assert budget.min_bullets_per_project == 4
    assert budget.max_bullets_per_project == 6
    assert budget.min_aspects_per_owner == 3
    assert budget.target_total_bullets == 40
    assert budget.max_experiences == 5
    assert budget.max_projects == 4
    assert budget.max_evidence_owners == 8


def test_a_floor_above_its_cap_is_rejected():
    with pytest.raises(pydantic.ValidationError):
        LengthBudget(min_bullets_per_role=8, max_bullets_per_role=5)
    with pytest.raises(pydantic.ValidationError):
        LengthBudget(min_bullets_per_project=9, max_bullets_per_project=6)


def test_legacy_yaml_without_floor_keys_still_validates():
    budget = LengthBudget.model_validate(
        {"max_experiences": 4, "max_bullets_per_role": 5, "target_total_bullets": 20}
    )
    assert budget.min_bullets_per_role == 5
    assert budget.max_bullets_per_role == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_review_config.py -k budget -v`
Expected: FAIL with `AttributeError: 'LengthBudget' object has no attribute 'page_target'`

- [ ] **Step 3: Write minimal implementation**

Replace the `LengthBudget` body in `src/resume_tailor_harness/tailor/review_config.py`:

```python
class LengthBudget(ExtensibleModel):
    """Page guidance handed to the tailor and surfaced to reviewers.

    Caps AND floors. The floors exist because a cap plus a shared global pool
    plus "drop the rest" is read - correctly - as permission to spend the pool
    top-down: measured across 30 stored versions, role #1 hit
    `max_bullets_per_role` in 30/30 and role #2 in 0/30. An unstated floor is
    not a neutral default; it reads as zero. That is the same failure the
    skills fields already document, and the same one every provider's unset
    `thinking` config produced in `llm_runner.py`.

    A floor is a REQUEST, never a licence to invent: `format_depth_plan` clamps
    every floor to the owner's actual source-bullet count before the writer
    ever sees it.
    """

    page_target: int = Field(default=2, ge=1)
    max_experiences: int = 5
    max_projects: int = 4
    max_evidence_owners: int = 8
    min_bullets_per_role: int = 5
    max_bullets_per_role: int = 7
    min_bullets_per_project: int = 4
    max_bullets_per_project: int = 6
    target_total_bullets: int = 40
    # Distinct aspects requested per evidence owner, so five bullets are five
    # angles rather than five restatements of one.
    min_aspects_per_owner: int = 3
    # A target, not a cap: the writer is asked to reach it, not to stop there.
    target_skills: int = 40
    max_skills_per_category: int = 12

    @model_validator(mode="after")
    def _floors_fit_under_caps(self) -> "LengthBudget":
        if self.min_bullets_per_role > self.max_bullets_per_role:
            raise ValueError("min_bullets_per_role exceeds max_bullets_per_role")
        if self.min_bullets_per_project > self.max_bullets_per_project:
            raise ValueError("min_bullets_per_project exceeds max_bullets_per_project")
        return self
```

> **Note on the third test:** legacy YAML supplies `max_bullets_per_role: 5` while `min_bullets_per_role` defaults to 5 — equal, so the validator passes. Verify no shipped YAML sets a cap *below* a new floor default. `config/review.yaml.example` sets `max_bullets_per_project: 3` against a default floor of 4, which **would** raise. Update all six YAML files in the same commit.

Each of the six `config/review*.yaml*` files gets its `length_budget` block replaced with:

```yaml
length_budget:
  page_target: 2
  max_experiences: 5
  max_projects: 4
  max_evidence_owners: 8
  min_bullets_per_role: 5
  max_bullets_per_role: 7
  min_bullets_per_project: 4
  max_bullets_per_project: 6
  target_total_bullets: 40
  min_aspects_per_owner: 3
  target_skills: 40
  max_skills_per_category: 12
```

In `src/resume_tailor_harness/api/schemas/config.py`, add the mirrored fields after line 85, using the existing `_budget_default` helper so the API never restates a literal:

```python
    page_target: int = _budget_default("page_target")
    min_bullets_per_role: int = _budget_default("min_bullets_per_role")
    min_bullets_per_project: int = _budget_default("min_bullets_per_project")
    min_aspects_per_owner: int = _budget_default("min_aspects_per_owner")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS. `tests/test_tailor_length.py::test_format_budget_mentions_one_page_and_numbers` is expected to FAIL here — Task 6 rewrites it. If it is the only failure, proceed.

- [ ] **Step 5: Regenerate API contracts and commit**

```bash
.venv/Scripts/python.exe scripts/export_openapi.py
bash scripts/gen_ts_client.sh
git add src/resume_tailor_harness/tailor/review_config.py src/resume_tailor_harness/api/schemas/config.py config/ tests/test_tailor_review_config.py web/src/lib/api/schema.ts
git commit -m "feat(tailor): add bullet floors and a two-page target to LengthBudget"
```

---

### Task 6: The depth plan block

**Files:**
- Modify: `src/resume_tailor_harness/tailor/length.py`
- Create: `src/resume_tailor_harness/profile/depth.py` (the `evidence_owners` accessor only; the report lands in Task 8)
- Test: `tests/test_tailor_length.py` (rewrite two tests, append the rest)

**Interfaces:**
- Consumes: `LengthBudget` (Task 5), `Project.highlights: list[Bullet]` (Task 2).
- Produces:
  - `resume_tailor_harness.profile.depth.OwnerRef` — frozen dataclass with `id: str`, `kind: Literal["experience", "project"]`, `label: str`, `bullets: list[Bullet]`
  - `resume_tailor_harness.profile.depth.evidence_owners(facts: ProfileFacts) -> list[OwnerRef]`
  - `resume_tailor_harness.tailor.length.format_depth_plan(facts: ProfileFacts, budget: LengthBudget) -> str`
  - `resume_tailor_harness.tailor.length.clamped_floor(owner: OwnerRef, budget: LengthBudget) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_length.py (append; also delete the obsolete
# test_format_budget_mentions_one_page_and_numbers and replace it with the
# first test below)
from resume_tailor_harness.models.profile import Bullet, Contact, Experience, ProfileFacts, Project
from resume_tailor_harness.profile.depth import evidence_owners
from resume_tailor_harness.tailor.length import clamped_floor, format_budget, format_depth_plan
from resume_tailor_harness.tailor.review_config import LengthBudget


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e_rich",
                company="Aptiv",
                title="Triage Engineer",
                bullets=[Bullet(id=f"b{n}", text=f"did thing {n}") for n in range(9)],
            ),
            Experience(
                id="e_thin",
                company="MAXIEYE",
                title="Intern",
                bullets=[Bullet(id=f"t{n}", text=f"did other {n}") for n in range(3)],
            ),
        ],
        projects=[
            Project(
                id="p_rich",
                name="Signal Plot",
                highlights=[Bullet(id=f"h{n}", text=f"hl {n}") for n in range(50)],
            )
        ],
    )


def test_format_budget_states_the_page_target_not_a_single_page():
    text = format_budget(LengthBudget())
    assert "single page" not in text
    assert "2 pages" in text


def test_evidence_owners_covers_experiences_and_projects():
    owners = evidence_owners(_facts())
    assert [owner.id for owner in owners] == ["e_rich", "e_thin", "p_rich"]
    assert [owner.kind for owner in owners] == ["experience", "experience", "project"]
    assert len(owners[2].bullets) == 50


def test_floor_clamps_to_supply_and_never_asks_for_more_than_exists():
    budget = LengthBudget()
    owners = {owner.id: owner for owner in evidence_owners(_facts())}
    assert clamped_floor(owners["e_rich"], budget) == 5   # floor, supply is ample
    assert clamped_floor(owners["e_thin"], budget) == 3   # supply-limited
    assert clamped_floor(owners["p_rich"], budget) == 4   # project floor


def test_depth_plan_names_every_owner_with_a_render_range():
    text = format_depth_plan(_facts(), LengthBudget())
    assert "BULLET DEPTH PLAN" in text
    assert "e_rich" in text and "9 source" in text and "5-7" in text
    assert "p_rich" in text and "50 source" in text and "4-6" in text


def test_depth_plan_marks_a_supply_limited_owner_and_never_states_a_floor_above_supply():
    text = format_depth_plan(_facts(), LengthBudget())
    thin = next(line for line in text.splitlines() if "e_thin" in line)
    assert "3 source" in thin
    assert "supply-limited" in thin
    assert "do not invent" in thin
    assert "5" not in thin.split("render")[1]


def test_depth_plan_is_empty_when_the_profile_has_no_owners():
    empty = ProfileFacts(contact=Contact(name="A"))
    assert format_depth_plan(empty, LengthBudget()) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_length.py -v`
Expected: FAIL with `ImportError: cannot import name 'format_depth_plan'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/profile/depth.py
"""Evidence owners and their bullet supply.

Pure measurement over ProfileFacts. Imports nothing from `tailor` - the tailor
side depends on this, never the other way round, so the profile coach and the
material-intake surface (specs B and C) can consume it without dragging review
config in.
"""

from dataclasses import dataclass
from typing import Literal

from resume_tailor_harness.models.profile import Bullet, ProfileFacts


@dataclass(frozen=True)
class OwnerRef:
    """One thing on a resume that owns bullets."""

    id: str
    kind: Literal["experience", "project"]
    label: str
    bullets: list[Bullet]


def evidence_owners(facts: ProfileFacts) -> list[OwnerRef]:
    """Experiences then projects, as one uniform sequence.

    Every downstream consumer - the depth plan, both depth reports, the coach -
    reads bullets through this instead of branching on record type, so
    `Experience.bullets` and `Project.highlights` differing in name costs
    nothing.
    """
    owners = [
        OwnerRef(
            id=experience.id,
            kind="experience",
            label=f"{experience.company} - {experience.title}",
            bullets=list(experience.bullets),
        )
        for experience in facts.experience
    ]
    owners.extend(
        OwnerRef(
            id=project.id,
            kind="project",
            label=project.name,
            bullets=list(project.highlights),
        )
        for project in facts.projects
    )
    return owners
```

In `src/resume_tailor_harness/tailor/length.py`, rewrite `format_budget` and add the two new functions:

```python
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.profile.depth import OwnerRef, evidence_owners


def format_budget(budget: LengthBudget) -> str:
    """Render the budget as one prompt instruction for tailor/reviser agents.

    Three budgets are stated separately on purpose - pages, bullets, skills -
    because they cost different amounts of page space and respond to different
    pressure. The per-owner bullet numbers live in `format_depth_plan`, not
    here: a floor stated in the abstract is a floor the writer has to reconcile
    against supply itself, which is exactly the arithmetic it gets wrong.
    """
    return (
        f"Target {budget.page_target} pages. Use at most {budget.max_experiences} "
        f"experiences, {budget.max_projects} projects, and "
        f"{budget.max_evidence_owners} combined evidence owners, with about "
        f"{budget.target_total_bullets} bullets in total. "
        "Per-owner bullet counts are given in the BULLET DEPTH PLAN below; treat "
        "each stated range as a requirement, not a ceiling to approach from "
        "beneath. Every owner listed there must appear on the resume. "
        f"Within one owner, cover at least {budget.min_aspects_per_owner} "
        "different aspects - scale, technical work, measured impact, "
        "collaboration, leadership, process, tooling, problem-solving - rather "
        "than restating one angle. "
        "The skills section is budgeted separately and is not where a resume runs "
        f"long: it renders as one comma-joined line per category, so about "
        f"{budget.target_skills} entries cost roughly five lines. Aim for "
        f"{budget.target_skills} skills entries, at most "
        f"{budget.max_skills_per_category} per category, and include every profile "
        "skill this job names as well as every adjacent skill from the same stack, "
        "toolchain, or domain. Listing an adjacent skill under its own true name "
        "from the cited fact is correct and expected; renaming it to the job's own "
        "term is not, and still fails. Cut only skills genuinely irrelevant to this "
        "role; do not drop a relevant skill to save space."
    )


def clamped_floor(owner: OwnerRef, budget: LengthBudget) -> int:
    """The floor this owner can actually meet without inventing.

    A floor of 5 against 3 source bullets is an instruction to invent, which
    `check_provenance` rejects at the cost of a round. So supply wins.
    """
    floor = (
        budget.min_bullets_per_role
        if owner.kind == "experience"
        else budget.min_bullets_per_project
    )
    return min(floor, len(owner.bullets))


def _ceiling(owner: OwnerRef, budget: LengthBudget) -> int:
    cap = (
        budget.max_bullets_per_role
        if owner.kind == "experience"
        else budget.max_bullets_per_project
    )
    return min(cap, len(owner.bullets))


def _depth_line(owner: OwnerRef, budget: LengthBudget) -> str:
    floor = clamped_floor(owner, budget)
    ceiling = _ceiling(owner, budget)
    supply = len(owner.bullets)
    limited = floor < (
        budget.min_bullets_per_role
        if owner.kind == "experience"
        else budget.min_bullets_per_project
    )
    span = f"{floor}" if floor == ceiling else f"{floor}-{ceiling}"
    note = " (supply-limited; render all of them and do not invent more)" if limited else ""
    return f"- {owner.id} {owner.label!r}: {supply} source -> render {span}{note}"


def format_depth_plan(facts: ProfileFacts, budget: LengthBudget) -> str:
    """Per-owner render ranges, already clamped to supply.

    This block is the fix. The writer receives arithmetic it cannot get wrong
    instead of a cap plus a shared pool, and a supply-limited owner is named as
    such so a short entry reads as a fact about the profile rather than as
    permission to pad.

    Deterministic self-generated ground truth: never fenced as untrusted.
    """
    owners = evidence_owners(facts)
    if not owners:
        return ""
    header = (
        "BULLET DEPTH PLAN (deterministic; per evidence owner; ranges are "
        "already clamped to available source bullets):"
    )
    return "\n".join([header, *(_depth_line(owner, budget) for owner in owners)])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_length.py -v && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/depth.py src/resume_tailor_harness/tailor/length.py tests/test_tailor_length.py
git commit -m "feat(tailor): add supply-clamped per-owner bullet depth plan"
```

---

### Task 7: Wire the depth plan into the prompts

**Files:**
- Modify: `src/resume_tailor_harness/tailor/tailoring.py:31-72` and `:86-96,143`
- Modify: `src/resume_tailor_harness/tailor/panel.py:31-43,128-148`
- Test: `tests/test_tailor_agents.py` or `tests/test_tailor_panel.py` (append)

**Interfaces:**
- Consumes: `format_depth_plan(facts, budget)` from Task 6.
- Produces: no signature changes. All three composers already hold `profile_facts` and the budget locally.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_panel.py (append)
from resume_tailor_harness.models.job import JobCriteria
from resume_tailor_harness.tailor.panel import compose_lean_review_input
from resume_tailor_harness.tailor.review_config import LengthBudget, ReviewConfig
from resume_tailor_harness.tailor.tailoring import compose_revise_input, compose_tailor_input


def test_tailor_input_carries_the_depth_plan_unfenced():
    text = compose_tailor_input(
        jd_text="a job",
        criteria=JobCriteria(),
        profile_facts=_facts(),           # reuse the fixture from test_tailor_length
        length_budget=LengthBudget(),
    )
    assert "BULLET DEPTH PLAN" in text
    start = text.index("BULLET DEPTH PLAN")
    assert "[BEGIN UNTRUSTED CONTENT" not in text[start - 200 : start]


def test_revise_input_carries_the_depth_plan():
    text = compose_revise_input(
        content=_empty_resume(),
        critiques=[],
        profile_facts=_facts(),
        jd_text="a job",
        length_budget=LengthBudget(),
    )
    assert "BULLET DEPTH PLAN" in text


def test_lean_review_input_carries_the_depth_plan_so_reviewers_see_supply_limits():
    text = compose_lean_review_input(
        _empty_resume(), "a job", "stats", depth_plan="BULLET DEPTH PLAN\n- x"
    )
    assert "BULLET DEPTH PLAN" in text


def test_no_depth_plan_when_no_budget_is_supplied():
    text = compose_tailor_input(
        jd_text="a job", criteria=JobCriteria(), profile_facts=_facts()
    )
    assert "BULLET DEPTH PLAN" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_panel.py -k depth -v`
Expected: FAIL — the block is absent; the lean-review test fails on an unexpected `depth_plan` keyword.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_tailor_harness/tailor/tailoring.py`, import `format_depth_plan` and extend `budget_line` at **both** line 41 and line 143 (identical change in `compose_tailor_input` and `compose_revise_input`):

```python
    budget_line = (
        f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}"
        f"\n\n{format_depth_plan(profile_facts, length_budget)}"
        if length_budget
        else ""
    )
```

The depth plan rides inside `budget_line`, which already sits after the fenced JD — stable context, unfenced, and no new parameter.

In `src/resume_tailor_harness/tailor/panel.py`, give `compose_lean_review_input` the block and compose it in `_panel_inputs` from data already in hand:

```python
def compose_lean_review_input(
    content: ResumeContent,
    jd_text: str,
    stats: str,
    coverage: str = "",
    depth_plan: str = "",
) -> str:
    """Input for non-gate reviewers: resume + JD + size stats. No raw profile.

    The depth plan is included so a reviewer reads a three-bullet role as a
    supply limit rather than as thin writing.
    """
    return (
        "JOB DESCRIPTION:\n"
        f"{untrusted(jd_text)}"
        f"{coverage_section(coverage)}"
        f"{coverage_section(depth_plan)}\n\n"
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "RESUME STATS:\n"
        f"{stats}"
    )
```

`coverage_section` is reused because it is already the generic "block as its own section, or nothing when absent" helper — update its docstring in `prompt_blocks.py` to say it serves any deterministic ground-truth block, not just coverage.

In `_panel_inputs` (`panel.py:128`):

```python
    evidence = resolve_evidence(content, profile_facts)
    stats = resume_stats(content)
    depth_plan = format_depth_plan(profile_facts, config.length_budget)
    inputs: list[tuple[str, str]] = []
    for spec in config.reviewers:
        if spec.gate:
            text = compose_evidence_review_input(content, jd_text, evidence)
        else:
            text = compose_lean_review_input(
                content, jd_text, stats, coverage=coverage, depth_plan=depth_plan
            )
        inputs.append((spec.name, text))
    return inputs
```

Apply the same `depth_plan=` argument at `panel.py:110` and `:209`, computing `format_depth_plan(profile_facts, config.length_budget)` where `profile_facts` and `config` are in scope. If either site lacks `profile_facts`, pass `depth_plan=""` there and note it — do **not** thread a new parameter down from `workflow.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tailor/tailoring.py src/resume_tailor_harness/tailor/panel.py src/resume_tailor_harness/tailor/prompt_blocks.py tests/test_tailor_panel.py
git commit -m "feat(tailor): hand the depth plan to writer, reviser, and panel"
```

---

### Task 8: Supply-side depth report and the `profile depth` CLI

**Files:**
- Modify: `src/resume_tailor_harness/profile/depth.py`
- Modify: `src/resume_tailor_harness/cli.py` (new `@profile_app.command("depth")`)
- Test: `tests/test_profile_depth.py`

**Interfaces:**
- Consumes: `evidence_owners`, `OwnerRef` (Task 6); `ASPECTS` (Task 1).
- Produces:
  - `OwnerSupply` — pydantic model: `id: str`, `kind: str`, `label: str`, `source_total: int`, `aspects_present: list[str]`, `aspects_missing: list[str]`, `unclassified: int`, `meets_target: bool`
  - `owner_depth(facts: ProfileFacts, target: int = 10) -> list[OwnerSupply]`
  - `SUPPLY_TARGET: int = 10`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_depth.py
from resume_tailor_harness.models.profile import Bullet, Contact, Experience, ProfileFacts, Project
from resume_tailor_harness.profile.depth import SUPPLY_TARGET, owner_depth


def test_supply_target_is_ten_source_bullets():
    """Ten source bullets from different aspects so the writer picks five."""
    assert SUPPLY_TARGET == 10


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e_thin",
                company="MAXIEYE",
                title="Intern",
                bullets=[
                    Bullet(id="t1", text="a", aspect="technical"),
                    Bullet(id="t2", text="b", aspect="technical"),
                    Bullet(id="t3", text="c"),
                ],
            )
        ],
        projects=[
            Project(
                id="p_rich",
                name="Signal Plot",
                highlights=[
                    Bullet(id=f"h{n}", text=f"hl {n}", aspect=aspect)
                    for n, aspect in enumerate(
                        [
                            "scope", "technical", "impact", "collaboration",
                            "leadership", "process", "tooling", "problem",
                            "impact", "technical", "scope", "process",
                        ]
                    )
                ],
            )
        ],
    )


def test_thin_owner_is_reported_below_target_with_its_missing_aspects():
    thin = next(row for row in owner_depth(_facts()) if row.id == "e_thin")
    assert thin.source_total == 3
    assert thin.meets_target is False
    assert thin.aspects_present == ["technical"]
    assert "impact" in thin.aspects_missing
    assert "leadership" in thin.aspects_missing
    assert thin.unclassified == 1


def test_rich_owner_meets_the_target_with_full_aspect_coverage():
    rich = next(row for row in owner_depth(_facts()) if row.id == "p_rich")
    assert rich.source_total == 12
    assert rich.meets_target is True
    assert rich.aspects_missing == []
    assert rich.unclassified == 0


def test_an_entirely_unclassified_profile_reports_supply_without_aspect_noise():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e",
                company="C",
                title="T",
                bullets=[Bullet(id=f"b{n}", text=str(n)) for n in range(11)],
            )
        ],
    )
    row = owner_depth(facts)[0]
    assert row.source_total == 11
    assert row.meets_target is True
    assert row.unclassified == 11
    assert row.aspects_present == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_depth.py -v`
Expected: FAIL with `ImportError: cannot import name 'owner_depth'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_tailor_harness/profile/depth.py`:

```python
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.profile.aspects import ASPECTS

# Source bullets an owner needs so the writer has a real menu to choose five
# from. Deliberately NOT the render floor (LengthBudget.min_bullets_per_role):
# ten to choose five from is the point.
SUPPLY_TARGET: int = 10


class OwnerSupply(ExtensibleModel):
    """What one evidence owner has to offer, before any job is considered."""

    id: str
    kind: str
    label: str
    source_total: int
    aspects_present: list[str]
    aspects_missing: list[str]
    unclassified: int
    meets_target: bool


def owner_depth(facts: ProfileFacts, target: int = SUPPLY_TARGET) -> list[OwnerSupply]:
    """Per-owner bullet supply and aspect coverage.

    Pure and job-independent: this answers "what does the profile hold", which
    is the question the coach (spec B) and the material intake (spec C) act on.
    The tailor's own question - "what did this resume render" - lives in
    `tailor/depth.py` and must not be conflated with it.
    """
    rows: list[OwnerSupply] = []
    for owner in evidence_owners(facts):
        present = {bullet.aspect for bullet in owner.bullets if bullet.aspect}
        rows.append(
            OwnerSupply(
                id=owner.id,
                kind=owner.kind,
                label=owner.label,
                source_total=len(owner.bullets),
                aspects_present=[name for name in ASPECTS if name in present],
                aspects_missing=[name for name in ASPECTS if name not in present],
                unclassified=sum(1 for bullet in owner.bullets if not bullet.aspect),
                meets_target=len(owner.bullets) >= target,
            )
        )
    return rows
```

In `src/resume_tailor_harness/cli.py`, add alongside the other `@profile_app.command(...)` handlers. `load_facts` is already imported at `cli.py:15` and `_tenant_cli_path` / `DEFAULT_FACTS` are already in scope. `SUPPLY_TARGET` is used as a default argument value, so it must be a **module-level** import — add `from resume_tailor_harness.profile.depth import SUPPLY_TARGET` to the top of `cli.py`, not inside the function body:

```python
@profile_app.command("depth")
def profile_depth_cmd(
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    target: int = typer.Option(
        SUPPLY_TARGET, help="Source bullets an owner needs to clear the bar."
    ),
) -> None:
    """Show bullet supply and aspect coverage per experience and project."""
    from resume_tailor_harness.profile.aspects import ASPECTS
    from resume_tailor_harness.profile.depth import owner_depth

    profile_facts = load_facts(_tenant_cli_path(facts))
    rows = owner_depth(profile_facts, target=target)
    for row in rows:
        mark = "OK " if row.meets_target else "GAP"
        typer.echo(
            f"{mark} {row.label} ({row.kind}): {row.source_total}/{target} bullets, "
            f"{len(row.aspects_present)}/{len(ASPECTS)} aspects"
        )
        if row.aspects_missing:
            typer.echo(f"      missing aspects: {', '.join(row.aspects_missing)}")
        if row.unclassified:
            typer.echo(f"      unclassified bullets: {row.unclassified}")
    gaps = [row for row in rows if not row.meets_target]
    if gaps:
        typer.echo(
            f"\n{len(gaps)} of {len(rows)} owners are below the supply target. "
            "Run `profile coach` to add bullets for them."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_depth.py -v && ruff check`
Expected: PASS.

Then confirm the CLI runs against the real workspace:
Run: `.venv/Scripts/python.exe -m resume_tailor_harness.cli profile depth`
Expected: `GAP` rows for the roles with 3-5 source bullets, `OK` for the projects with 8+.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/depth.py src/resume_tailor_harness/cli.py tests/test_profile_depth.py
git commit -m "feat(profile): report bullet supply and aspect gaps per owner"
```

---

### Task 9: Render-side depth critique

**Files:**
- Create: `src/resume_tailor_harness/tailor/depth.py`
- Modify: `src/resume_tailor_harness/tailor/workflow.py:118-150`
- Test: `tests/test_tailor_depth.py`

**Interfaces:**
- Consumes: `evidence_owners`, `OwnerRef` (Task 6); `clamped_floor` (Task 6); `LengthBudget` (Task 5).
- Produces:
  - `DEPTH_REVIEWER: str = "bullet-depth"`
  - `DepthCritique(ReviewCritique)` with extra fields `owners_total: int`, `owners_met: int`
  - `depth_report(content, facts, budget) -> DepthReport`
  - `depth_critique(content, facts, budget) -> DepthCritique | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_depth.py
from resume_tailor_harness.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_tailor_harness.models.review import Severity
from resume_tailor_harness.tailor.depth import DEPTH_REVIEWER, depth_critique
from resume_tailor_harness.tailor.review_config import LengthBudget


def _facts(rich_aspects: bool = True) -> ProfileFacts:
    aspects = ["scope", "technical", "impact", "collaboration", "leadership"]
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e_rich",
                company="Aptiv",
                title="Triage",
                bullets=[
                    Bullet(
                        id=f"b{n}",
                        text=f"thing {n}",
                        aspect=aspects[n % 5] if rich_aspects else "technical",
                    )
                    for n in range(9)
                ],
            ),
            Experience(
                id="e_thin",
                company="MAXIEYE",
                title="Intern",
                bullets=[Bullet(id=f"t{n}", text=f"other {n}") for n in range(3)],
            ),
        ],
    )


def _resume(counts: dict[str, int], aspect_of: dict[str, str] | None = None) -> ResumeContent:
    aspect_of = aspect_of or {}
    return ResumeContent(
        contact=Contact(name="A"),
        experience=[
            TailoredExperience(
                company=owner_id,
                title="T",
                provenance=owner_id,
                bullets=[
                    TailoredBullet(
                        text=f"rendered {n}",
                        provenance=("b" if owner_id == "e_rich" else "t") + str(n),
                    )
                    for n in range(count)
                ],
            )
            for owner_id, count in counts.items()
        ],
    )


def test_meeting_every_clamped_floor_produces_no_major_issues():
    critique = depth_critique(_resume({"e_rich": 5, "e_thin": 3}), _facts(), LengthBudget())
    assert critique is not None
    assert critique.reviewer == DEPTH_REVIEWER
    assert critique.score == 100
    assert [i for i in critique.issues if i.severity is Severity.major] == []


def test_under_rendering_an_owner_with_supply_is_a_major_issue():
    critique = depth_critique(_resume({"e_rich": 1, "e_thin": 3}), _facts(), LengthBudget())
    majors = [i for i in critique.issues if i.severity is Severity.major]
    assert len(majors) == 1
    assert "e_rich" in majors[0].message
    assert "1" in majors[0].message and "5" in majors[0].message
    assert critique.score == 50


def test_a_supply_limited_owner_at_its_clamped_floor_is_never_an_issue():
    """The reviser cannot conjure a 10th MAXIEYE bullet; only the profile owner can."""
    critique = depth_critique(_resume({"e_rich": 5, "e_thin": 3}), _facts(), LengthBudget())
    assert all("e_thin" not in issue.message for issue in critique.issues)


def test_dropping_a_planned_owner_entirely_is_a_major_issue():
    """The observed exp_bullets=[5] regression: three roles vanished silently."""
    critique = depth_critique(_resume({"e_rich": 5}), _facts(), LengthBudget())
    majors = [i for i in critique.issues if i.severity is Severity.major]
    assert len(majors) == 1
    assert "e_thin" in majors[0].message
    assert "absent" in majors[0].message
    assert critique.score == 50


def test_monotone_aspects_are_a_minor_issue_not_a_major_one():
    critique = depth_critique(
        _resume({"e_rich": 5, "e_thin": 3}), _facts(rich_aspects=False), LengthBudget()
    )
    minors = [i for i in critique.issues if i.severity is Severity.minor]
    assert len(minors) == 1
    assert "e_rich" in minors[0].message
    assert [i for i in critique.issues if i.severity is Severity.major] == []


def test_unclassified_bullets_never_raise_an_aspect_issue():
    critique = depth_critique(_resume({"e_rich": 5, "e_thin": 3}), _facts(), LengthBudget())
    assert all("e_thin" not in issue.message for issue in critique.issues)


def test_a_profile_with_no_owners_yields_no_measurement():
    empty = ProfileFacts(contact=Contact(name="A"))
    assert depth_critique(ResumeContent(contact=Contact(name="A")), empty, LengthBudget()) is None


def test_depth_critique_is_advisory_and_never_a_gate():
    critique = depth_critique(_resume({"e_rich": 1}), _facts(), LengthBudget())
    assert critique.passed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_depth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.tailor.depth'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/tailor/depth.py
"""Did the resume render the depth its evidence supports?

Mirrors `tailor/coverage.py` deliberately - same advisory-not-a-gate posture,
same runtime-marker subtype, same "a measurement or None, never 0" score.

The audience split is the design. Under-RENDERING is the reviser's to fix and
rides as a major issue. Under-SUPPLY is not: the reviser cannot conjure a tenth
source bullet, and `tailor/CLAUDE.md` already records what happens when an
unfixable complaint enters the loop - it "would hand the writer an unwinnable
round". Supply lives in `profile/depth.py` and reaches the profile owner.
"""

from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.models.review import ReviewCritique, ReviewIssue, Severity
from resume_tailor_harness.profile.depth import OwnerRef, evidence_owners
from resume_tailor_harness.tailor.length import clamped_floor
from resume_tailor_harness.tailor.review_config import LengthBudget

DEPTH_REVIEWER: str = "bullet-depth"


class DepthCritique(ReviewCritique):
    """Runtime marker for the advisory depth measurement.

    Exactly the role `CoverageCritique` plays: the persisted shape stays
    `ReviewCritique`, and this subtype exists only while a round is aggregated
    so a configured reviewer named `bullet-depth` is never shadowed by the
    deterministic measurement. `bullet-depth` is NOT in
    RESERVED_REVIEWER_NAMES, for the same reason `must-have-coverage` is not.
    """

    owners_total: int = 0
    owners_met: int = 0


class OwnerDepth(ExtensibleModel):
    id: str
    label: str
    floor: int
    rendered: int
    aspects_rendered: list[str] = Field(default_factory=list)
    absent: bool = False


class DepthReport(ExtensibleModel):
    owners: list[OwnerDepth] = Field(default_factory=list)


def _rendered_counts(content: ResumeContent) -> dict[str, int]:
    """Bullets rendered per source-owner id, keyed by the owner's provenance."""
    counts: dict[str, int] = {}
    for entry in (*content.experience, *content.projects):
        counts[entry.provenance] = counts.get(entry.provenance, 0) + len(entry.bullets)
    return counts


def _rendered_aspects(
    content: ResumeContent, owner: OwnerRef
) -> list[str]:
    """Aspects of the source bullets this resume actually cited for one owner."""
    by_id = {bullet.id: bullet.aspect for bullet in owner.bullets}
    aspects: list[str] = []
    for entry in (*content.experience, *content.projects):
        if entry.provenance != owner.id:
            continue
        for bullet in entry.bullets:
            aspect = by_id.get(bullet.provenance)
            if aspect and aspect not in aspects:
                aspects.append(aspect)
    return aspects


def depth_report(
    content: ResumeContent, facts: ProfileFacts, budget: LengthBudget
) -> DepthReport:
    """Per-owner floor, rendered count, and rendered aspect spread."""
    counts = _rendered_counts(content)
    owners = [
        OwnerDepth(
            id=owner.id,
            label=owner.label,
            floor=clamped_floor(owner, budget),
            rendered=counts.get(owner.id, 0),
            aspects_rendered=_rendered_aspects(content, owner),
            absent=owner.id not in counts,
        )
        for owner in evidence_owners(facts)
        if owner.bullets
    ]
    return DepthReport(owners=owners)


def _issues(report: DepthReport, budget: LengthBudget) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for owner in report.owners:
        if owner.absent:
            issues.append(
                ReviewIssue(
                    severity=Severity.major,
                    location=f"experience/{owner.id}",
                    message=(
                        f"{owner.label!r} ({owner.id}) is in the depth plan with "
                        f"{owner.floor} bullets available but is absent from this resume"
                    ),
                    suggestion=(
                        "add the entry and render its bullets; every owner in the "
                        "BULLET DEPTH PLAN must appear"
                    ),
                )
            )
            continue
        if owner.rendered < owner.floor:
            issues.append(
                ReviewIssue(
                    severity=Severity.major,
                    location=f"experience/{owner.id}",
                    message=(
                        f"{owner.label!r} ({owner.id}) rendered {owner.rendered} "
                        f"bullets against a supply-clamped floor of {owner.floor}"
                    ),
                    suggestion=(
                        "add bullets from this owner's remaining cited facts until "
                        "it reaches its stated range in the BULLET DEPTH PLAN"
                    ),
                )
            )
        if (
            owner.rendered >= 3
            and len(owner.aspects_rendered) == 1
        ):
            issues.append(
                ReviewIssue(
                    severity=Severity.minor,
                    location=f"experience/{owner.id}",
                    message=(
                        f"{owner.label!r} ({owner.id}) rendered {owner.rendered} "
                        f"bullets all covering one aspect "
                        f"({owner.aspects_rendered[0]})"
                    ),
                    suggestion=(
                        f"cover at least {budget.min_aspects_per_owner} different "
                        "aspects - scale, technical work, measured impact, "
                        "collaboration, leadership, process, tooling, problem-solving"
                    ),
                )
            )
    return issues


def depth_critique(
    content: ResumeContent, facts: ProfileFacts, budget: LengthBudget
) -> DepthCritique | None:
    """Advisory depth rate, or None when there is nothing to measure."""
    report = depth_report(content, facts, budget)
    if not report.owners:
        return None
    met = sum(
        1
        for owner in report.owners
        if not owner.absent and owner.rendered >= owner.floor
    )
    return DepthCritique(
        reviewer=DEPTH_REVIEWER,
        # The denominator is the PLAN, not the resume. Scoring only the owners
        # that reached the page would let a resume that dropped three roles
        # score 100%.
        score=round(100 * met / len(report.owners)),
        passed=True,
        owners_total=len(report.owners),
        owners_met=met,
        issues=_issues(report, budget),
    )
```

Wire it into `_deterministic_critiques` in `src/resume_tailor_harness/tailor/workflow.py`. The function needs the budget, which it can read from the config — add a `config: ReviewConfig` parameter and pass `self.request.config` from `_WorkflowState.record`:

```python
    if (coverage := coverage_critique(content, skill_context)) is not None:
        critiques.append(coverage)
    if (
        depth := depth_critique(content, profile_facts, config.length_budget)
    ) is not None:
        critiques.append(depth)
```

Extend the docstring's closing paragraph to say that depth rides alongside coverage on identical terms — advisory, runtime-marked, never a gate.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tailor/depth.py src/resume_tailor_harness/tailor/workflow.py tests/test_tailor_depth.py
git commit -m "feat(tailor): measure rendered bullet depth as an advisory critique"
```

---

### Task 10: Aspect classification

**Files:**
- Create: `src/resume_tailor_harness/profile/aspect_classifier.py`
- Modify: `src/resume_tailor_harness/services/profile_build.py` (call the backfill inside `run_corpus_build`)
- Test: `tests/test_profile_aspect_classifier.py`

**Interfaces:**
- Consumes: `ASPECTS`, `ASPECT_DESCRIPTIONS` (Task 1); `evidence_owners` (Task 6).
- Produces:
  - `AspectAssignment` — pydantic model: `bullet_id: str`, `aspect: Aspect`
  - `AspectBatch` — pydantic model: `assignments: list[AspectAssignment]`
  - `async def classify_aspects(facts: ProfileFacts, agent: Runner) -> ProfileFacts`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_aspect_classifier.py
from resume_tailor_harness.models.profile import Bullet, Contact, Experience, ProfileFacts, Project
from resume_tailor_harness.profile.aspect_classifier import (
    AspectAssignment,
    AspectBatch,
    classify_aspects,
)


class _RunOutput:
    """Minimal stand-in for agno's RunOutput.

    `expect_schema` reads `result.content` (llm_runner.py:550), so a fake that
    returns the schema object directly would fail the isinstance check and raise
    UnparsedAgentOutput. The fake must wrap it.
    """

    def __init__(self, content: AspectBatch) -> None:
        self.content = content


class _FakeAgent:
    """Returns a fixed batch; records the prompts it was given.

    Matches the `Runner` protocol (llm_runner.py:33): `async def arun(self,
    prompt: str) -> Any`.
    """

    def __init__(self, batch: AspectBatch) -> None:
        self.batch = batch
        self.prompts: list[str] = []

    async def arun(self, prompt: str) -> _RunOutput:
        self.prompts.append(prompt)
        return _RunOutput(self.batch)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e1",
                company="C",
                title="T",
                bullets=[
                    Bullet(id="b1", text="Cut triage time 40%"),
                    Bullet(id="b2", text="Mentored three engineers", aspect="leadership"),
                ],
            )
        ],
        projects=[Project(id="p1", name="P", highlights=[Bullet(id="h1", text="Built a parser")])],
    )


async def test_only_unclassified_bullets_are_sent_to_the_model():
    agent = _FakeAgent(AspectBatch(assignments=[]))
    await classify_aspects(_facts(), agent)
    prompt = agent.prompts[0]
    assert "b1" in prompt and "h1" in prompt
    assert "b2" not in prompt


async def test_assignments_land_on_experience_and_project_bullets_alike():
    agent = _FakeAgent(
        AspectBatch(
            assignments=[
                AspectAssignment(bullet_id="b1", aspect="impact"),
                AspectAssignment(bullet_id="h1", aspect="technical"),
            ]
        )
    )
    result = await classify_aspects(_facts(), agent)
    assert result.experience[0].bullets[0].aspect == "impact"
    assert result.projects[0].highlights[0].aspect == "technical"


async def test_an_already_classified_bullet_survives_a_rebuild():
    """Not the strip-and-re-derive treatment inferred skills get: a
    hand-corrected aspect must not be recomputed."""
    agent = _FakeAgent(
        AspectBatch(assignments=[AspectAssignment(bullet_id="b2", aspect="impact")])
    )
    result = await classify_aspects(_facts(), agent)
    assert result.experience[0].bullets[1].aspect == "leadership"


async def test_an_unknown_bullet_id_in_the_response_is_ignored_not_raised():
    agent = _FakeAgent(
        AspectBatch(assignments=[AspectAssignment(bullet_id="ghost", aspect="impact")])
    )
    result = await classify_aspects(_facts(), agent)
    assert result.experience[0].bullets[0].aspect is None


async def test_a_fully_classified_profile_makes_no_model_call():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        experience=[
            Experience(
                id="e1", company="C", title="T",
                bullets=[Bullet(id="b1", text="x", aspect="impact")],
            )
        ],
    )
    agent = _FakeAgent(AspectBatch(assignments=[]))
    await classify_aspects(facts, agent)
    assert agent.prompts == []
```

> **Deviation from the spec, deliberate.** Spec §2 says new bullets get an
> aspect "at extraction time, in the fragment, synthesis, and project
> extractors." This task implements the build-time backfill only, because
> `run_corpus_build` runs the backfill after every merge — so a bullet a fresh
> extraction just produced is unclassified for microseconds and then classified
> by the same pass. Adding an `aspect` field to three extractor output schemas
> would spend three prompts' worth of attention budget to reach the identical
> end state, and would put aspect classification inside prompts whose job is
> fact extraction. One classifier, one prompt, one place to fix it.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_aspect_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.profile.aspect_classifier'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/profile/aspect_classifier.py
"""Assign an aspect to each unclassified bullet.

Idempotent by construction: only bullets with `aspect is None` are sent, so a
hand-corrected aspect survives every rebuild. This is deliberately NOT the
strip-and-re-derive treatment `profile build` gives inferred skills - an aspect
is a durable classification of a fact, not a derived artifact.

Classification never changes bullet text and never creates or removes a bullet,
so it cannot touch fact-lock.
"""

from pydantic import Field

from resume_tailor_harness.llm_runner import Runner, expect_schema
from resume_tailor_harness.models.base import ExtensibleModel
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.profile.aspects import ASPECT_DESCRIPTIONS, ASPECTS, Aspect
from resume_tailor_harness.profile.depth import evidence_owners


class AspectAssignment(ExtensibleModel):
    bullet_id: str
    aspect: Aspect


class AspectBatch(ExtensibleModel):
    assignments: list[AspectAssignment] = Field(default_factory=list)


_INSTRUCTIONS = (
    "Classify each resume bullet under exactly one aspect from the closed list "
    "below. Judge only what the bullet says; never infer beyond its text. "
    "Return one assignment per bullet id you were given.\n\nASPECTS:\n"
    + "\n".join(f"- {name}: {ASPECT_DESCRIPTIONS[name]}" for name in ASPECTS)
)


async def classify_aspects(facts: ProfileFacts, agent: Runner) -> ProfileFacts:
    """Return a copy with every previously-unclassified bullet given an aspect."""
    output = facts.model_copy(deep=True)
    pending = [
        bullet
        for owner in evidence_owners(output)
        for bullet in owner.bullets
        if bullet.aspect is None
    ]
    if not pending:
        return output

    listing = "\n".join(f"- {bullet.id}: {bullet.text}" for bullet in pending)
    response = await agent.arun(f"{_INSTRUCTIONS}\n\nBULLETS:\n{listing}")
    # `source` is a REQUIRED keyword argument (llm_runner.py:544) - it names the
    # call site in the UnparsedAgentOutput diagnostic. Never omit it.
    batch = expect_schema(response, AspectBatch, source="aspect-classifier")

    by_id = {bullet.id: bullet for bullet in pending}
    for assignment in batch.assignments:
        bullet = by_id.get(assignment.bullet_id)
        if bullet is not None:
            bullet.aspect = assignment.aspect
    return output
```

> `evidence_owners` returns `OwnerRef`s holding `list(...)` **copies** of the bullet lists. Mutating a bullet through that copy still mutates the same `Bullet` objects (the list is copied, the elements are not), so assignment propagates into `output`. Confirm this with `test_assignments_land_on_experience_and_project_bullets_alike` — if it fails, iterate `output.experience` and `output.projects` directly instead.

In `src/resume_tailor_harness/services/profile_build.py`, call `classify_aspects` inside `run_corpus_build` after facts are merged and ids assigned, and before the facts+matrix pair is written. Build the agent at the `cheap` tier through the existing `build_model` / `model_for_tier` seam, matching how the neighbouring profile agents are constructed in that module. A classification failure must be a **build warning**, not a build failure — an unclassified bullet is valid.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/profile/aspect_classifier.py src/resume_tailor_harness/services/profile_build.py tests/test_profile_aspect_classifier.py
git commit -m "feat(profile): classify bullet aspects during corpus build"
```

---

### Task 11: Expose the new budget fields in the settings UI

**Files:**
- Modify: `web/src/features/settings/pages/ReviewSettingsPage.tsx`
- Test: `web/src/features/settings/pages/ReviewSettingsPage.test.tsx` (append)

**Interfaces:**
- Consumes: the regenerated `web/src/lib/api/schema.ts` from Task 5.
- Produces: nothing consumed by later tasks.

> **Scope note:** the spec puts web UI out of scope, meaning *new* surfaces. This task adds four numeric inputs to an existing form. Without it the floors that drive the whole feature are the only budget fields a user cannot edit, which is a worse outcome than the small amount of UI work. Skip this task only if you accept floors being YAML-only.

- [ ] **Step 1: Write the failing test**

```tsx
it("renders the bullet floor inputs alongside the caps", async () => {
  renderReviewSettingsPage();
  expect(await screen.findByLabelText(/minimum bullets per role/i)).toBeInTheDocument();
  expect(await screen.findByLabelText(/minimum bullets per project/i)).toBeInTheDocument();
  expect(await screen.findByLabelText(/page target/i)).toBeInTheDocument();
  expect(await screen.findByLabelText(/minimum aspects per owner/i)).toBeInTheDocument();
});
```

Match `renderReviewSettingsPage` and the query helpers to whatever the existing tests in that file already use.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- ReviewSettingsPage`
Expected: FAIL — the four labels do not exist.

- [ ] **Step 3: Write minimal implementation**

Add four number inputs to the length-budget section of `ReviewSettingsPage.tsx`, following the exact markup the neighbouring `maxBulletsPerRole` / `maxBulletsPerProject` inputs already use — same `Field` primitive, same label-for/id wiring, same change handler shape. Bind them to `pageTarget`, `minBulletsPerRole`, `minBulletsPerProject`, and `minAspectsPerOwner`.

Place each floor input immediately before its matching cap so the pairing reads as a range.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- ReviewSettingsPage && npm run typecheck && npm run lint`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/
git commit -m "feat(web): expose bullet floors and page target in review settings"
```

---

### Task 12: Documentation and end-to-end verification

**Files:**
- Modify: `src/resume_tailor_harness/tailor/CLAUDE.md`
- Modify: `src/resume_tailor_harness/profile/CLAUDE.md`
- Modify: `CLAUDE.md` (hot-paths table)

**Interfaces:**
- Consumes: everything.
- Produces: nothing.

- [ ] **Step 1: Verify the whole suite and the lint gate**

```bash
.venv/Scripts/python.exe -m pytest -q
ruff check
cd web && npm test && npm run typecheck && npm run lint
```

Expected: all green. Record the actual test counts — do not claim a number you did not read.

- [ ] **Step 2: Verify against real data**

```bash
.venv/Scripts/python.exe -m resume_tailor_harness.cli profile depth
```

Expected, from the measured corpus: `GAP` for UMich (4), Varian (5), CIM (3), MAXIEYE (3); `OK` for Aptiv only among experiences once its 9 are counted against a target of 10 — Aptiv should read `GAP` at 9/10. Projects `Automated_Signal_Plot` (50), `Field-Trip` (13), `Deep Agent` (10) read `OK`.

Then run one real tailor against a stored job and confirm the rendered shape moved. Compare against the recorded baseline of `[5, 1, 2, 2] + [2, 2]`:

```bash
.venv/Scripts/python.exe -c "
import sqlite3, json
con = sqlite3.connect('data/users/9127fd59b364/resume_tailor_harness.db')
for rid, cj in con.execute('select id, content_json from resume_versions order by created_at desc limit 3'):
    c = json.loads(cj)
    print(rid, [len(e['bullets']) for e in c['experience']], [len(p['bullets']) for p in c['projects']])
"
```

Expected: every experience with supply at or above its clamped floor. Aptiv 5-7, UMich 4, Varian 5, CIM 3, MAXIEYE 3, projects 4-6.

- [ ] **Step 3: Update the module references**

In `src/resume_tailor_harness/tailor/CLAUDE.md`, add to the review/scoring notes:

```markdown
- **A cap without a floor reads as zero.** `format_budget` used to state
  `max_bullets_per_role` plus a shared `target_total_bullets` pool plus "drop
  the rest". Measured across 30 stored versions, role #1 hit the cap in 30/30
  and role #2 in 0/30 — spending the pool top-down is the correct reading of
  that instruction. `LengthBudget` now carries floors, and `format_depth_plan`
  hands the writer a per-owner render range **already clamped to the owner's
  source-bullet count**, because a floor of 5 against 3 source bullets is an
  instruction to invent that `check_provenance` then rejects at the cost of a
  round. This is the same failure `target_skills` documents and the same one
  every provider's unset `thinking` config produced.
- **Depth splits by audience, and that split is the design.** Under-rendering
  is the reviser's to fix and rides as a major issue from `tailor/depth.py`.
  Under-supply is not — the reviser cannot conjure a tenth source bullet — so
  it lives in `profile/depth.py` and reaches the profile owner through
  `profile depth`. Routing it into the tailor loop would hand the writer an
  unwinnable round, exactly as a must-have-coverage gate would.
  `bullet-depth` is advisory, runtime-marked by `DepthCritique`, and
  deliberately absent from `RESERVED_REVIEWER_NAMES`.
- **The depth score's denominator is the plan, not the resume.** Scoring only
  owners that reached the page would let a resume that silently dropped three
  roles score 100% — an observed regression (`exp_bullets=[5]`).
```

In `src/resume_tailor_harness/profile/CLAUDE.md`, add:

```markdown
- **Project highlights are addressable facts.** `Project.highlights` holds
  `Bullet`s, not strings, so `index_facts` registers a per-highlight id and the
  provenance gate can reject a fabricated project bullet. A `mode="before"`
  validator still accepts a legacy `list[str]`. `merge.py` used to flatten
  stub bullets to text and discard ids that already existed.
- **Bullet aspects are durable, not derived.** `profile build` classifies only
  bullets with `aspect is None`, so a hand-corrected aspect survives a rebuild.
  Unlike inferred skills, aspects are never stripped and re-derived. An
  unclassified bullet is valid and simply invisible to the diversity rule.
```

In the root `CLAUDE.md` hot-paths table, add rows for `profile/depth.py`, `tailor/depth.py`, and `profile/aspects.py`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/resume_tailor_harness/tailor/CLAUDE.md src/resume_tailor_harness/profile/CLAUDE.md
git commit -m "docs: record the bullet-depth invariants"
```

---

## Verification Checklist

Before calling this done, confirm each with actual command output — not inference:

- [ ] `.venv/Scripts/python.exe -m pytest -q` passes; note the count.
- [ ] `ruff check` is clean.
- [ ] `cd web && npm test && npm run typecheck && npm run lint` pass.
- [ ] An existing pre-change `facts.json` loads without error (Task 2's validator).
- [ ] An existing pre-change `resume_versions.content_json` still deserializes.
- [ ] A fabricated project-highlight id fails `check_provenance` (Task 4).
- [ ] `profile depth` reports `GAP` for the four thin roles.
- [ ] A real tailor run renders at or above each clamped floor.
- [ ] No new name appears in `DETERMINISTIC_GATES` or `RESERVED_REVIEWER_NAMES`.
- [ ] `git log --oneline` shows one commit per task.
