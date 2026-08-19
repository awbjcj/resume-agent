# Universal Career Capability Matrix: Profile and Match-Gap Integration

**Date:** 2026-08-19

**Status:** Proposed for implementation

**Design authority:** Universal Career Capability Matrix research handoff, effective-taxonomy read-contract handoff, and UCCM reference model

**Scope:** A compatibility-first UCCM foundation wired through profile building, job requirements, match-gap, and the downstream tailoring context

## Problem Statement

Candidates need one career-capability model that works across technical and non-technical careers, preserves the evidence behind every claim, and explains what is covered, transferable, partial, unknown, or genuinely missing for a target job. The current taxonomy is optimized around a fixed technology-heavy category hierarchy. It treats skills, tools, knowledge, tasks, and requirements too similarly; represents relatedness primarily through same-domain adjacency; and stores a profile row as a canonical label, evidence list, strength, recency, and display group. This makes the model difficult to apply consistently to finance, education, healthcare, human resources, design, consulting, public service, skilled operations, and other career families.

The current read contract is also inconsistent. Generated taxonomy data, durable user corrections, lifecycle state, and profile overrides are not guaranteed to be read through one coherent revision by profile building, match-gap, matrix freshness checks, evidence planning, and tailoring. A correction can therefore be visible in one consumer while another consumer uses a stale or incomplete view. Building a richer capability model on top of those competing reads would make the inconsistency harder to diagnose and roll back.

The match-gap experience compounds the modeling problem. Its legacy `covered`, same-domain `adjacent`, and `gap` states cannot distinguish a true absence from insufficient evidence, lower proficiency, stale experience, missing context, a strict tool mismatch, a credential requirement, or an unresolved extraction. The same-domain rule can overstate transferability, while the current result does not explain the relationship path or the candidate evidence used to reach it.

The product must introduce the Universal Career Capability Matrix without weakening candidate truth, breaking existing profiles and jobs, changing stored resume behavior without a gate, or creating a second canonical taxonomy service. All derived profile, match, and resume artifacts must be reproducible from pinned facts, taxonomy, extraction, and matching-policy revisions.

## Solution

Present candidates with a six-layer Universal Career Capability Matrix backed by a typed, versioned Career Capability Graph. The user-facing layers are Career Core Capabilities, Foundational Literacies and Work Methods, Transferable Work Functions, Domain and Industry Knowledge, Occupation and Role Capabilities, and Tools, Technologies, Standards, and Artifacts. Credentials, licenses, degrees, experience duration, work authorization, location, schedule, clearance, and physical or environmental constraints live in a separate Requirements and Context lane.

First, establish one immutable effective-taxonomy snapshot and complete revision manifest for every consumer. The snapshot combines generated taxonomy data, the durable correction ledger, lifecycle state, profile-level canonicalization overrides, graph and crosswalk versions when present, tenant overlay state, and policy revisions. Profile building, match-gap, evidence planning, tailoring, freshness checks, API projections, and stored resume versions all consume or record this same revision.

Then introduce typed graph concepts and relationships behind adapters. Existing canonical skills and aliases become an initial graph projection without changing production matching. The existing category/domain hierarchy remains available as a legacy display projection, but category or domain co-membership does not become semantic equivalence or transferability. Stable UCCM core families and transferable work-function families are seeded as governed product concepts. Profile facts become evidence-linked capability assertions, while job descriptions become typed, source-traceable requirements with explicit importance and strictness.

Add a Match Engine v2 that resolves requirements, applies hard requirement gates, retrieves bounded candidate assertions through allowed typed graph paths, compares proficiency, context, recency, and evidence, and returns a precise status with an explanation. Run it in shadow mode beside the unchanged legacy matcher until cross-industry evaluation gates pass. Match-gap adds UCCM projections and typed results additively while retaining its existing demand graph and legacy coverage fields during migration. Taxonomy relationships can improve retrieval, ranking, explanation, and development recommendations, but they never create candidate facts or rename a transferable candidate capability as the requested target term.

## User Stories

