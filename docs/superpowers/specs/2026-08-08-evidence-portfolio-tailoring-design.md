# Evidence-portfolio resume tailoring

**Status:** Approved for implementation  
**Date:** 2026-08-08

## Problem

The tailoring pipeline already exposes deterministic must-have coverage and
fact-lock gates, but generation still receives the whole profile and chooses
roles, projects, and bullets in one pass. That makes selection inconsistent:
strong but irrelevant facts can consume the one-page budget, matching projects
can lose to weak work-history bullets, and job terminology is not consistently
bound to the facts that authorize it.

The existing optional match plan maps requirements to fact ids, but it is
transient, disabled by default, and does not allocate resume space, validate
parent/child relationships, explain omissions, or drive rendering.

## Goals

1. Rank the job's material requirements and select the strongest truthful work
   and project evidence before drafting.
2. Let the writer adopt job terminology only when a profile fact or explicit
   alias authorizes it.
3. Emphasize the top three to five evidenced required skills in the resume and
   explain the selection in the job UI.
4. Preserve the complete profile as the source of truth for provenance and
   fact-check review.
5. Degrade safely to a deterministic portfolio when the planner fails.

## Non-goals

- No pin, exclude, or approval controls in the first version.
- Adjacent skills may guide selection but never become claimed required skills.
- The existing score threshold and fact-lock gates do not change.
- Custom templates are not required to render highlights; they receive an
  optional input and may opt in.
- The feature is not enabled by default until the recorded evaluation and blind
  comparison gates pass.

## Architecture

### Evidence catalog

Build an internal deterministic catalog from `ProfileFacts`, `JobCriteria`, and
the existing `SkillMatchContext`. Each experience and project owner records its
nested facts, dates, metric-bearing evidence, stable source order, and direct or
adjacent job-skill links. Direct evidenced must-haves outrank supporting job
skills, quantified evidence, recency/strength, and finally stable source order.
This same precedence produces the rule-based fallback.

### Evidence portfolio

One structured planning call per enabled job attempt returns an
`EvidencePortfolio` containing:

- ranked skill and responsibility requirements with covered, adjacent, or gap
  state and supporting fact ids;
- selected experiences and projects, exact bullet ids, requirement links,
  allocated bullet counts, and concise rationales;
- selected skill fact ids, section ordering, three to five approved highlight
  terms, and a small list of meaningful omissions;
- frozen source excerpts needed to explain the decision later without reading
  a potentially changed profile.

The portfolio stores concise decisions, not hidden chain-of-thought.

### Normalization and fallback

Treat the planner result as untrusted. Normalization removes unknown ids,
rejects a nested fact under the wrong owner, enforces the shared page budget,
deduplicates selections, and permits displayed job terms only when the selected
fact name or an explicit alias supports them. Gap and adjacent requirements
cannot contribute highlight or claimed-skill terms.

The budget defaults are four experiences, two projects, five evidence owners,
five bullets per role, three bullets per project, and twenty bullets total.
Selected work remains reverse-chronological; selected projects are ordered by
relevance. A continuity-only role may carry at most one bullet.

If the planner raises, returns unparsed output, or normalizes to an unusable
portfolio, tailoring continues with the deterministic portfolio and records a
safe warning/status for the UI.

### Generation and review

The writer and reviser receive the normalized portfolio and a profile slice in
which experience, projects, and skills are restricted to portfolio-approved
facts. Other factual sections retain today's availability. The job description
may change selection, action phrasing, and emphasis, but not scope, ownership,
technologies, dates, or outcomes.

Provenance and fact-check review continue against the full profile. A new
advisory alignment critique checks whether highlighted core skills appear in
the skills list and, where the portfolio contains supporting bullet evidence,
in contextual experience or project prose. Its issues reach the reviser but do
not create an unwinnable gate.

## Persistence and interfaces

Every resume version in a tailoring attempt stores the same frozen portfolio
JSON and status. User revisions inherit the parent portfolio, use an `inherited`
status, and report realized facts outside the original selection instead of
rewriting history. Older versions have no portfolio and remain valid.

`JobDetail` exposes only whether a portfolio is available and its status. An
authenticated per-version endpoint lazily returns the detailed explanation.
The web version row renders an accessible, responsive "Why this evidence?"
disclosure with core requirements, selected evidence excerpts, omissions, and
fallback state.

Rendering receives validated highlight terms outside resume prose. The bundled
Classic template bolds exact approved terms in summary, bullets, and skill
entries while retaining numeric highlighting and identical extracted ATS text.

`evidence_portfolio_enabled` is the canonical configuration field. The legacy
`match_plan_enabled` spelling remains a one-release alias; contradictory values
are rejected.

## Testing and rollout

Focused tests cover catalog ranking, normalization, fallback, profile slicing,
sync/async workflow parity, persistence, inheritance, authorization, rendering,
and UI accessibility. Selection eval cases cover competing roles, strong
projects, career changes, overlong profiles, aliases, and adjacent-skill traps.

The feature begins default-off. Default-on requires all of the following with
identical baseline/candidate models and settings:

- at least 90% mandatory-evidence recall and zero forbidden or gap claims;
- at least five points of mean relevance improvement;
- no provenance, fact-lock, or trap-recall regression;
- at least seven wins in a blind comparison of ten representative real jobs.

Latency, token cost, fallback rate, and artifacts are recorded even though cost
is not the deciding gate. If any gate fails, the feature remains opt-in.
