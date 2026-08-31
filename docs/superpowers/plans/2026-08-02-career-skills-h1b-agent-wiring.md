# Career Skills and H-1B Agent Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every approved local career skill executable through a purpose-specific Agno agent, add a streamed Career Lab, and enrich sponsorship-required, JD-silent jobs through the read-only H-1B MCP server.

**Architecture:** A verified registry resolves one hash-pinned `SkillRef` for each skilled run. Existing application services remain authoritative for routing, validation, persistence, fact locks, scoring, and mutations; Agno agents analyze or draft behind `AgentRunner`. A dedicated sponsorship agent alone receives one allowlisted `MCPTools` instance per enrichment batch, and Career Lab reuses the existing run/session streaming substrate.

**Tech Stack:** Python 3.13, Agno 2.8.x with the `mcp` extra, Pydantic 2, FastAPI, SQLModel/SQLite, Typer, React 19, TypeScript 6, TanStack Query, Vitest, Playwright, OpenAPI.

## Global Constraints

- Implement only the approved read-only slice in `docs/superpowers/specs/2026-08-02-career-skills-h1b-agent-wiring-design.md`.
- H-1B is the only MCP integration. Do not add ATS, Scanner, JobSpy, GitHub, JobGPT, or LinkedIn MCP code or configuration.
- A task agent receives exactly one verified local skill. Formatter agents receive no skill, and only the Sponsorship Research Agent receives MCP tools.
- H-1B runs only when `SearchConfig.sponsorship_required` is true and `JobCriteria.sponsorship_signal` is `silent`.
- Historical H-1B evidence never changes the current posting signal to `offered`, never hard-rejects a job, and never claims current employer policy.
- H-1B is disabled by default. Enabled configuration selects exactly one of local `stdio` or Streamable HTTP.
- Expose only `get_company_stats`, `search_h1b_jobs`, and `get_available_data`, prefixed as `h1b_*`.
- Preserve existing provider-key refresh, quotas, retries, usage accounting, streaming, and async cleanup through `AgentRunner`.
- Treat skills, job descriptions, profile/resume content, Career Lab messages, and MCP responses as untrusted data.
- Keep all new API fields additive, camel-cased through `CamelModel`, and use the existing structured `ApiException` error envelope.
- Validate API input, environment configuration, skill files, and MCP responses at their boundaries; internal functions consume typed values.
- Existing rows use `None` for unknown legacy skill metadata. Never backfill a claim about a skill that did not run.
- Use focused TDD for each task, regenerate OpenAPI clients after schema changes, and finish with `make verify` plus targeted browser coverage.
- Keep changes surgical. Do not refactor unrelated discovery, session, prompt, or UI code.

## Why this remains one plan

The registry, `SkillRef`, run metadata, and Agno attachment seam are shared contracts. H-1B enrichment and Career Lab are separately reviewable tasks after those contracts land, but splitting them into independent plans would duplicate or temporarily fork those interfaces.

## File Structure

### New backend modules

- `src/resume_tailor_harness/career_skills/__init__.py` — public registry and provenance exports.
- `src/resume_tailor_harness/career_skills/models.py` — closed enums, manifest models, `SkillRef`, `SkillUse`, and agent-run metadata.
- `src/resume_tailor_harness/career_skills/registry.py` — root-confined manifest verification and capability lookup.
- `src/resume_tailor_harness/career_skills/agno.py` — one-skill Agno kwargs and runner metadata attachment.
- `src/resume_tailor_harness/career_lab/models.py` — Career Lab session, turn, route, context-reference, and artifact schemas.
- `src/resume_tailor_harness/career_lab/store.py` — `SessionStore` custody and lifecycle deltas.
- `src/resume_tailor_harness/career_lab/agents.py` — router, skilled persona, and tool-free formatter Agno builders.
- `src/resume_tailor_harness/services/career_lab.py` — tenant-scoped context resolution and streamed turn orchestration.
- `src/resume_tailor_harness/h1b/models.py` — typed configuration-independent evidence and enrichment report models.
- `src/resume_tailor_harness/h1b/mcp.py` — lazy `MCPTools` construction, allowlist, result guard, and lifecycle.
- `src/resume_tailor_harness/h1b/service.py` — cache lookup, company batching, agent calls, validation, and persistence.
- `src/resume_tailor_harness/api/schemas/career_lab.py` — REST input/output schemas.
- `src/resume_tailor_harness/api/routers/career_lab.py` — Career Lab resources and run launch endpoints.

### Modified backend seams

- `.gitattributes`, `.gitignore`, `skills-lock.json` — tracked, LF-stable v2 skill manifest.
- `pyproject.toml`, `uv.lock` — install the Agno MCP extra compatible with locked Agno 2.8.x.
- `src/resume_tailor_harness/config.py` — typed career-skill and H-1B settings.
- `src/resume_tailor_harness/llm_runner.py` — attach immutable run metadata without changing run semantics.
- `src/resume_tailor_harness/services/agents.py` — registry-backed purpose-specific bundle construction and keyed reuse.
- `src/resume_tailor_harness/discovery/{extract.py,fit.py,pipeline.py}` — skilled Job Analysis agents and H-1B context between filter and score.
- `src/resume_tailor_harness/profile/project_extractor.py` — internal `project-dossier` skill.
- `src/resume_tailor_harness/tailor/agents.py`, `src/resume_tailor_harness/tailor/review_config.py`, `src/resume_tailor_harness/tailor/service.py`, `src/resume_tailor_harness/services/{tailoring.py,revision.py}` — authoring/review skill selection and provenance.
- `src/resume_tailor_harness/cover_letter/agents.py`, `src/resume_tailor_harness/cover_letter/service.py`, `src/resume_tailor_harness/services/{cover_letters.py,cover_letter_revision.py}` — cover-letter skills and provenance.
- `src/resume_tailor_harness/interview/{agent.py,store.py}`, `src/resume_tailor_harness/services/mock_interview.py` — preparation/mock skills with skill-free formatters.
- `src/resume_tailor_harness/tracking/{tables.py,migrate.py,queries.py}`, `src/resume_tailor_harness/db.py` — skill metadata and H-1B cache persistence.
- `src/resume_tailor_harness/api/{app.py,deps.py}`, `src/resume_tailor_harness/api/schemas/{jobs.py,runs.py,setup.py}`, `src/resume_tailor_harness/api/routers/{jobs.py,runs.py,setup.py}` — additive API/readiness surfaces.
- `src/resume_tailor_harness/tenancy/workspace.py`, `src/resume_tailor_harness/cli.py` — Career Lab custody and CLI.
- `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` — regenerated contracts.

### New web feature

- `web/src/features/career-lab/use-career-lab.ts` — typed queries, mutations, and run recovery.
- `web/src/features/career-lab/CareerLabPage.tsx` — responsive guided workspace.
- `web/src/features/career-lab/CareerLabPage.test.tsx`, `web/src/features/career-lab/use-career-lab.test.tsx` — UI and hook contracts.
- `web/e2e/career-lab.spec.ts` — authenticated user journey, refresh recovery, stop, archive, and keyboard coverage.

## Stable Contracts

```python
class AgentFamily(StrEnum):
    JOB_ANALYSIS = "job_analysis"
    RESUME_AUTHORING = "resume_authoring"
    RESUME_REVIEW = "resume_review"
    COVER_LETTER = "cover_letter"
    INTERVIEW = "interview"
    CAREER_LAB = "career_lab"
    INTERNAL_PROFILE = "internal_profile"
    SPONSORSHIP_RESEARCH = "sponsorship_research"


class SkillRef(BaseModel):
    name: str
    version: str
    sha256: str
    family: AgentFamily


class SkillUse(BaseModel):
    skill_ref: SkillRef
    stage: Literal["generated", "reviewed", "revised"]
    used_at: datetime
    model_id: str
    prompt_policy_version: str


class AgentRunMeta(BaseModel):
    agent_family: AgentFamily
    prompt_policy_version: str
    model_id: str
    skill_ref: SkillRef | None = None


class ResumeAuthoringSkillName(StrEnum):
    ACADEMIC_CV_BUILDER = "academic-cv-builder"
    ACADEMIC_RESEARCH_CV = "academic-research-cv"
    CREATIVE_PORTFOLIO_RESUME = "creative-portfolio-resume"
    EXECUTIVE_LEADERSHIP_RESUME = "executive-leadership-resume"
    EXECUTIVE_RESUME_WRITER = "executive-resume-writer"
    RESUME_BULLET_WRITER = "resume-bullet-writer"
    RESUME_CUSTOMIZER = "resume-customizer"
    RESUME_QUANTIFIER = "resume-quantifier"
    RESUME_SECTION_BUILDER = "resume-section-builder"
    RESUME_TAILOR = "resume-tailor"
    SOFTWARE_ENGINEER_RESUME = "software-engineer-resume"
    TECH_RESUME_OPTIMIZER = "tech-resume-optimizer"


class CoverLetterSkillName(StrEnum):
    GENERATOR = "cover-letter-generator"
    WRITER = "cover-letter-writer"


class CareerLabSkillName(StrEnum):
    APPLICATION_FORM_FILLER = "application-form-filler"
    CAREER_CHANGER_TRANSLATOR = "career-changer-translator"
    CAREER_PIVOT_PLANNER = "career-pivot-planner"
    COLD_EMAIL_WRITER = "cold-email-writer"
    COMPENSATION_NEGOTIATOR = "compensation-negotiator"
    LINKEDIN_PROFILE_BOOSTER = "linkedin-profile-booster"
    LINKEDIN_PROFILE_OPTIMIZER = "linkedin-profile-optimizer"
    OFFER_COMPARISON_ANALYZER = "offer-comparison-analyzer"
    PORTFOLIO_CASE_STUDY = "portfolio-case-study"
    PORTFOLIO_CASE_STUDY_WRITER = "portfolio-case-study-writer"
    REFERENCE_LIST_BUILDER = "reference-list-builder"
    SALARY_NEGOTIATION_PREP = "salary-negotiation-prep"
```

