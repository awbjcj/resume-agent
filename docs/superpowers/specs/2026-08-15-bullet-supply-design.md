# Bullet supply: anchored coach notes, gap-seeded agendas, unmined-source questioning

Date: 2026-08-15
Status: design approved, unimplemented
Scope: Spec B of three — see [2026-08-15-bullet-depth-design.md](2026-08-15-bullet-depth-design.md)
Depends on: Spec A (`owner_depth`, `evidence_owners`, the `Aspect` vocabulary)

## Problem

Spec A clamps every render floor to available supply, so a role holding three
source bullets renders three no matter what the budget asks for. Closing that
gap needs new facts, and facts are elicited or extracted — never generated.

The measured supply:

| Experience | Source bullets |
| --- | --- |
| Aptiv — Vehicle System Triage Engineer | 9 |
| Varian — Systems Engineering Intern | 5 |
| UMich — Graduate Student Instructor | 4 |
| Contemporary Intelligent Mfg — Co-op | 3 |
| Shanghai MAXIEYE — Systems Engineering Intern | 3 |

The Profile Coach exists to elicit exactly this. It has never been used:

```
$ ls data/users/*/profile/coach/     -> empty, both workspaces
$ find data/users -name "note--*.md" -> nothing
```

Zero sessions, zero saved notes. The path is wired end to end but unexercised,
and it contains a defect that would surface on first use.

### The anchoring defect

An approved draft becomes a corpus document, not a fact:

```
coach turn -> DraftNote(summary + verbatim quotes)
  -> approve_draft()                       services/profile_coach.py:324
    -> intake.add_note_source(...)
      -> _stage_and_add(..., mode="literal")   profile/intake.py:28
        -> profile build -> extract_fragments -> merge_fragments
          -> _same_experience()                merge.py:181
```

`_same_experience` requires an exact normalized **company** match, then either
an exact title match or >=50% title-token overlap **with confirmed date
overlap**. A note saying "At Aptiv I cut triage time 40%" yields title tokens
`{triage, engineer}` against the profile's `{vehicle, system, triage, engineer,
technical, lead, vsda, team}` — Jaccard ~0.22 — and states no dates, so
`_date_ranges_overlap` returns `None` and the token-overlap branch (which
requires `overlap is True`) cannot fire either.

**The elicited bullets would not attach to the role they are about.** They
would land as a duplicate `Experience`, or through the synthesis path as a
fallback project (`merge.py:527`).

### Why re-extraction was cut

Spec A's decomposition named Spec B as "coach depth topic + aspect-aware corpus
re-extraction". The re-extraction half is **dropped**. Measured against the
live corpus, facts by source document:

```
  82  resume-38978903                  (resume.pdf)
  34  github-vsda-deep-agent-...       (and 11 more GitHub dossiers, 11-31 each)
   6  2025-goal-setting-32db5b3e       6 facts, ZERO experience bullets
   -  2026-goal-setting                absent entirely: ZERO facts