1. As a candidate in any career family, I want my capabilities organized in a model that is not technology-centric, so that my profile represents the work I can actually do.
2. As a candidate, I want to see my capabilities across career core, foundations, work functions, domains, roles, and enablers, so that broad strengths and specific expertise are both understandable.
3. As a career changer, I want transferable capabilities separated from direct target-role experience, so that I can see credible bridges without being told I already possess the target capability.
4. As a candidate, I want every capability assertion linked to profile evidence, so that I can inspect and correct the basis of the claim.
5. As a candidate, I want literal evidence, supported inference, self-report, assessment, transfer candidate, unknown, and disputed states kept distinct, so that uncertainty is visible rather than silently converted into fact.
6. As a candidate, I want proficiency, autonomy, complexity, responsibility scope, influence scope, recency, and evidence confidence represented separately, so that seniority is not inferred from a title or one opaque score.
7. As a candidate, I want tools and technologies separated from the capabilities performed with them, so that knowing a tool is not mistaken for performing every task associated with it.
8. As a candidate, I want credentials and legal or logistical requirements separated from skills, so that eligibility constraints are never treated as semantically transferable capabilities.
9. As a candidate, I want profile corrections to remain durable across rebuilds, so that model refreshes do not erase my intent.
10. As a candidate, I want one correction to appear consistently in my profile and match-gap results, so that the product never shows contradictory classifications.
11. As a candidate, I want unknown capability status distinguished from absence, so that missing profile data prompts a question instead of an incorrect negative judgment.
12. As a candidate, I want stale or weak evidence called out separately from missing capability, so that I know whether to add evidence, refresh practice, or learn something new.
13. As a candidate, I want a strict tool mismatch distinguished from an underlying capability match, so that the development action is specific.
14. As a candidate in a regulated occupation, I want license and credential checks to require exact verified evidence and jurisdiction, so that the product does not imply eligibility incorrectly.
15. As a candidate, I want match explanations to name the candidate-side capability truthfully, so that transferable evidence is never relabeled as the employer's requested term.
16. As a candidate, I want match-gap to explain the relationship and evidence behind each result, so that I can decide whether the result is credible.
17. As a candidate, I want gaps classified as capability, subskill, proficiency, context, tool, knowledge, credential, recency, evidence, articulation, or unknown gaps, so that suggested next actions fit the deficit.
18. As a candidate, I want job requirements linked to the original job-description span, so that I can verify how the requirement was interpreted.
19. As a candidate, I want must-have, preferred, responsibility, context, credential, experience, education, availability, and physical requirements kept distinct, so that job fit reflects their different meanings.
20. As a candidate, I want exact-product requirements treated more strictly than capability requirements, so that approved alternatives are only used when the employer wording permits them.
21. As a candidate, I want broader and narrower coverage interpreted directionally, so that a general concept does not automatically satisfy a specific requirement.
22. As a candidate, I want approved transfer relationships to be directional and context-scoped, so that similarity alone cannot produce a positive match.
23. As a candidate, I want the match-gap dashboard to summarize demand by UCCM layer while preserving individual job and requirement drill-down, so that the summary remains traceable.
24. As a candidate, I want the existing skill-demand dashboard to continue working during migration, so that the redesign does not remove current filters, rankings, or taxonomy maintenance controls prematurely.
25. As a candidate, I want older profiles, jobs, and resume versions to remain readable, so that adopting UCCM does not invalidate my history.
26. As a candidate, I want profile and match artifacts to rebuild when their source facts, taxonomy, extraction policy, or matching policy changes, so that I do not unknowingly rely on stale results.
27. As a candidate, I want a safe fallback when capability typing or matching providers fail, so that an outage does not corrupt my taxonomy or assert unsupported facts.
28. As a profile-building operator, I want one application service to bind facts, effective taxonomy, assertions, and legacy matrix rows, so that profile artifacts cannot drift independently.
29. As a job-ingestion operator, I want ambiguous terms preserved as unknown with their source text, so that deterministic rules or a model are not forced to guess.
30. As a taxonomy maintainer, I want semantic identity, hierarchy, dependency, work relationships, role relationships, and transfer relationships stored as different edge types, so that matching policy can treat them safely.
31. As a taxonomy maintainer, I want stable namespaced concept identifiers and source mappings, so that external standards can be upgraded without destroying provenance.
32. As a taxonomy maintainer, I want aliases limited to lexical variants and approved true synonyms, so that related products, versions, prerequisites, and co-used concepts do not collapse into one identity.
33. As a taxonomy maintainer, I want existing learned domains and fixed categories retained as projections rather than converted into transfer edges, so that legacy structure does not create false semantic coverage.
34. As a taxonomy maintainer, I want corrections scoped to candidate, tenant, or proposed shared mappings, so that one tenant's intent cannot alter another tenant's effective taxonomy.
35. As a taxonomy maintainer, I want correction replay and revision generation to be deterministic and idempotent, so that the same inputs always reproduce the same result.
36. As a taxonomy maintainer, I want generated nodes and edges to remain proposals until validation and review gates pass, so that model instability does not rewrite the canon autonomously.
37. As a product owner, I want Match Engine v2 evaluated in shadow mode before it changes rankings or tailoring, so that richer semantics do not silently regress current behavior.
38. As a product owner, I want per-career-family quality metrics, so that strong performance in software roles cannot hide undercoverage in other industries.
39. As an evaluation owner, I want adversarial same-domain negatives, strict credentials, strict tools, direct evidence, transfer evidence, stale evidence, and unknown cases in the gold set, so that important failure modes are measured explicitly.
40. As an evaluation owner, I want each match result to retain its features, relationship path, evidence links, confidence, and policy revision, so that errors can be reproduced and adjudicated.
41. As a resume-tailoring operator, I want tailoring to receive the same pinned capability and match context as match-gap, so that evidence planning and user-visible gaps do not disagree.
42. As a resume reviewer, I want the existing fact-lock, provenance, skill-naming, numeric-evidence, and adjacent-name protections preserved, so that UCCM cannot make unsupported resume claims.
43. As an API consumer, I want UCCM fields added without removing current profile and match-gap fields, so that clients can migrate incrementally.
44. As a frontend developer, I want a single typed response for legacy demand, UCCM projections, precise match statuses, and revision metadata, so that the UI does not reconstruct semantic policy independently.
45. As an operator, I want every derived artifact to carry a resolvable revision manifest and matching-policy revision, so that incidents can be traced and rolled back.
46. As an operator, I want feature flags and reversible projections at every migration phase, so that the graph, assertion builder, or Match Engine v2 can be disabled without deleting user data.
47. As a security and privacy owner, I want corrections and evaluation signals aggregated without exposing raw personal or job text, so that shared learning does not leak tenant data.
48. As a licensing owner, I want every external source snapshot to carry license, attribution, checksum, and version metadata before import, so that restricted content cannot enter product exports accidentally.