`SkillUseStage` is the shared alias
`Literal["generated", "reviewed", "revised"]`; persisted and API models use
the same spelling throughout.

The fixed routing map is:

| Family | Skills |
|---|---|
| Job Analysis | `job-description-analyzer`, `job-fit-analyzer` |
| Resume Authoring | `academic-cv-builder`, `academic-research-cv`, `creative-portfolio-resume`, `executive-leadership-resume`, `executive-resume-writer`, `resume-bullet-writer`, `resume-customizer`, `resume-quantifier`, `resume-section-builder`, `resume-tailor`, `software-engineer-resume`, `tech-resume-optimizer` |
| Resume Review | `ats-resume-checker`, `resume-ats-optimizer`, `resume-formatter`, `resume-version-manager` |
| Cover Letter | `cover-letter-generator`, `cover-letter-writer` |
| Interview | `interview-prep-generator`, `mock-interview-coach` |
| Career Lab | `application-form-filler`, `career-changer-translator`, `career-pivot-planner`, `cold-email-writer`, `compensation-negotiator`, `linkedin-profile-booster`, `linkedin-profile-optimizer`, `offer-comparison-analyzer`, `portfolio-case-study`, `portfolio-case-study-writer`, `reference-list-builder`, `salary-negotiation-prep` |
| Internal Profile | `project-dossier` |

---

### Task 1: Track and verify the complete career-skill manifest

**Files:**
- Modify: `.gitattributes`
- Modify: `.gitignore`
- Modify and force-add: `skills-lock.json`
- Modify: `Dockerfile`
- Create: `src/resume_tailor_harness/career_skills/__init__.py`
- Create: `src/resume_tailor_harness/career_skills/models.py`
- Create: `src/resume_tailor_harness/career_skills/registry.py`
- Modify: `src/resume_tailor_harness/config.py`
- Modify: `src/resume_tailor_harness/api/schemas/setup.py`
- Modify: `src/resume_tailor_harness/api/routers/setup.py`
- Modify generated: `contracts/openapi.json`
- Modify generated: `contracts/ts/api.ts`
- Modify generated: `web/src/lib/api/schema.ts`
- Test: `tests/test_career_skill_registry.py`
- Test: `tests/test_config.py`
- Test: `tests/api/test_setup_status.py`

**Interfaces:**
- Produces: `CareerSkillRegistry.from_settings(settings: Settings) -> CareerSkillRegistry`
- Produces: `CareerSkillRegistry.require(name: str, *, family: AgentFamily, use: str) -> VerifiedSkill`
- Produces: `CareerSkillRegistry.public_capabilities() -> list[SkillCapability]`
- Produces: `VerifiedSkill(ref: SkillRef, directory: Path, uses: frozenset[str])`
- Produces: `SkillUnavailable(code: str, skill_name: str, reason: str)`
- Produces: `registry_for_paths(root: Path | str, manifest: Path | str) -> CareerSkillRegistry`, cached by resolved string paths

- [ ] **Step 1: Write failing manifest and registry tests**

```python
def test_shipped_manifest_covers_every_skill_once():
    registry = CareerSkillRegistry.from_paths(Path("skills"), Path("skills-lock.json"))
    assert len(registry.all()) == 35
    assert len(registry.public_capabilities()) == 34
    assert registry.require(
        "project-dossier", family=AgentFamily.INTERNAL_PROFILE, use="profile_project"
    ).ref.name == "project-dossier"


@pytest.mark.parametrize("failure", ["traversal", "symlink_escape", "hash", "utf8", "oversize", "duplicate"])
def test_invalid_manifest_entry_fails_only_its_capability(tmp_path, failure):
    root, manifest = build_invalid_registry_fixture(tmp_path, failure)
    registry = CareerSkillRegistry.from_paths(root, manifest)
    with pytest.raises(SkillUnavailable):
        registry.require("resume-customizer", family=AgentFamily.RESUME_AUTHORING, use="tailor")
    assert registry.require(
        "job-fit-analyzer", family=AgentFamily.JOB_ANALYSIS, use="fit"
    ).ref.name == "job-fit-analyzer"
```

- [ ] **Step 2: Run the tests and verify the trust boundary is absent**

Run: `uv run pytest tests/test_career_skill_registry.py tests/test_config.py tests/api/test_setup_status.py -v`

Expected: FAIL because the registry models do not exist and setup readiness has no skill capability state.

- [ ] **Step 3: Define the v2 manifest and registry models**

```python
class SkillManifestEntry(BaseModel):
    source: str
    source_type: Literal["github", "local"] = Field(alias="sourceType")
    reviewed_ref: str = Field(alias="reviewedRef")
    skill_path: str = Field(alias="skillPath")
    computed_hash: str = Field(alias="computedHash", pattern=r"^[0-9a-f]{64}$")
    local_version: str = Field(alias="localVersion")
    family: AgentFamily
    uses: frozenset[str]
    visibility: Literal["public", "internal"]


class SkillManifest(BaseModel):
    version: Literal[2]
    hash_mode: Literal["utf8-lf-v1"] = Field(alias="hashMode")
    skills: dict[str, SkillManifestEntry]


class SkillCapability(BaseModel):
    name: str
    description: str
    family: AgentFamily
    uses: list[str]
    is_available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class VerifiedSkill:
    ref: SkillRef
    directory: Path
    uses: frozenset[str]
```

Registry construction must resolve both roots, reject absolute or escaping manifest paths, require a regular non-symlink `SKILL.md`, read at most 256 KiB as UTF-8, canonicalize CRLF/CR to LF under the explicit `utf8-lf-v1` hash mode, hash those approved canonical bytes, validate frontmatter name against the manifest key, and retain typed failures by skill name. `require()` checks name, family, use, and verified availability without guessing a substitute. Tests prove LF and CRLF checkouts hash identically while every other content change fails.

- [ ] **Step 4: Make the shipped manifest deterministic and complete**

Add these attributes:

```gitattributes
skills/**/SKILL.md text eol=lf
skills-lock.json text eol=lf
```

Remove `skills-lock.json` from `.gitignore`. Review all 35 committed `SKILL.md` files, replace the stale 22 hashes, add the 13 absent entries, set `localVersion` to `2026-08-02`, use the local import commit `fb34e2f26f597bcd90306d9f949ac25a96f6469d` as `reviewedRef` for the 34 unchanged imports and `e85fdb29570bb23dcd89435a869e91630aa0463a` for `project-dossier`, retain existing upstream `source` values where recorded, and use `https://github.com/awbjcj/resume-tailor-harness` with `sourceType: "local"` where upstream provenance is not recorded. Encode the exact family/use map from this plan and mark only `project-dossier` internal.

The ignored local lock recorded `Paramchoudhary/ResumeSkills` as the upstream
source for exactly these 22 names: `academic-cv-builder`,
`application-form-filler`, `career-changer-translator`, `cold-email-writer`,
`cover-letter-generator`, `creative-portfolio-resume`,
`executive-resume-writer`, `interview-prep-generator`,
`job-description-analyzer`, `linkedin-profile-optimizer`,
`offer-comparison-analyzer`, `portfolio-case-study-writer`,
`reference-list-builder`, `resume-ats-optimizer`, `resume-bullet-writer`,
`resume-formatter`, `resume-quantifier`, `resume-section-builder`,
`resume-tailor`, `resume-version-manager`, `salary-negotiation-prep`, and
`tech-resume-optimizer`. The remaining 13 entries use the local repository
source stated above rather than guessing an upstream origin.