```

All 24 experience bullets trace to `resume.pdf`. The two goal-setting documents
(7.3 KB of dense, on-topic material about the Aptiv role) produced no bullets —
and that is fact-lock working correctly, because every statement in them is
forward-looking:

> "Deliver automated triage dashboards/reports ... reducing manual reporting
> effort by **>=50%**."
> "achieve **>=60% reuse** across supported programs."
> "**>=30%** reduction in sync-meeting prep time."

These are targets, not outcomes. A second extraction pass with a better prompt
can only produce nothing again (correct) or produce aspirational claims (a
fact-lock breach). Neither is worth building.

The material is valuable as **question material**: ~19 named initiatives at one
role, each with a stated metric. That is an interview script. The user's answer
becomes the fact; the document only prompts the question.

## Design

### 1. Anchored coach notes

`CoachTopic` (`profile/coach_store.py:17`) gains `owner_id: str = ""`. Every
field there already defaults, so stored session JSON keeps loading.

`approve_draft` (`services/profile_coach.py:301`) already loads the session and
locates the draft by `topic_id`. It looks the topic up in the same session dict
and passes its owner through:

```python
topic = next(
    (row for row in session["topics"] if row["id"] == topic_id), None
)
doc = add_note_source(
    root, title, body, anchor=(topic or {}).get("owner_id") or None
)
```

A topic that cannot be found yields no anchor rather than an error — the draft
lookup immediately above already rejects an unknown `topic_id`, so this branch
is unreachable in practice and must not introduce a second failure mode.

`intake.add_note_source` gains `anchor: str | None = None` and stages the
document with `mode="synthesis"` when an anchor is present, `mode="literal"`
when it is not. That branch is the entire fix. Everything downstream exists:

| Step | Where | Behavior |
| --- | --- | --- |
| pin | `synthesis.py:320` | `_apply_pinned_anchor` forces every entry's `anchor_id` to `doc.anchor` |
| stub | `synthesis.py:474` | anchored entries become Experience stubs whose **`id` is the anchor target** |
| attach | `merge.py:522` | `by_id.get(stub.id)` appends bullets to that exact role |
| dedup | `merge.py:540` | normalized-text dedup against existing bullets |

No restriction needs lifting. `SourceManifest.validate_docs` already permits an
anchor on a synthesis-mode document; the guard it enforces
(`anchor requires synthesis mode`) is satisfied rather than relaxed.
`read_document_text` handles `.md` natively (`resume_reader.py:28`) and
`extract_synthesis_fragments` selects on `doc.mode`, never on file suffix, so a
markdown note in synthesis mode needs no reader change.

**Synthesis is the right path on its own merits, not merely a route to
anchoring.** It is verified extraction — synthesize, verify against source
excerpts, one repair round. A coach note's source text is the user's verbatim
quotes: ADR 0005 requires every draft note to retain them and
`render_note_body` refuses a note carrying none. So each generated bullet is
entailment-checked against what the user actually said. Literal mode performs
no such check.

An unanchored note — from a topic the model added mid-session, which carries no
`owner_id` — keeps today's `literal` behavior exactly. The degradation is
silent and safe.

### 2. Deterministic agenda seeding

`profile/depth.py` gains `depth_topics(facts, target) -> list[CoachTopic]`,
built from Spec A's `owner_depth()`. One topic per below-target owner, in
`evidence_owners` order (resume order, current role first), truncated to
`AGENDA_CAP` (12, `coach.py:38`):

```
id:             t1
owner_id:       exp_umich
gap:            "UMich - Graduate Student Instructor has 4 of 10 source bullets;
                 no evidence yet for impact, scope, tooling, problem"
why_it_matters: "a role with 4 bullets renders 4; the resume can only show
                 what the profile holds"