## Implementation Decisions

### Delivery boundary and sequencing

- Deliver this design as one program with independently reversible phases. The first phase repairs the effective-taxonomy read and revision contract. Later phases add graph primitives, term typing, profile assertions, typed job requirements, shadow matching, and UCCM projections in that order.
- Do not make the typed graph or Match Engine v2 authoritative until the effective read seam is stable and the defined evaluation gates pass. The richer model must not create a second taxonomy read path.
- Use one highest cross-path behavior seam for acceptance: given profile facts, job criteria, generated taxonomy, corrections, lifecycle state, profile overrides, and pinned policies, build the saved profile capability artifact and match-gap response, then assert that both use the same effective revision and semantics.
- Treat the UCCM reference model as the vocabulary authority for layers, core families, concept types, edge types, assertion dimensions, requirement kinds, strictness, typed match statuses, revision components, and invariants.

### Canonical representation and user projections

- The canonical representation is a typed, versioned Career Capability Graph. UCCM is the principal user projection, not a second source of truth.
- Seed six career layers: career core, foundational, transferable function, domain and industry, occupation and role, and enabler. Seed the eight original UCCM core capability families and the twelve transferable work-function families from the design authority.
- Keep credentials, licenses, degrees, experience duration, work authorization, location, schedule, security clearance, and physical or environmental requirements in a separate requirement lane. They may link to capabilities through typed validation relationships but do not become candidate skills.
- Support the concept types enumerated by the reference model. A concept has independent type, granularity, reusability, career-layer, domain, occupation, locale, jurisdiction, source, status, and claim-policy facets.
- Treat current fixed categories and learned domains as legacy navigation and display projections. Their co-membership does not create `same_as`, equivalence, or transfer relationships.
- Preserve existing profile `hard`, `soft`, and `domain` values and rendered resume skill-section labels as compatibility fields. They are derived or user-authored projections, not canonical concept types.

### Concept identity, edges, and validation