Add `COPY skills ./skills` and `COPY skills-lock.json ./skills-lock.json` to
the runtime stage in `Dockerfile` so the default paths exist in deployed
images. Add a registry test that asserts both copy directives remain present.

- [ ] **Step 5: Add safe settings and additive readiness output**

```python
career_skill_root: Path = Path("skills")
career_skill_manifest: Path = Path("skills-lock.json")
```

Extend setup output with optional `capabilities.careerSkills` counts (`available`, `unavailable`) and optional `capabilities.h1b` state without changing the existing `complete` calculation. A broken manifest must not make `/api/setup/status` return 500.

- [ ] **Step 6: Regenerate the additive API contract**

Run:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
```

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_career_skill_registry.py tests/test_config.py tests/api/test_setup_status.py tests/api/test_openapi_contract.py -v`

Expected: PASS, including exactly 35 verified entries and the isolated capability-failure cases.

```bash
git add .gitattributes .gitignore skills-lock.json Dockerfile src/resume_tailor_harness/career_skills src/resume_tailor_harness/config.py src/resume_tailor_harness/api/schemas/setup.py src/resume_tailor_harness/api/routers/setup.py tests/test_career_skill_registry.py tests/test_config.py tests/api/test_setup_status.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: verify approved career skills"
```

### Task 2: Persist typed skill and sponsorship provenance

**Files:**
- Modify: `src/resume_tailor_harness/career_skills/models.py`
- Modify: `src/resume_tailor_harness/tracking/tables.py`
- Modify: `src/resume_tailor_harness/tracking/migrate.py`
- Modify: `src/resume_tailor_harness/db.py`
- Test: `tests/test_tracking_migrate.py`
- Test: `tests/test_job_detail_row.py`
- Test: `tests/test_cover_letter_table.py`

**Interfaces:**
- Produces: `JobAnalysisMeta(criteria: AgentRunMeta | None, fit: AgentRunMeta | None, h1b_evidence_id: int | None, h1b_evidence_snapshot: dict[str, object] | None)`
- Produces: nullable `Job.analysis_meta_json`, `ResumeVersion.skill_uses_json`, and `CoverLetter.skill_uses_json`
- Produces: `H1BCompanyEvidence` table keyed by unique normalized company
- Produces: `read_skill_uses(raw: object) -> list[SkillUse]`

- [ ] **Step 1: Write failing additive-migration tests**

```python
def test_agent_metadata_migration_is_additive_and_idempotent(tmp_path):
    engine = legacy_engine(tmp_path)
    init_db(engine)
    init_db(engine)
    assert {"analysis_meta_json"} <= table_columns(engine, "jobs")
    assert {"skill_uses_json"} <= table_columns(engine, "resume_versions")
    assert {"skill_uses_json"} <= table_columns(engine, "cover_letters")
    assert table_exists(engine, "h1b_company_evidence")
    with Session(engine) as session:
        assert session.get(Job, 1).analysis_meta_json is None
```

- [ ] **Step 2: Run the migration tests to verify failure**

Run: `uv run pytest tests/test_tracking_migrate.py tests/test_job_detail_row.py tests/test_cover_letter_table.py -v`

Expected: FAIL on missing columns/table and missing typed provenance parsers.

- [ ] **Step 3: Add the nullable columns and H-1B cache table**

```python
class H1BCompanyEvidence(SQLModel, table=True):
    __tablename__ = "h1b_company_evidence"
    __table_args__ = (UniqueConstraint("normalized_company"),)

    id: int | None = Field(default=None, primary_key=True)
    normalized_company: str = Field(index=True)
    display_company: str | None = None
    status: str = Field(index=True)
    evidence_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    source_url: str | None = None
    data_version: str | None = None
    retrieved_at: datetime
    expires_at: datetime = Field(index=True)
    schema_version: int = 1
```

Add idempotent `ensure_agent_metadata_columns(engine)` and call it from `init_db()`. New databases obtain the table from SQLModel metadata; legacy databases obtain only the three nullable columns through `ALTER TABLE`. Do not backfill legacy rows.

`JobAnalysisMeta.h1b_evidence_snapshot` stores the validated projected evidence
used for that fit call. The row id points to the refreshable company cache;
the snapshot prevents a later cache refresh from rewriting the audit meaning
of an older fit analysis.

- [ ] **Step 4: Add strict typed JSON readers**

`read_skill_uses()` and `read_job_analysis_meta()` return empty/`None` only for legacy `None`; malformed non-null metadata raises a typed validation error so corrupt audit data is not silently rewritten.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/test_tracking_migrate.py tests/test_job_detail_row.py tests/test_cover_letter_table.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/career_skills/models.py src/resume_tailor_harness/tracking/tables.py src/resume_tailor_harness/tracking/migrate.py src/resume_tailor_harness/db.py tests/test_tracking_migrate.py tests/test_job_detail_row.py tests/test_cover_letter_table.py
git commit -m "feat: persist agent skill provenance"
```

### Task 3: Add the one-skill Agno runner seam

**Files:**
- Create: `src/resume_tailor_harness/career_skills/agno.py`
- Modify: `src/resume_tailor_harness/llm_runner.py`
- Modify: `src/resume_tailor_harness/services/agents.py`
- Test: `tests/test_agent_skills.py`
- Test: `tests/test_llm_runner.py`

**Interfaces:**
- Produces: `skill_kwargs(skill: VerifiedSkill) -> dict[str, Skills]`
- Produces: `AgentRunner(agent: Any, *, run_meta: AgentRunMeta | None = None)` and read-only `run_meta`
- Produces: `SkilledAgentPool.get(key: AgentCacheKey, builder: Callable[[], Runner]) -> Runner`
- Produces: `run_meta_payload(*runners: Runner) -> list[dict[str, object]]` for redacted background-run metadata
- Consumes: `CareerSkillRegistry.require(name: str, *, family: AgentFamily, use: str) -> VerifiedSkill`

- [ ] **Step 1: Write failing structural tests**

```python
def test_skill_kwargs_loads_only_the_selected_directory(verified_skill):
    kwargs = skill_kwargs(verified_skill)
    loaders = kwargs["skills"].loaders
    assert len(loaders) == 1
    assert loaders[0].path == verified_skill.directory.resolve()


def test_skilled_pool_reuses_stable_configuration(pool):
    key = AgentCacheKey(
        family=AgentFamily.JOB_ANALYSIS,
        skill_sha256="a" * 64,
        model_id="test-model",
        output_schema="JobCriteriaExtract",
        prompt_policy_version="job-extract-v1",
    )
    first = pool.get(key, fake_builder)
    second = pool.get(key, fake_builder)
    assert first is second
    assert fake_builder.call_count == 1
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run pytest tests/test_agent_skills.py tests/test_llm_runner.py -v`

Expected: FAIL because agents cannot yet attach one `LocalSkills` loader or immutable run metadata.

- [ ] **Step 3: Implement the minimal Agno attachment seam**

```python
def skill_kwargs(skill: VerifiedSkill) -> dict[str, Skills]:
    return {
        "skills": Skills(loaders=[LocalSkills(str(skill.directory))]),
    }


@dataclass(frozen=True)
class AgentCacheKey:
    family: AgentFamily
    skill_sha256: str | None
    model_id: str
    output_schema: str | None
    prompt_policy_version: str
```

`AgentRunner.run_meta` is metadata only; do not change retry, quota, usage, stream mapping, or cleanup behavior. `SkilledAgentPool` uses a lock-protected dictionary, creates outside item loops, and keys on every behavior-affecting field. Do not cache H-1B tool-bearing agents beyond their owning async batch.

`run_meta_payload()` includes family, prompt-policy version, model id, and the
selected skill name/version/hash; it excludes prompts, skill bodies, user
content, credentials, and tool results.

- [ ] **Step 4: Assert tool boundaries**

Inspect the built Agno object in tests: a skilled task agent has one `LocalSkills` loader and no `MCPTools`; a formatter has neither; only a sponsorship builder may receive `MCPTools`.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/test_agent_skills.py tests/test_llm_runner.py tests/test_agent_prompt_contracts.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/career_skills/agno.py src/resume_tailor_harness/llm_runner.py src/resume_tailor_harness/services/agents.py tests/test_agent_skills.py tests/test_llm_runner.py tests/test_agent_prompt_contracts.py
git commit -m "feat: attach one verified skill to Agno agents"
```

### Task 4: Wire Job Analysis and internal profile agents

**Files:**
- Modify: `src/resume_tailor_harness/discovery/extract.py`
- Modify: `src/resume_tailor_harness/discovery/fit.py`
- Modify: `src/resume_tailor_harness/discovery/pipeline.py`
- Modify: `src/resume_tailor_harness/profile/project_extractor.py`
- Modify: `src/resume_tailor_harness/services/agents.py`
- Modify: `src/resume_tailor_harness/api/routers/runs.py`
- Test: `tests/test_discovery_extract.py`
- Test: `tests/test_discovery_fit.py`
- Test: `tests/test_discovery_pipeline.py`
- Test: `tests/test_profile_project_extractor.py`