related_ref:    exp_umich
```

Today the agenda is entirely LLM-proposed: `normalize_opening` (`coach.py:111`)
reads `turn.topics` from the model's opening response. Under this design the
seeded list is passed in and the model's proposals are **appended** to it.

`normalize_opening` currently raises `TurnRejected("opening turn proposed no
topics")` when the model returns none. That rejection now fires only when the
agenda is empty from *both* sources, which means the profile has no gaps and
the model found nothing to add — a legitimate "nothing to work on" state rather
than a malformed turn. The message changes accordingly.

`AGENDA_CAP` applies to the **combined** list, and seeded topics take
precedence: seeding truncates to the cap first, then the model's proposals fill
whatever remains. A profile with 12 or more below-target owners therefore
leaves the model no room to add any — which is correct, because a profile that
thin has nothing more urgent to discuss than its own gaps.

Only seeded topics carry `owner_id`. Model-added topics do not, and their notes
stay unanchored.

`profile_overview` (`coach.py:288`) already reports per-owner counts
(`experience e1: Aptiv - Triage | 9 bullets, 3 with metrics`) but states no
target and no aspect breakdown. It gains both, so the counts it prints and the
agenda it drives agree.

### 3. Unmined-source questioning

`profile/depth.py` gains:

```python
class UnminedSource(ExtensibleModel):
    doc_id: str
    filename: str
    fact_total: int      # facts anywhere in facts.json citing this doc

def unmined_sources(profile_dir: Path | str) -> list[UnminedSource]: ...
```

A document is unmined when it contributed **zero bullets** to any evidence
owner, measured by `source_ref` across `Experience.bullets` and
`Project.highlights`. Rows are ranked by `fact_total` ascending, so a document
that contributed nothing at all sorts ahead of one that yielded only skills. On
the live corpus this returns `2026-Goal-Setting.md` (0 facts) then
`2025-Goal-Setting.md` (6 facts, 0 bullets), and excludes `resume.pdf` and all
12 GitHub dossiers.

Their text is loaded through the existing `read_document_text` and rendered
into the coach's context as question material, bounded at **12 KB total**. The
budget is spent in the ranked order above — zero-fact documents first — and the
document that exhausts it is truncated at the boundary rather than dropped, so
a large first document cannot starve the block entirely. It rides the same
optional-context pattern `_market_gaps_report` already uses at `coach.py:320`:
wrapped so an unreadable or deleted document degrades the block away rather
than failing the turn.

**The prompt rule is the safety story, and it is one sentence: this text is
question material, never claimable fact.** Without it the coach reads
"reduce manual reporting effort by >=50%" and drafts a note asserting a 50%
reduction — laundering a target into a claim through the coaching channel,
which is the exact invention fact-lock exists to prevent.

The pipeline backs the prompt up, which is why §1's routing matters here too. A
note's verbatim quotes come from the user's own chat turns, not from the
document, so synthesis entailment verification checks each generated bullet
against what the user said. A claim sourced from the goal document but absent
from the user's words fails that check. The prompt states the rule; the
pipeline enforces it. Neither alone suffices.

The block is **not** wrapped in `prompt_blocks.untrusted()`. That fence is for
third-party text; these are the user's own uploaded documents, already fed
unfenced to every extractor in the system.

### 4. Data flow

```
owner_depth(facts)                        <- Spec A
  +- depth_topics(facts)                  -> seeded CoachTopics with owner_id
      +- opening turn agenda              (model may append; no owner_id on those)
          +- coach asks, grounded by unmined_sources(...)
              +- user answers in their own words
                  +- DraftNote(summary + verbatim quotes)
                      +- approve_draft -> add_note_source(anchor=owner_id)
                          -> sources/note--*.md   mode=synthesis, anchor=exp_umich
                              +- profile build
                                  |- synthesize -> verify against quotes -> repair
                                  |- _apply_pinned_anchor -> stub.id = exp_umich
                                  +- merge -> Experience(exp_umich).bullets += ...
                                      +- aspect classification   <- Spec A
```

The loop closes: new bullets raise `owner_depth`, which drops that owner from
the next session's seeded agenda.

## Testing

Offline, with faked agents and no network, per the project's test contract.

- `depth_topics` seeds one topic per below-target owner, in resume order,
  capped at `AGENDA_CAP`; a profile with no gaps seeds nothing.
- A seeded topic carries `owner_id`; a model-added topic does not.
- `approve_draft` on a seeded topic writes a manifest doc with
  `mode="synthesis"` and `anchor=<owner_id>`; on an unseeded topic it writes
  `mode="literal"` with `anchor=None`.
- **An anchored note's bullets land on the target experience and create no
  duplicate role.** Driven through `apply_synthesis_fragments` with a stub
  whose id is the anchor. This is the regression the current code fails, and it
  is the reason this spec exists.
- An unanchored note still merges by `_same_experience`, unchanged.
- `unmined_sources` returns both goal documents, ordered zero-fact first, and
  excludes `resume.pdf` and every GitHub dossier.
- The unmined block respects its 12 KB cap; an unreadable document degrades to
  an empty block without raising.
- `normalize_opening` accepts a turn proposing no topics when seeded topics
  exist, and still rejects one when the agenda would be empty from both
  sources.
- A coach session JSON stored before this change still loads, with `owner_id`
  defaulting to `""`.

## Out of scope

- **Aspect-aware re-extraction** — cut, with evidence, above.
- **Per-role material intake** (performance reviews, retros, Jira exports) —
  Spec C.
- **Any new web UI.** The seeded agenda renders through the existing coach
  panel; `CoachTopicOut` (`api/schemas/coach.py:26`) gains `ownerId` for
  parity but no component changes.
- Changing what `_same_experience` does. Anchored notes bypass it; unanchored
  ones keep today's behavior exactly.