- Use stable namespaced identifiers. Internal governed concepts, tenant-local concepts, and mapped external concepts retain distinct identifiers and source provenance.
- Restrict identity collapse to validated lexical aliases and approved semantic identity. Contextual equivalence, broader or narrower scope, versions, family membership, prerequisites, tool use, task support, role relevance, and transferability remain separate edge types.
- Store edge direction, status, confidence, conditions, source evidence, reviewer identity, scope, validity dates, and creation revision. Matching may only traverse edge types and directions allowed by the active policy.
- Require deterministic graph validation for identifier uniqueness, allowed source and target types, alias cycles, hierarchy cycles where prohibited, dangling edges, invalid scope, missing source metadata, and deterministic serialization.
- Model-generated concepts and edges are proposals. Deterministic gates and the configured review threshold decide whether they become part of an effective snapshot.

### One effective snapshot and complete revisions

- Extend the existing taxonomy custody boundary rather than adding a parallel service. It owns coherent reads, per-workspace mutation serialization, effective projections, and revision generation.
- The immutable effective capability snapshot contains the governed graph, tenant overlay and corrections, active policies, a deterministic legacy cluster projection, UCCM projections, lifecycle state, and a complete revision manifest.
- During the compatibility phase, the snapshot also exposes the effective legacy cluster map expected by existing consumers. All profile, match-gap, taxonomy maintenance, evidence-planning, tailoring, and freshness code receives the snapshot or a narrow adapter derived from it.
- Candidate-facing semantic precedence is generated taxonomy, then durable Workspace taxonomy corrections, then profile-specific canonicalization overrides. An explicit forbidden alias wins last for that profile. Candidate-skill exclusion and display grouping remain separate projections and do not mutate graph identity.
- The revision manifest includes internal graph version, external source snapshots when present, crosswalk revision, tenant overlay revision, generated legacy-map revision, correction-ledger revision, lifecycle-state revision, correction-policy version, matching-policy version, and a stable effective hash. Timestamps are metadata and do not participate in deterministic identity.
- Phase 0 embeds a compact manifest containing generated-taxonomy, correction-ledger, lifecycle-state, canonicalization-override, and effective hashes in every taxonomy-dependent derived artifact. The effective hash is an integrity field, not a pointer to a central registry. Facts, assertion-policy, extraction-policy, and matching-policy revisions remain separate artifact fields.
- Profile overrides that affect canonicalization participate in the effective revision. Pure display-only group corrections participate in the profile projection revision but not semantic graph identity.
- Every derived profile matrix, capability assertion set, typed job requirement set, match result, match-gap response, evidence portfolio, and stored resume version records the effective taxonomy revision plus its applicable facts, extraction, assertion-policy, and matching-policy revisions.
- Freshness checks reject an artifact when any semantically relevant revision changes. A rejected artifact triggers an explicit rebuild or a clear unavailable state; it is never silently accepted as current.

### Persistence and migration

- Introduce graph models and deterministic serialization behind repositories. A deterministic versioned document is sufficient for the initial internal graph and tenant overlay; large external source imports later use a shared queryable relational store without changing the domain interfaces.
- Keep current tenant taxonomy, correction, state, facts, matrix, and profile override artifacts readable. Legacy correction events are adapted into the effective graph and projection rather than materialized back into generated taxonomy as the primary fix.
- Add UCCM data to the profile artifact additively: capability assertions, UCCM roll-ups, assertion-policy revision, effective taxonomy revision, and legacy matrix rows. Older readers continue to consume legacy rows.
- Add typed requirements to persisted job criteria additively. Existing must-have, nice-to-have, and technology lists remain compatibility projections and remain populated for older consumers.
- Add revision metadata and typed match-context metadata to new resume versions. Existing versions without those fields remain valid and are reported as legacy or revision-unknown rather than rewritten.
- Migrations are idempotent and restartable. Converting current canonical skills creates typed `skill` concepts with legacy projection metadata, converts aliases to lexical identity edges, and leaves learned domain membership as projection metadata until reviewed semantic edges exist.
- A rollback disables the new read projection and Match Engine v2 while retaining additive UCCM data. No rollback requires deleting profile facts, corrections, assertions, or graph records.

### Corrections, tenancy, and governance