**Interfaces:**
- `build_extract_agent(model_id: str | None = None, *, skill: VerifiedSkill) -> AgentRunner` uses `job-description-analyzer`.
- `build_fit_agent(model_id: str | None = None, *, skill: VerifiedSkill) -> AgentRunner` uses `job-fit-analyzer`.
- `build_project_extractor_agent(model_id: str | None = None, *, skill: VerifiedSkill) -> AgentRunner` uses internal `project-dossier`.
- Successful extraction and fit persist their own `AgentRunMeta` into `Job.analysis_meta_json`.

- [ ] **Step 1: Write failing routing and persistence tests**

```python
def test_discovery_bundle_uses_fixed_job_analysis_skills(registry):
    bundle = build_discovery_bundle(registry=registry)
    assert bundle.extract.run_meta.skill_ref.name == "job-description-analyzer"
    assert bundle.fit.run_meta.skill_ref.name == "job-fit-analyzer"


def test_successful_stages_record_the_exact_agent_metadata(session, skilled_bundle):
    discover(session, config, facts, skilled_bundle.extract, skilled_bundle.fit)
    meta = JobAnalysisMeta.model_validate(session.get(Job, 1).analysis_meta_json)
    assert meta.criteria.skill_ref.name == "job-description-analyzer"
    assert meta.fit.skill_ref.name == "job-fit-analyzer"
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run pytest tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_profile_project_extractor.py -v`

Expected: FAIL because current builders have no skill argument and jobs have no run metadata writes.

- [ ] **Step 3: Add exact skill parameters to the existing Agno builders**

Keep each builder's model selection, instructions, output schema, JSON-mode decision, and retry settings. Add `**skill_kwargs(skill)` and construct `AgentRunMeta` with explicit policy versions `job-extract-v1`, `job-fit-v1`, and `project-dossier-v1`.

- [ ] **Step 4: Persist metadata only after validated output**

Extraction records metadata after `JobCriteriaExtract.to_criteria()` succeeds; fit records after `FitScore` validates. A failed/retried stage leaves its former metadata unchanged until a successful replacement. `project-dossier` remains absent from Career Lab capabilities.

Discovery background runs add `run_meta_payload(bundle.extract, bundle.fit)`
under `meta.agents` before launch so support records identify the exact fixed
procedures without storing input content.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_profile_project_extractor.py tests/test_agent_prompt_contracts.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/discovery/extract.py src/resume_tailor_harness/discovery/fit.py src/resume_tailor_harness/discovery/pipeline.py src/resume_tailor_harness/profile/project_extractor.py src/resume_tailor_harness/services/agents.py src/resume_tailor_harness/api/routers/runs.py tests/test_discovery_extract.py tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_profile_project_extractor.py
git commit -m "feat: skill job analysis agents"
```

### Task 5: Wire resume and cover-letter skills with additive selection

**Files:**
- Modify: `src/resume_tailor_harness/tailor/agents.py`
- Modify: `src/resume_tailor_harness/tailor/review_config.py`
- Modify: `src/resume_tailor_harness/tailor/service.py`
- Modify: `src/resume_tailor_harness/services/agents.py`
- Modify: `src/resume_tailor_harness/services/tailoring.py`
- Modify: `src/resume_tailor_harness/services/revision.py`
- Modify: `src/resume_tailor_harness/cover_letter/agents.py`
- Modify: `src/resume_tailor_harness/cover_letter/service.py`
- Modify: `src/resume_tailor_harness/services/cover_letters.py`
- Modify: `src/resume_tailor_harness/services/cover_letter_revision.py`
- Modify: `src/resume_tailor_harness/api/schemas/runs.py`
- Modify: `src/resume_tailor_harness/api/routers/runs.py`
- Modify: `src/resume_tailor_harness/cli.py`
- Modify generated: `contracts/openapi.json`
- Modify generated: `contracts/ts/api.ts`
- Modify generated: `web/src/lib/api/schema.ts`
- Test: `tests/test_tailor_agents.py`
- Test: `tests/test_services_tailoring.py`
- Test: `tests/test_services_cover_letter_revision.py`
- Test: `tests/api/test_runs_launch.py`
- Test: `tests/test_cli_tailor.py`
- Test: `tests/test_cli_cover_letter.py`

**Interfaces:**
- Adds optional `authoringSkill` to `TailorParams`; default is `resume-customizer`.
- Adds optional `skill` to `CoverLetterParams`; default is `cover-letter-generator`.
- Adds `--skill` to `resume-tailor-harness tailor` and `resume-tailor-harness cover-letter`, validated against the relevant closed enum.
- Writer/reviser/revision functions receive a `VerifiedSkill` selected before entering the workflow.
- Each persisted resume/cover version appends a validated `SkillUse` only after successful generation/review/revision.

- [ ] **Step 1: Write failing selector and provenance tests**

```python
def test_tailor_rejects_a_review_skill_as_authoring_input(client):
    response = client.post("/api/tailor", json={"jobIds": [1], "authoringSkill": "ats-resume-checker"})
    assert response.status_code == 422


def test_tailor_default_and_revision_skill_uses(session, registry):
    outcome = tailor(session, job_ids=[1], registry=registry)
    uses = read_skill_uses(outcome.versions[1][-1].skill_uses_json)
    assert uses[0].skill_ref.name == "resume-customizer"
    assert uses[0].stage == "generated"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_tailor_agents.py tests/test_services_tailoring.py tests/test_services_cover_letter_revision.py tests/api/test_runs_launch.py tests/test_cli_tailor.py tests/test_cli_cover_letter.py -v`

Expected: FAIL because the request/CLI selectors and skill provenance do not exist.

- [ ] **Step 3: Implement deterministic resume routing**

The authoring selector accepts exactly the 12 Resume Authoring names. Default tailoring uses `resume-customizer`; a selected variant replaces it for writer and reviser steps. Reviewer routing is fixed by reviewer role: `ats-keyword` → `ats-resume-checker`, `recruiter` → `resume-ats-optimizer`, `concision` → `resume-formatter`; reviewers without a mapped procedure remain skill-free Agno agents. Manual version revision uses `resume-version-manager`. Never load two procedures into one reviewer or writer.

- [ ] **Step 4: Implement deterministic cover-letter routing**

Draft defaults to `cover-letter-generator`; explicit selection may choose either Cover Letter skill. Reviser and manual revision use `cover-letter-writer` unless the request explicitly selects that same family skill. Keep `CoverLetterContent` structured output and the existing fact-lock unchanged.

- [ ] **Step 5: Persist stage-specific uses without changing rendered content**

```python
def append_skill_use(raw: object, runner: Runner, stage: SkillUseStage) -> list[dict]:
    uses = read_skill_uses(raw)
    meta = require_run_meta(runner)
    if meta.skill_ref is not None:
        uses.append(SkillUse(
            skill_ref=meta.skill_ref,
            stage=stage,
            used_at=utcnow(),
            model_id=meta.model_id,
            prompt_policy_version=meta.prompt_policy_version,
        ))
    return [use.model_dump(mode="json") for use in uses]
```

Call this at the same transaction boundary that creates each `ResumeVersion` or `CoverLetter`; do not modify source facts, resume JSON, cover-letter JSON, or PDFs.

Tailor, revision, and cover-letter launches write `run_meta_payload()` under
`meta.agents`; selecting a skill changes only the selected family runner and
the metadata, not the endpoint shape or existing run lifecycle.

- [ ] **Step 6: Regenerate the API clients**

Run:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
```

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_tailor_agents.py tests/test_tailor_service.py tests/test_services_tailoring.py tests/test_cover_letter_service.py tests/test_services_cover_letter_revision.py tests/api/test_runs_launch.py tests/api/test_openapi_contract.py tests/test_cli_tailor.py tests/test_cli_cover_letter.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/tailor src/resume_tailor_harness/cover_letter src/resume_tailor_harness/services/agents.py src/resume_tailor_harness/services/tailoring.py src/resume_tailor_harness/services/revision.py src/resume_tailor_harness/services/cover_letters.py src/resume_tailor_harness/services/cover_letter_revision.py src/resume_tailor_harness/api/schemas/runs.py src/resume_tailor_harness/api/routers/runs.py src/resume_tailor_harness/cli.py tests/test_tailor_agents.py tests/test_tailor_service.py tests/test_services_tailoring.py tests/test_cover_letter_service.py tests/test_services_cover_letter_revision.py tests/api/test_runs_launch.py tests/test_cli_tailor.py tests/test_cli_cover_letter.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: skill resume and cover letter workflows"
```

### Task 6: Wire interview preparation and mock-coaching agents

**Files:**
- Modify: `src/resume_tailor_harness/interview/agent.py`
- Modify: `src/resume_tailor_harness/interview/store.py`
- Modify: `src/resume_tailor_harness/services/mock_interview.py`
- Test: `tests/test_interview_agent.py`
- Test: `tests/test_interview_store.py`
- Test: `tests/test_mock_interview_service.py`
- Test: `tests/api/test_interview_router.py`

**Interfaces:**
- Opening plan/persona uses `interview-prep-generator`.
- Answer-turn persona and debrief coach use `mock-interview-coach`.
- `build_interview_formatter_agent(schema)` remains skill-free and tool-free.
- Interview session JSON stores validated `skill_uses` with opening/turn/debrief stages.
- Interview session `skill_uses` include model id and prompt-policy version; interview run metadata contains the same redacted agent identities.

- [ ] **Step 1: Write failing interview boundary tests**

```python
def test_interview_agents_separate_procedure_from_formatter(registry):
    prep = build_interviewer_agent(style, skill=registry.require(
        "interview-prep-generator", family=AgentFamily.INTERVIEW, use="interview_prep"
    ))
    formatter = build_interview_formatter_agent(OpeningInterview)
    assert prep.run_meta.skill_ref.name == "interview-prep-generator"
    assert formatter.run_meta.skill_ref is None
    assert getattr(formatter._agent, "skills", None) is None
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_interview_agent.py tests/test_interview_store.py tests/test_mock_interview_service.py tests/api/test_interview_router.py -v`

Expected: FAIL on missing skill arguments and session provenance.

- [ ] **Step 3: Select and persist exactly one skill per persona call**

Resolve the opening, mock-turn, and debrief skills in service code before builder invocation. Append a `SkillUse` only after the formatter/normalizer accepts the output. A degraded prose turn may retain the persona skill because that persona output is visible, but it records the existing degraded notice and never invents formatter metadata.

- [ ] **Step 4: Prove stop/failure leaves durable session state unchanged**

Extend service tests to snapshot session bytes before a rejected formatter/cancelled run and compare them afterward. Preserve the existing one-active-session, archive, delete, and refresh-recovery contracts.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/test_interview_agent.py tests/test_interview_store.py tests/test_mock_interview_service.py tests/api/test_interview_router.py tests/test_session_turns.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/interview src/resume_tailor_harness/services/mock_interview.py tests/test_interview_agent.py tests/test_interview_store.py tests/test_mock_interview_service.py tests/api/test_interview_router.py
git commit -m "feat: skill interview agents"
```

### Task 7: Add the isolated H-1B MCP adapter and cache service

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/resume_tailor_harness/config.py`
- Modify: `src/resume_tailor_harness/tenancy/workspace.py`
- Create: `src/resume_tailor_harness/h1b/__init__.py`
- Create: `src/resume_tailor_harness/h1b/models.py`
- Create: `src/resume_tailor_harness/h1b/mcp.py`
- Create: `src/resume_tailor_harness/h1b/service.py`
- Create: `tests/fixtures/h1b/company-stats.json`
- Create: `tests/fixtures/h1b/no-match.json`
- Create: `tests/fixtures/h1b/malformed.json`
- Create: `tests/test_h1b_config.py`
- Create: `tests/test_h1b_mcp.py`
- Create: `tests/test_h1b_service.py`
- Modify: `tests/tenancy/test_workspace.py`

**Interfaces:**
- Produces: `H1BSponsorshipEvidence` exactly as specified in the approved design.
- Produces: `H1BEnrichmentReport(by_company: dict[str, H1BSponsorshipEvidence], cache_hits: int, researched: int, unavailable: int)`.
- Produces: `async enrich_companies(engine: Engine, companies: Sequence[str], *, settings: Settings, agent_factory: SponsorshipAgentFactory) -> H1BEnrichmentReport`.
- Produces: `h1b_tools(settings: Settings)` async context manager.

`SponsorshipAgentFactory` is a protocol with
`build(tools: MCPTools) -> AgentRunner`; production construction returns one
structured Agno agent for the batch, while tests inject a fixture-backed
runner.

```python
class H1BSponsorshipEvidence(BaseModel):
    status: Literal["matched", "no_match", "unavailable"]
    normalized_company: str
    display_company: str | None
    fiscal_periods: list[str]
    filing_count: int | None
    certified_count: int | None
    wage_summary: dict[str, float] | None
    source_url: str | None
    data_version: str | None
    retrieved_at: datetime
    expires_at: datetime
    confidence: float = Field(ge=0, le=1)
    caveat: str


class H1BEnrichmentReport(BaseModel):
    by_company: dict[str, H1BSponsorshipEvidence]
    cache_hits: int = 0
    researched: int = 0
    unavailable: int = 0
```

Validators require non-negative counts, timezone-aware timestamps with
`expires_at > retrieved_at`, an HTTP(S) `source_url` without credentials when
present, and the exact historical-only caveat constant owned by application
code. The agent cannot choose or omit that caveat.

- [ ] **Step 1: Write failing configuration and allowlist tests**

```python
@pytest.mark.parametrize(
    "env",
    [
        {"H1B_MCP_ENABLED": "true", "H1B_MCP_TRANSPORT": "stdio"},
        {"H1B_MCP_ENABLED": "true", "H1B_MCP_TRANSPORT": "streamable-http"},
        {"H1B_MCP_ENABLED": "true", "H1B_MCP_TRANSPORT": "stdio", "H1B_MCP_COMMAND": "server", "H1B_MCP_URL": "https://example.com/mcp"},
    ],
)
def test_enabled_h1b_requires_exactly_one_transport_target(monkeypatch, env):
    apply_env(monkeypatch, env)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


async def test_toolkit_exposes_only_prefixed_read_tools(valid_settings, fake_mcp):
    async with h1b_tools(valid_settings, mcp_type=fake_mcp) as tools:
        assert tools.include_tools == ["get_company_stats", "search_h1b_jobs", "get_available_data"]
        assert tools.tool_name_prefix == "h1b"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_h1b_config.py tests/test_h1b_mcp.py tests/test_h1b_service.py -v`

Expected: FAIL because the dependency, settings, models, and adapter do not exist.

- [ ] **Step 3: Install the supported Agno MCP extra and typed settings**

Run: `uv add "agno[mcp]>=2.8.6,<2.9"`

Add fields with the approved defaults and bounds: `h1b_mcp_enabled=False`, transport `stdio`, command/URL empty, timeout 30 seconds, maximum result 200,000 characters, and cache TTL 30 days. An enabled HTTP URL must be absolute `http`/`https`, contain no credentials, and have a host. Disabled configuration ignores command/URL and imports no MCP module.

Add the H-1B command and URL fields to `tenancy.workspace._PLATFORM_FIELDS`
and test that `secrets.env` cannot override them. MCP process configuration is
operator-owned, not tenant-controlled.

- [ ] **Step 4: Implement one owned MCP lifecycle**

```python
H1B_INCLUDE_TOOLS = ["get_company_stats", "search_h1b_jobs", "get_available_data"]


def build_h1b_tools(settings: Settings) -> MCPTools:
    common = dict(
        include_tools=H1B_INCLUDE_TOOLS,
        tool_name_prefix="h1b",
        timeout_seconds=settings.h1b_mcp_timeout_seconds,
        tool_hooks=[bounded_h1b_result(settings.h1b_mcp_max_result_chars)],
    )
    if settings.h1b_mcp_transport == "stdio":
        return MCPTools(command=settings.h1b_mcp_command, transport="stdio", **common)
    return MCPTools(url=settings.h1b_mcp_url, transport="streamable-http", **common)
```

The result hook calls the underlying function, serializes the returned `ToolResult`/JSON for a size check, and raises `H1BResultTooLarge` before the payload reaches the model. Enter the value returned by `build_h1b_tools(settings)` as an async context manager so connect and close occur on the same event loop. Never construct `MultiMCPTools`.

- [ ] **Step 5: Build one structured Sponsorship Research Agent per batch**

Use an Agno `Agent` with `output_schema=H1BSponsorshipEvidence`, the batch-owned toolkit, no local skill, historical-only instructions, and `AgentRunner`. Normalize companies deterministically before caching, process unique companies with `Semaphore(min(settings.llm_concurrency, 4))`, and persist `matched`, `no_match`, and `unavailable` distinctly. Validate every agent output before upsert; raw MCP content is never persisted or forwarded.

- [ ] **Step 6: Test partial startup, timeout, malformed, oversized, and cache paths**

Assert the close callback runs once after every partial startup/call failure, fresh cache avoids tool calls, expired cache refreshes, duplicate company spellings call once, and malformed/oversized output becomes `unavailable` rather than `no_match`.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_h1b_config.py tests/test_h1b_mcp.py tests/test_h1b_service.py tests/tenancy/test_workspace.py -v`