- Represent corrections as durable, append-only intent with actor, scope, action, subject, predicate and object where applicable, prior value, new value, rationale, evidence references, target revision, and timestamp.
- Support candidate, tenant, and proposed-global scopes. Candidate and tenant corrections take effect only inside their scope. Proposed-global corrections require review before entering the governed graph.
- Preserve current correction precedence and idempotent replay. Explicit user intent beats generated placement, while invalid or dangling corrections remain inert and observable rather than corrupting the snapshot.
- Expose correction conflicts and obsolete targets as actionable maintenance states. Do not silently discard them during source or graph upgrades.
- Shared learning from corrections requires de-identification, aggregation across independent cases, privacy review, and approval. Raw candidate or job text is never promoted automatically.

### Profile-building integration

- Preserve `ProfileFacts` as candidate truth. The graph can normalize, organize, retrieve, and explain facts; it cannot create candidate facts.
- After source extraction and manual-skill replay, profile building obtains one effective capability snapshot and binds the remainder of the build to that revision.
- Resolve literal profile skills and evidence-bearing inferred skills to typed concepts. Ambiguous phrases remain unresolved or `unknown`; they are not forced into a skill type.
- Build capability assertions from evidence facts, not from taxonomy membership. Each assertion records concept, status, evidence fact identifiers, context, optional proficiency dimensions, recency and usage, claimability, facts revision, taxonomy revision, and assertion-policy revision.
- Use the five-level behaviorally anchored proficiency scale from the design authority. Autonomy, complexity, responsibility scope, influence scope, and evidence confidence remain independent dimensions. Title alone cannot establish any dimension.
- Initial proficiency fields may be unknown when evidence is insufficient. Unknown values must not be defaulted to a favorable level merely to preserve the legacy strength score.
- Derive existing matrix rows from the assertion set and legacy projection so current APIs, settings, match context, and rendering continue to work. Existing strength and recency remain compatibility projections; they are not the canonical proficiency model.
- Rebuild the saved profile artifact after taxonomy classification or correction changes. The artifact is atomic and bound to both the facts revision and complete effective snapshot revision.
- Expose UCCM profile views for core families, transferable functions, domain and role capabilities, enablers, evidence quality, and development needs. Roll-ups link back to the assertions and evidence that support them.

### Job-requirement extraction

- Introduce a typed job-requirement record with stable identifier, job identifier, source span, parsed concept, concept type, requirement kind, strictness, minimum proficiency when stated, context, importance, evidence expectation, recency constraint, extraction confidence, taxonomy revision, and extraction-policy revision.
- Preserve exact source text and offsets for new extractions. Legacy job criteria without offsets are adapted with the original list item as source text and explicitly marked legacy-source provenance.
- Use deterministic rules first for credentials, degrees, experience duration, locations, schedules, work authorization, security clearance, and obvious tools. Use model assistance only for ambiguity, followed by schema and semantic validation.
- Keep unresolved phrases as unknown requirements with source provenance. Never coerce a phrase into a skill merely to satisfy a closed schema.
- Apply strictness by requirement type: exact product, product family, capability, method or standard, credential, and contextual. Credentials and legal requirements have exact verification policies and no semantic transfer.
- Continue populating the current must-have, nice-to-have, and technology projections during migration. Their values must be derivable from or reconciled with the typed records, and inconsistencies are surfaced rather than silently preferred.

### Match Engine v2

- Match one typed requirement at a time against evidence-backed capability assertions and verified requirement-lane facts.
- The pipeline resolves requirement concepts, applies hard gates, retrieves candidate assertions through bounded policy-approved graph paths, computes structured features, applies requirement-type policy, calibrates confidence, and attaches an explanation with provenance.
- Hard gates cover exact credentials and licenses, jurisdiction, work authorization, explicit non-substitutable tools or standards, and other legally or operationally strict constraints.
- Features include canonical identity, approved equivalence, relationship path and direction, task and knowledge overlap, subskill coverage, tool-family compatibility, industry and occupation context, audience or scale, proficiency, autonomy, complexity, recency, evidence directness and confidence, requirement importance, and strictness.
- Same category, same learned domain, embedding similarity, or lexical similarity alone cannot produce equivalence, coverage, or transferability.
- Store the precise statuses defined by the reference model: verified exact, verified equivalent, covered broader, covered narrower, transferable, partial, level gap, context gap, recency gap, evidence gap, tool gap, credential gap, unknown, and absent.
- A simplified UCCM UI grouping may present Covered, Transferable, Partial, Gap, and Unknown, but the precise stored status, confidence, relationship path, evidence references, and policy revision remain available.
- Transferability is directional, condition-scoped, evidence-supported, and non-claiming. It can improve ranking or suggest a development bridge but does not count as strict requirement coverage and cannot rename the candidate capability.
- Run Match Engine v2 in shadow mode beside the current exact, same-domain adjacent, and gap matcher. During shadowing, `legacyCoverage` is the actual legacy result, not a lossy mapping from the v2 status.
- After rollout gates pass, clients may use v2 as the primary display and ranking input. The legacy result remains available for a deprecation window and rollback.

### Match-gap service and API integration

- Keep the existing demand graph, target-job filters, canonical skill keys, raw demand edges, taxonomy maintenance state, and legacy coverage fields during migration.
- Add the effective taxonomy revision, matching-policy revision, typed requirements, per-requirement Match v2 results, UCCM layer identifiers, concept types, and explanation summaries to the response additively.
- Aggregate demand from typed requirements while preserving source and strictness. The browser may continue recomputing filter-local demand scores from raw edges, but it must not infer semantic match status or collapse precise gaps.
- Add UCCM roll-ups for core capabilities, transferable functions, domains, roles, and enablers. Keep requirements and context in a visibly separate lane.
- Drill-down from any roll-up shows the contributing jobs, exact requirement source text, candidate assertion or verified requirement fact, precise status, confidence, and recommended action.
- Show unknown separately from gap. Show a legacy-adjacent result distinctly from Match v2 transfer or partial coverage while shadow mode is active.
- The API response is generated from one effective snapshot and one profile artifact revision. If they do not match, the service rebuilds through the shared profile seam or returns an explicit stale state; it does not combine mismatched artifacts.
- Regenerate OpenAPI and TypeScript contracts whenever additive fields or endpoints change. Generated contracts remain the frontend source of truth.

### Tailoring and downstream compatibility

- Evidence planning and tailoring consume the same pinned profile assertions, typed requirements, match results, and effective snapshot used by match-gap.
- Keep current fact-lock, provenance, skill naming, numeric evidence, and adjacent-name behavior unchanged until a separately gated policy explicitly supersedes a legacy rule.
- Verified exact and appropriately covered narrower or broader results may guide direct evidence selection only when the supporting assertion is claimable. Transferable and partial results may guide emphasis and questions but cannot produce the target term as a candidate claim.
- Resume versions persist the complete effective taxonomy revision, matching-policy revision, profile facts revision, job-extraction revision, assertion identifiers, and match-context status used for the attempt.
- Older tailoring adapters continue to receive a deterministic legacy skill-match context derived from the same snapshot. This adapter exists for compatibility and is not an independent matcher.

### Configuration, rollout, and observability

- Use a deployment mode with `legacy`, `shadow`, and `uccm` states rather than unrelated booleans. `legacy` uses the corrected single-read seam and current matching. `shadow` computes and records v2 without changing user decisions. `uccm` exposes v2 as primary while retaining compatibility fields.
- Version assertion, extraction, correction, and matching policies independently. A policy change invalidates only artifacts whose semantics depend on it.
- Record snapshot-build latency, profile assertion counts by status and type, unresolved term rates, match-status distributions, false-transfer adjudications, correction rates, fallback rates, stale-artifact incidents, provider cost, and latency.
- Provider failure, invalid structured output, or incomplete retrieval leaves the last approved graph and corrections unchanged. The affected term or result remains unknown or failed with an observable reason.
- Do not expose hidden reasoning. Store concise decisions, feature values, relationship paths, evidence references, and policy outcomes sufficient to reproduce and explain results.

### Release gates and definition of done