Expected: PASS.

```bash
git add pyproject.toml uv.lock src/resume_tailor_harness/config.py src/resume_tailor_harness/tenancy/workspace.py src/resume_tailor_harness/h1b tests/fixtures/h1b tests/test_h1b_config.py tests/test_h1b_mcp.py tests/test_h1b_service.py tests/tenancy/test_workspace.py
git commit -m "feat: add read-only H1B sponsorship research"
```

### Task 8: Insert historical H-1B evidence between filter and fit

**Files:**
- Modify: `src/resume_tailor_harness/discovery/fit.py`
- Modify: `src/resume_tailor_harness/discovery/pipeline.py`
- Modify: `src/resume_tailor_harness/services/discovery.py`
- Modify: `src/resume_tailor_harness/tracking/queries.py`
- Modify: `src/resume_tailor_harness/api/schemas/jobs.py`
- Modify: `src/resume_tailor_harness/api/routers/jobs.py`
- Modify: `src/resume_tailor_harness/api/routers/setup.py`
- Modify generated: `contracts/openapi.json`
- Modify generated: `contracts/ts/api.ts`
- Modify generated: `web/src/lib/api/schema.ts`
- Test: `tests/test_discovery_fit.py`
- Test: `tests/test_discovery_pipeline.py`
- Test: `tests/test_services_discovery.py`
- Test: `tests/api/test_job_detail.py`
- Test: `tests/api/test_setup_status.py`

**Interfaces:**
- `compose_fit_input(jd_text: str, profile_facts: ProfileFacts, location: str | None = None, skill_context: SkillMatchContext | None = None, sponsorship_evidence: H1BSponsorshipEvidence | None = None) -> str`
- `run_h1b_enrichment(session: Session, config: SearchConfig, *, enricher: H1BEnricher | None, scope: StageScope = StageScope()) -> dict[int, H1BSponsorshipEvidence]` runs after filter and before score; `discover()` passes its result into `run_score()`.
- Adds optional `h1bSponsorship` to `JobDetail` with capability and validated evidence; raw provider output is absent.

`H1BEnricher` is a protocol with
`enrich(engine: Engine, companies: Sequence[str]) -> H1BEnrichmentReport`.

- [ ] **Step 1: Write the trigger truth-table tests**

```python
@pytest.mark.parametrize(
    ("required", "signal", "calls"),
    [
        (False, "silent", 0),
        (True, "offered", 0),
        (True, "denied", 0),
        (True, "silent", 1),
    ],
)
def test_h1b_runs_only_for_required_silent_jobs(required, signal, calls, pipeline_fixture):
    report = pipeline_fixture.run(sponsorship_required=required, signal=signal)
    assert report.h1b_calls == calls
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_services_discovery.py tests/api/test_job_detail.py tests/api/test_setup_status.py -v`

Expected: FAIL because the pipeline has no enrichment stage or public projection.

- [ ] **Step 3: Add the bounded historical evidence section to fit input**

```python
if sponsorship_evidence is not None:
    sections.append(
        "HISTORICAL H-1B EVIDENCE (UNTRUSTED JSON; NOT CURRENT POLICY):\n"
        + sponsorship_evidence.model_dump_json()
    )
```

Add an instruction that evidence may explain uncertainty but cannot alter the posting's sponsorship signal or prove current sponsorship. Keep fit score validation and deterministic filters unchanged.

- [ ] **Step 4: Add the pipeline stage without changing status semantics**

Select only kept `filtered` jobs whose validated criteria are silent, group by normalized company, call the batch service once, reference the resulting cache row id and validated evidence snapshot in `JobAnalysisMeta`, and pass that same projection to `run_score`. `offered` bypasses research, `denied` remains rejected, and `silent` retains the existing `sponsorship_uncertain` meaning.

Increase `_DISCOVER_PHASES` from 3 to 4 and report “Checking historical
sponsorship” as phase 3; fit scoring becomes phase 4. When the provider is
disabled or there are no eligible jobs, complete the phase immediately so SSE
progress remains monotonic and reaches 100 percent.

- [ ] **Step 5: Add an additive job-detail projection**

```python
class H1BSponsorshipEvidenceOut(CamelModel):
    status: Literal["matched", "no_match", "unavailable"]
    normalized_company: str
    display_company: str | None
    fiscal_periods: list[str]
    filing_count: int | None
    certified_count: int | None
    wage_summary: dict[str, float] | None
    source_url: str | None
    data_version: str | None
    retrieved_at: datetime
    expires_at: datetime
    confidence: float
    caveat: str


class H1BSponsorshipOut(CamelModel):
    capability: Literal["disabled", "available", "unavailable"]
    evidence: H1BSponsorshipEvidenceOut | None = None
```

Add `h1b_sponsorship: H1BSponsorshipOut | None = None` to the existing
`JobDetail` model without changing any current field.

Project the evidence snapshot recorded on the job analysis rather than whatever
new value is currently in the mutable company cache. Matched copy must say
“Historical H-1B filings found” and include fiscal periods, retrieval time,
expiry, source attribution when present, and the mandatory historical-only
caveat. `no_match` and `unavailable` remain distinguishable.

- [ ] **Step 6: Regenerate the API clients**

Run:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
```

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_discovery_filter.py tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_services_discovery.py tests/api/test_job_detail.py tests/api/test_setup_status.py tests/api/test_openapi_contract.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/discovery/fit.py src/resume_tailor_harness/discovery/pipeline.py src/resume_tailor_harness/services/discovery.py src/resume_tailor_harness/tracking/queries.py src/resume_tailor_harness/api/schemas/jobs.py src/resume_tailor_harness/api/routers/jobs.py src/resume_tailor_harness/api/routers/setup.py tests/test_discovery_fit.py tests/test_discovery_pipeline.py tests/test_services_discovery.py tests/api/test_job_detail.py tests/api/test_setup_status.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: enrich silent sponsorship signals"
```

### Task 9: Build Career Lab session, agents, and service

**Files:**
- Create: `src/resume_tailor_harness/career_lab/__init__.py`
- Create: `src/resume_tailor_harness/career_lab/models.py`
- Create: `src/resume_tailor_harness/career_lab/store.py`
- Create: `src/resume_tailor_harness/career_lab/agents.py`
- Create: `src/resume_tailor_harness/services/career_lab.py`
- Modify: `src/resume_tailor_harness/tenancy/workspace.py`
- Test: `tests/test_career_lab_store.py`
- Test: `tests/test_career_lab_agents.py`
- Test: `tests/test_career_lab_service.py`

**Interfaces:**
- `CareerLabContextRefs(profile_snapshot: Literal["current"] | None, job_id: int | None, resume_version_id: int | None, offer_application_ids: list[int], artifact: CareerLabArtifactRef | None)`
- `CareerLabRoute(skill: CareerLabSkillName | None, needs_selection: bool, reason: str)`
- `run_start_turn(reporter, *, root: Path, engine: Engine, message: str, goal: str, skill: CareerLabSkillName | None, context_refs: CareerLabContextRefs, sink: StreamSink) -> dict`
- `run_message_turn(reporter, *, root: Path, engine: Engine, session_id: str, message: str, skill: CareerLabSkillName | None, context_refs: CareerLabContextRefs, sink: StreamSink) -> dict`
- `run_end_turn(reporter, *, root: Path, session_id: str) -> dict`
- Durable path: `<workspace>/career-lab/session-<id>.json`.

- [ ] **Step 1: Write failing store and role-invariant tests**

```python
def test_assistant_turn_requires_exactly_one_skill_ref():
    with pytest.raises(ValidationError):
        CareerLabTurnRecord(role="assistant", text="draft", skill_ref=None)


def test_stopped_turn_keeps_transcript_byte_identical(tmp_path, service):
    path = create_active_session(tmp_path)
    before = path.read_bytes()
    with pytest.raises(TurnRejected):
        service.run_message_turn(session_id="s1", message="draft this", formatter=rejecting_formatter)
    assert path.read_bytes() == before
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_career_lab_store.py tests/test_career_lab_agents.py tests/test_career_lab_service.py -v`

Expected: FAIL because Career Lab does not exist.

- [ ] **Step 3: Define the closed session and artifact models**