- Phase 0 is done when profile building, match-gap, matrix freshness, evidence planning, tailoring, and new resume versions use or record one complete effective revision; correction-only alias, move, and merge cases agree across paths; and legacy matching behavior is otherwise unchanged.
- The graph-adapter phase is done when current canonical skills and aliases round-trip through the graph into a deterministic legacy projection, correction replay is idempotent, and legacy APIs remain contract-compatible.
- The profile and requirement phase is done when assertions and requirements retain evidence or source spans, ambiguous cases remain unknown, requirement-lane types are separated, and legacy projections remain readable.
- Shadow matching is done when every v2 result is reproducible from stored revisions and the cross-industry evaluation report meets approved release thresholds.
- UCCM mode is done when profile and match-gap expose the layered projections accessibly, tailoring consumes the same snapshot, rollback to shadow or legacy is verified, and no existing stored profile, job, or resume artifact becomes unreadable.

## Testing Decisions

- Prefer behavior tests at the shared profile-and-match application seam over tests of individual loaders. The primary acceptance fixture supplies facts, generated taxonomy, correction ledger, lifecycle state, profile overrides, job criteria, and policies; runs profile building and match-gap; and verifies the same revision, concepts, assertions, legacy rows, requirements, and match outcomes in both artifacts.
- Preserve focused unit tests only for domain invariants that are difficult to diagnose through the high seam: graph validation, deterministic hashing, correction replay, bounded traversal, hard requirement gates, feature calculation, and compatibility projection.
- Extend existing prior art from taxonomy custody tests, profile matrix tests, profile-build service tests, match-gap projection and API tests, tailoring service tests, OpenAPI drift tests, frontend aggregation and component tests, and prompt-contract tests.
- Add a correction regression in which an alias, skill-to-domain move, and domain merge exist only in the correction ledger. Profile building, match-gap, legacy tailoring context, and stored revision metadata must all observe the correction without materializing it into generated taxonomy.
- Test revision sensitivity independently for generated taxonomy, correction ledger, lifecycle state, canonicalization overrides, graph version, tenant overlay, crosswalk, assertion policy, extraction policy, and matching policy. Reordering equivalent serialized input must not change the effective hash.
- Test migration from current taxonomy artifacts to graph concepts and back to the legacy cluster projection. Aliases flatten deterministically; invalid cycles fail validation; learned domain co-membership does not create semantic transfer edges; and fixed categories remain display projections.
- Test profile assertions for literal evidence, evidence-backed inference, self-report, assessment, disputed state, unknown state, duplicate evidence, stale evidence, missing evidence, and deterministic rebuilds. No assertion may cite a missing fact identifier.
- Test that title alone does not establish proficiency, autonomy, complexity, scope, influence, or evidence confidence. Unknown dimensions remain unknown.
- Test concept typing across capability, knowledge, task, method, standard, tool, artifact, work style, language, occupation, industry, credential, requirement, context, and ambiguous phrases. Strict credentials and context are never emitted as ordinary skills.
- Test typed job extraction with exact source spans, legacy list adapters, must and preferred distinctions, strict product requirements, product-family alternatives, capability requirements, credentials, experience duration, work authorization, location, schedule, and physical requirements.
- Test Match Engine v2 with verified exact, approved equivalence, broader and narrower direction, transfer, partial subskill coverage, level, context, recency, evidence, tool, credential, unknown, and absent outcomes.
- Include adversarial cases proving that same category, same learned domain, high embedding similarity, co-occurrence, and lexical resemblance do not independently count as coverage or transferability.
- Test candidate-name-only behavior for transferable capabilities. Neither match explanations nor tailoring inputs may relabel candidate evidence as the target requirement.
- Test hard gates for credentials, jurisdiction, strict tools, work authorization, and explicit non-substitution. No graph path may bypass a hard gate.
- Test bounded graph traversal for allowed edge types, direction, maximum path length, cycles, inactive edges, tenant scope, confidence threshold, and policy version.
- Test shadow mode by computing legacy and v2 results together and asserting that legacy results remain byte-for-byte compatible while v2 records divergence without altering ranking, suggestions, or tailoring.
- Test compatibility APIs with old profile matrices, jobs containing only legacy lists, match-gap clients reading only existing fields, and resume versions without revision metadata.
- Test stale-artifact handling so mismatched profile and taxonomy revisions never produce a blended response. Verify explicit rebuild, unavailable, and provider-failure paths.
- Test resume-version persistence so every new attempt retains the complete effective revision, facts revision, job-extraction revision, assertion policy, matching policy, assertion references, and match context.
- Test tenant isolation by applying conflicting aliases or transfer-edge corrections in two workspaces and proving their snapshots and results remain independent.
- Test correction replay, graph projection, profile building, match results, and API serialization for determinism and idempotence across repeated runs.
- Add frontend tests for the six UCCM layer projections, separate requirements lane, precise status labels, unknown versus absent, legacy versus v2 comparison in shadow mode, requirement source drill-down, evidence links, stale states, keyboard use, small-screen layout, reduced motion, and non-color status cues.
- Keep the current full contract regeneration gate. Add schema assertions that all new UCCM fields are additive during the compatibility window and that closed enums remain synchronized across backend and frontend.
- Build a stratified offline gold set spanning software and data, engineering and manufacturing, finance and accounting, human resources, education and research, consulting and operations, creative and media, sales and customer work, healthcare and social services, legal and policy, logistics and skilled operations, and public or nonprofit administration.
- Include entry, mid, senior individual-contributor, and management cases; cross-industry transfer cases; multilingual aliases where feasible; ambiguous descriptions; strict credentials and tools; direct, transferable, partial, stale, missing, and unknown evidence; and adversarial false-adjacency examples.
- Gate UCCM mode on the design authority's proposed thresholds unless the evaluation owner approves a documented replacement: at least 98% exact and synonym precision, at most 0.5% strict credential or tool false positives, at least 99.5% evidence-backed resume-claim precision, at least 92% transfer precision overall, at least 97% transfer precision where must-have requirements receive positive ranking credit, at most 3% false transfer on adversarial same-domain negatives, at least 0.93 concept-type macro-F1, at least 0.88 match-status macro-F1 with no critical status below 0.80, 100% correction propagation, and 100% deterministic reproduction from stored revisions.
- Run ablations for current adjacency, typed exact-only matching, broader and narrower edges, task and knowledge overlap, approved transfer edges, proficiency and context features, lexical versus embedding retrieval, rule-only versus calibrated classification, and global graph with and without tenant corrections.