```python
class CareerLabArtifactRef(ExtensibleModel):
    session_id: str
    turn_id: str


class CareerLabContextRefs(ExtensibleModel):
    profile_snapshot: Literal["current"] | None = None
    job_id: int | None = None
    resume_version_id: int | None = None
    offer_application_ids: list[int] = Field(default_factory=list, max_length=10)
    artifact: CareerLabArtifactRef | None = None


class CareerLabRoute(BaseModel):
    skill: CareerLabSkillName | None
    needs_selection: bool
    reason: str = Field(max_length=500)


class CareerLabArtifactMeta(ExtensibleModel):
    artifact_type: Literal[
        "application_answer", "email", "linkedin_profile", "offer_comparison",
        "case_study", "reference_list", "career_plan", "negotiation_plan"
    ]
    title: str = Field(max_length=200)
    summary: str = Field(max_length=1_000)


class CareerLabTurnRecord(ExtensibleModel):
    turn_id: str
    role: Literal["user", "assistant"]
    text: str = Field(max_length=100_000)
    at: str
    context_refs: CareerLabContextRefs | None = None
    skill_ref: SkillRef | None = None
    agent_meta: AgentRunMeta | None = None
    artifact: CareerLabArtifactMeta | None = None
    notice: str = ""
```

A model validator requires context references only on user turns and exactly one `SkillRef` plus matching `AgentRunMeta` on assistant turns. `CareerLabSession` extends `SessionModel` with optional goal, `ended_at`, and turns. Use the shared `SessionStore` for id validation, atomic writes, stable listing, one-active-session, archive/unarchive, and delete.

- [ ] **Step 4: Build three Agno agents with structural boundaries**

The Router Agent is tool-free and skill-free with `output_schema=CareerLabRoute` over the exact 12-name enum. The persona receives one `VerifiedSkill` through `LocalSkills` and streams prose. The formatter is tool-free and skill-free with `output_schema=CareerLabArtifactMeta`. Invalid/ambiguous routing sets `needs_selection=True` and invokes no persona.

- [ ] **Step 5: Resolve tenant context before the model call**

Resolve `job_id`, `resume_version_id`, `offer_application_ids`, current profile snapshot, and prior artifact inside the active workspace/database. Require the resume to belong to the referenced job, offer applications to have status `offer`, and prior artifact session/turn to exist in Career Lab. Bound each projected section and label it untrusted. Accept no path or raw database identifier outside these typed fields.

- [ ] **Step 6: Implement streamed turn commit semantics**

Use `persona_output()` and `format_with_retry()` from the shared session turn utilities. Persist the user and assistant turns together only after route, skill, persona, formatter, and Pydantic validation succeed. On formatter retry exhaustion, persist visible persona prose with the existing degraded notice and its real persona `SkillRef`; on cancellation before that decision, persist neither turn. End is deterministic and does not create a synthetic LLM recap.

- [ ] **Step 7: Run focused tests and commit**

Run: `uv run pytest tests/test_career_lab_store.py tests/test_career_lab_agents.py tests/test_career_lab_service.py tests/test_session_store.py tests/test_session_turns.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/career_lab src/resume_tailor_harness/services/career_lab.py src/resume_tailor_harness/tenancy/workspace.py tests/test_career_lab_store.py tests/test_career_lab_agents.py tests/test_career_lab_service.py
git commit -m "feat: add Career Lab sessions and agents"
```

### Task 10: Expose the Career Lab REST contract and regenerate clients

**Files:**
- Create: `src/resume_tailor_harness/api/schemas/career_lab.py`
- Create: `src/resume_tailor_harness/api/routers/career_lab.py`
- Modify: `src/resume_tailor_harness/api/app.py`
- Modify: `src/resume_tailor_harness/api/deps.py`
- Modify: `tests/api/test_openapi_contract.py`
- Create: `tests/api/test_career_lab_router.py`
- Modify generated: `contracts/openapi.json`
- Modify generated: `contracts/ts/api.ts`
- Modify generated: `web/src/lib/api/schema.ts`

**Interfaces:**
- `GET /api/career-lab/skills`
- `POST /api/career-lab/sessions` → `202 RunOut`
- `POST /api/career-lab/sessions/{session_id}/messages` → `202 RunOut`
- `POST /api/career-lab/sessions/{session_id}/end` → `202 RunOut`
- `GET /api/career-lab/sessions?page=1&pageSize=20&includeArchived=false`
- `GET /api/career-lab/sessions/{session_id}`
- `POST /api/career-lab/sessions/{session_id}/archive`
- `POST /api/career-lab/sessions/{session_id}/unarchive`
- `DELETE /api/career-lab/sessions/{session_id}` → `204`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_start_message_and_lifecycle_contract(client, completed_run):
    started = client.post("/api/career-lab/sessions", json={
        "goal": "Prepare negotiation points",
        "message": "Help me compare base and equity",
        "skill": "compensation-negotiator",
        "context": {"offerApplicationIds": [4, 7]},
    })
    assert started.status_code == 202
    assert started.json()["kind"] == "career-lab-turn"


def test_start_rejects_second_active_session(client, active_session):
    response = client.post("/api/career-lab/sessions", json={"message": "new"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_ACTIVE"
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `uv run pytest tests/api/test_career_lab_router.py tests/api/test_openapi_contract.py -v`

Expected: FAIL on missing routes and schemas.

- [ ] **Step 3: Define contract-first request and response types**

`CareerLabStartIn` requires a 1–100,000 character message and permits an optional 2,000-character goal, optional closed-enum skill, and typed context. `CareerLabMessageIn` has the same message/skill/context shape without goal. Skill list rows contain name, description, family, uses, `isAvailable`, and optional `unavailableReason`; they never expose filesystem paths or skill bodies.

`CareerLabSessionsOut` contains `sessions` and the existing shared `Pagination` envelope (`page`, `pageSize`, `totalItems`, `totalPages`). Page is at least 1; page size is 1–100, and the router declares `Query(alias="pageSize")` and `Query(alias="includeArchived")`. Session and turn outputs use camelCase aliases and typed artifact/skill fields.

- [ ] **Step 4: Mirror existing run and lifecycle semantics**

Use `launch()` with kinds `career-lab-turn` and `career-lab-end`, `singleton_key=f"career-lab:{session_id}"`, streamed run metadata containing session id, turn count, and the redacted `AgentRunMeta` fields, and the existing run recovery endpoints. Reject archive/unarchive/delete while that session has an active run. Map unknown session to 404, ended/active conflicts to 409, unavailable skills to 409 `CAPABILITY_UNAVAILABLE`, and invalid inputs to 422.

- [ ] **Step 5: Regenerate and verify contracts**

Run on Windows:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
```

Run: `uv run pytest tests/api/test_career_lab_router.py tests/api/test_openapi_contract.py tests/api/test_stream_event_parity.py -v`

Expected: PASS and no diff after rerunning the generation commands.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/career_lab.py src/resume_tailor_harness/api/routers/career_lab.py src/resume_tailor_harness/api/app.py src/resume_tailor_harness/api/deps.py tests/api/test_career_lab_router.py tests/api/test_openapi_contract.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: expose Career Lab API"
```

### Task 11: Add the Career Lab CLI

**Files:**
- Modify: `src/resume_tailor_harness/cli.py`
- Create: `tests/test_cli_career_lab.py`

**Interfaces:**
- Command: `resume-tailor-harness career-lab [GOAL] [--skill NAME] [--job-id ID] [--resume-version-id ID] [--offer-application-id ID (repeatable)]`
- Reuses `services.career_lab` and the existing terminal stream sink; it does not call an LLM or MCP client directly.

- [ ] **Step 1: Write failing CLI lifecycle tests**

```python
def test_career_lab_command_passes_typed_context_and_skill(monkeypatch):
    result = CliRunner().invoke(
        cli.app,
        ["career-lab", "Negotiate offer", "--skill", "salary-negotiation-prep", "--offer-application-id", "7"],
        input="Draft my counter\nend\n",
    )
    assert result.exit_code == 0, result.output
    assert captured.context.offer_application_ids == [7]
    assert captured.skill == "salary-negotiation-prep"
```

- [ ] **Step 2: Run the CLI test and verify failure**

Run: `uv run pytest tests/test_cli_career_lab.py -v`

Expected: FAIL because the command is absent.

- [ ] **Step 3: Implement the thin interactive command**

Validate `--skill` through `CareerSkillRegistry` before starting. Resume the single active Career Lab session when one exists; `end` closes it, `quit` leaves it active, and empty input is ignored. Print skill selection requests and degraded notices distinctly. Use typed ids only and preserve the same maximum message length as the API.

- [ ] **Step 4: Run focused CLI tests and commit**

Run: `uv run pytest tests/test_cli_career_lab.py tests/test_cli_scout.py tests/test_cli_profile_coach.py -v`

Expected: PASS.

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_career_lab.py
git commit -m "feat: add Career Lab CLI"
```

### Task 12: Build the responsive Career Lab workspace

**Files:**
- Create: `web/src/features/career-lab/use-career-lab.ts`
- Create: `web/src/features/career-lab/use-career-lab.test.tsx`
- Create: `web/src/features/career-lab/CareerLabPage.tsx`
- Create: `web/src/features/career-lab/CareerLabPage.test.tsx`
- Modify: `web/src/components/chat/GuidedWorkspaceHeader.tsx`
- Modify: `web/src/components/chat/GuidedWorkspaceHeader.test.tsx`
- Modify: `web/src/app/router.tsx`
- Modify: `web/src/app/AppLayout.tsx`
- Modify: `web/src/index.css`
- Create: `web/e2e/career-lab.spec.ts`

**Interfaces:**
- Route: `/career-lab`, lazy loaded behind `SetupGate`.
- Navigation label: `Career Lab` in the Prepare group.
- Hook consumes only generated OpenAPI types and existing run/SSE utilities.

- [ ] **Step 1: Write failing hook and workspace tests**

```tsx
it("requires an explicit choice when routing is ambiguous", async () => {
  render(<CareerLabPage />);
  await userEvent.type(screen.getByLabelText("Message Career Lab"), "Help with my career");
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/choose a skill/i);
  expect(screen.getByRole("combobox", { name: "Career skill" })).toHaveFocus();
});


it("does not append a cancelled partial assistant turn", async () => {
  const { result } = renderHook(() => useCareerLabSession("s1"), { wrapper });
  fakeStream.text("partial");
  fakeStream.cancelled();
  await waitFor(() => expect(result.current.session.turns).toHaveLength(2));
});
```

- [ ] **Step 2: Run web tests and verify failure**

Run: `npm --prefix web run test:run -- src/features/career-lab src/components/chat/GuidedWorkspaceHeader.test.tsx`

Expected: FAIL because the feature, route, navigation, and `career-lab` tone are absent.

- [ ] **Step 3: Implement typed hooks and run recovery**

Create query keys for skill capabilities, paginated sessions, and one session. Start/message/end mutations attach the returned run id to `useChatStream`, invalidate the session/list after terminal completion, and reuse the existing active-run rehydration registry. Archive/unarchive/delete invalidate both list and selected-session queries. Stop calls the existing run cancellation API and discards streamed preview text when the terminal state is cancelled/error.

- [ ] **Step 4: Implement the guided workspace**

The desktop layout has a session rail, central chat/artifact thread, and context/skill rail; collapse rails into keyboard-operable drawers on small screens. Provide the 12-skill picker with unavailable explanations, typed job/resume/offer selectors, streamed progress/tool disclosures, retry/stop/end actions, archive/unarchive/delete confirmation, empty/loading/error states, and refresh recovery. Outputs are visibly labeled “Draft”; do not add send, upload, apply, or profile-update actions.

Extend `GuidedWorkspaceTone` with `"career-lab"` and add a CSS tone variable. Every control needs a programmatic label, focus order must follow the visual order, dialogs must restore focus, and reduced-motion/reduced-transparency rules must remain effective.

- [ ] **Step 5: Run component, accessibility, and production checks**

Run:

```bash
npm --prefix web run test:run -- src/features/career-lab src/components/chat/GuidedWorkspaceHeader.test.tsx src/test/a11y.test.tsx
npm --prefix web run lint
npm --prefix web run build
```

Expected: all commands PASS.

- [ ] **Step 6: Run the focused browser journey and commit**

Run: `npm --prefix web run e2e -- career-lab.spec.ts`

Expected: PASS for start → stream → refresh recovery → continue → stop without partial persistence → end → archive, including keyboard-only skill selection at mobile and desktop viewports.

```bash
git add web/src/features/career-lab web/src/components/chat/GuidedWorkspaceHeader.tsx web/src/components/chat/GuidedWorkspaceHeader.test.tsx web/src/app/router.tsx web/src/app/AppLayout.tsx web/src/index.css web/e2e/career-lab.spec.ts
git commit -m "feat: add Career Lab workspace"
```

### Task 13: Enforce agent/tool boundaries and complete broad verification

**Files:**
- Create: `tests/test_career_agent_boundaries.py`
- Modify: `tests/test_agent_prompt_contracts.py`
- Modify: `tests/api/test_openapi_contract.py`
- Modify: `README.md`
- Modify: `.env.example`

**Interfaces:**
- No new runtime interface; this task locks the approved architecture and operator contract.

- [ ] **Step 1: Add architecture and prompt-injection tests**

```python
def test_only_sponsorship_agent_receives_mcp_tools(all_built_agents):
    tool_owners = {
        row.family for row in all_built_agents if any(isinstance(tool, MCPTools) for tool in row.tools)
    }
    assert tool_owners == {AgentFamily.SPONSORSHIP_RESEARCH}


def test_every_affected_model_call_is_an_agno_agent():
    forbidden = find_provider_client_calls([
        "src/resume_tailor_harness/career_lab",
        "src/resume_tailor_harness/h1b",
        "src/resume_tailor_harness/discovery",
        "src/resume_tailor_harness/tailor",
        "src/resume_tailor_harness/cover_letter",
        "src/resume_tailor_harness/interview",
    ])
    assert forbidden == []
```

Add malicious job, skill, Career Lab message, and MCP fixture cases that attempt to enable tools, mutate data, expose secrets, or relabel historical sponsorship. Assert fixed tool availability, unchanged filters/fact locks, validated output, and redacted logs.

Assert structured logs contain family, policy version, model, skill identity,
run/job/session correlation ids, and H-1B enabled/cache/latency/result counts,
but never credentials, prompts, skill bodies, raw MCP payloads, resumes,
profile bodies, contact details, or full messages.

- [ ] **Step 2: Document only the implemented operator surface**

Add the nine approved environment variables to `.env.example`, describe local stdio and Streamable HTTP configuration without embedding a community URL, state the three read-only tools, and explain historical-only semantics. Document Career Lab web/API/CLI usage and its draft-only boundary. Do not document excluded MCP providers or future write actions as available.

```dotenv
CAREER_SKILL_ROOT=./skills
CAREER_SKILL_MANIFEST=./skills-lock.json
H1B_MCP_ENABLED=false
H1B_MCP_TRANSPORT=stdio
H1B_MCP_COMMAND=
H1B_MCP_URL=
H1B_MCP_TIMEOUT_SECONDS=30
H1B_MCP_MAX_RESULT_CHARS=200000
H1B_CACHE_TTL_DAYS=30
```

- [ ] **Step 3: Run all focused backend suites together**

Run:

```bash
uv run pytest tests/test_career_skill_registry.py tests/test_agent_skills.py tests/test_career_agent_boundaries.py tests/test_h1b_config.py tests/test_h1b_mcp.py tests/test_h1b_service.py tests/test_career_lab_store.py tests/test_career_lab_agents.py tests/test_career_lab_service.py tests/api/test_career_lab_router.py tests/api/test_job_detail.py tests/api/test_openapi_contract.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the full repository verification**

Run: `make verify`

Expected: Python lint, full Python/API tests, web lint/tests, and production web build all complete successfully. A timeout or interrupted command is incomplete verification, not a pass.

- [ ] **Step 5: Re-run generation and dirty-tree checks**

Run:

```powershell
.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts/openapi.json -o contracts/ts/api.ts
Copy-Item -LiteralPath contracts/ts/api.ts -Destination web/src/lib/api/schema.ts
git diff --check
git status --short
```

Expected: generation produces no new diff; `git diff --check` is clean; status contains only the intended documentation/test updates for this task.

- [ ] **Step 6: Commit the verification contract**

```bash
git add tests/test_career_agent_boundaries.py tests/test_agent_prompt_contracts.py tests/api/test_openapi_contract.py README.md .env.example
git commit -m "test: lock career agent tool boundaries"
```

## Final Acceptance Checklist

- [ ] All 35 committed skills are represented exactly once by a tracked, hash-valid manifest; 34 are public and `project-dossier` is internal.
- [ ] Each skilled task agent receives exactly one `LocalSkills` directory, and every affected LLM call is an Agno `Agent` behind `AgentRunner`.
- [ ] Existing specialized workflows use the fixed skill routes or an explicit same-family selector and persist exact `SkillRef`/`SkillUse` metadata.
- [ ] Career Lab exposes all 12 general career skills via web, API, and CLI with one active session, streaming, recovery, stop, end, archive, unarchive, and delete.
- [ ] Career Lab context is tenant-scoped and typed; outputs are drafts and have no external mutation tools.
- [ ] H-1B remains disabled by default and supports exactly one configured stdio or Streamable HTTP transport.
- [ ] Only the three prefixed H-1B read tools are callable, and all connections close on success, cancellation, partial startup, and per-company failure.
- [ ] Only sponsorship-required, JD-silent jobs invoke H-1B; historical evidence remains caveated and cannot flip the posting signal or reject a job.
- [ ] Fresh company cache entries prevent duplicate calls; `matched`, `no_match`, and `unavailable` remain distinct.
- [ ] Job, resume, cover-letter, interview, Career Lab, and run metadata retain the exact skill/model/prompt-policy identity that influenced them.
- [ ] API contracts and TypeScript clients are current; focused tests, browser tests, and `make verify` pass completely.