## Out of Scope

- Bulk import of O*NET, ESCO, DigComp, NICE, SFIA, NACE, or another external framework in this implementation program. The graph and source-manifest interfaces must support later imports, but each source requires a separate licensed import spec and release gate.
- Copying restricted NACE or SFIA wording into the product without appropriate permission or license.
- Selecting or deploying a graph database solely because the canonical domain model is a graph.
- Autonomous promotion of tenant corrections, model-generated aliases, mappings, transfer edges, or domain placements into the global governed graph.
- Replacing candidate evidence with assessment, taxonomy, labor-market, employer, title, or relationship inference.
- Inferring protected traits, legal eligibility, credential status, work authorization, or physical capability from ordinary profile text.
- A complete learning-resource marketplace, course recommender, credential marketplace, or automated career-path planner. This spec may classify development actions but does not source or rank providers.
- Market-demand signals as canonical taxonomy truth. Demand may influence ranking and gap priority but remains a separate, faster-changing signal.
- Immediate deletion of the current cluster map, fixed categories, legacy matrix rows, exact/adjacent/gap matcher, match-gap demand graph, or existing taxonomy correction APIs.
- Rewriting historical profiles, jobs, match reports, evidence portfolios, or resume versions to pretend their revisions were known.
- Making Match Engine v2 authoritative for tailoring or job ranking before shadow evaluation and rollback gates pass.
- Unbounded graph traversal, unconstrained embedding similarity as coverage, or a single opaque fit score presented as truth.

## Further Notes

- The six UCCM layers are navigation projections with increasing contextual specificity; they are not a single-parent hierarchy.
- The eight career-core families are original product language. External frameworks are crosswalk and validation references, not the internal identity system.
- The effective-taxonomy read-contract repair is a prerequisite, not a substitute for the UCCM graph. It should be implemented and merged first so every later phase has one correctness boundary.
- The main acceptance seam is intentionally cross-path: one fixture should prove profile building, match-gap, and the legacy tailoring adapter consume the same pinned snapshot. Lower-level tests support diagnosis, but they must not become competing definitions of effective taxonomy.
- Implementation should produce a short migration note for every phase, including the compatibility projection, revision changes, feature-mode behavior, rollback procedure, and data that remains after rollback.
- Before implementation starts, the product owner should confirm that the proposed cross-path acceptance seam and the legacy/shadow/UCCM rollout modes match release expectations. No additional taxonomy intelligence should be implemented ahead of that confirmation.
