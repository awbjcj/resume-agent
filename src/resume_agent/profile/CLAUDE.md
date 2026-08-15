# Profile developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/profile/`.

- **Profile coaching is turn-per-run and evidence-locked.** Durable sessions follow
  ADR 0006, while the ADR 0005 amendment requires every draft note to retain
  verbatim quotes from the current user turn. The former batch interview API,
  CLI command, and web panel are retired; its history remains read-only input
  for avoiding repeated questions.
- **GitHub depth is two-tier; dossiers win.** `profile/github_harvest.py` writes
  qualifying repositories' root docs (README files plus CLAUDE, CONTEXT, and
  AGENTS markdown, capped at 30 KB per file) as deterministic
  `sources/github--<repo>.md` documents with `origin="github"` and
  `mode="project"` during build phase 0 and `profile sync-github`. A markdown
  upload with `repo_url:` frontmatter, such as output from
  `.claude/skills/project-dossier`, supersedes the auto-document for the same
  normalized repository URL. Harvest also discovers root files named
  `*dossier*.md` (max 5 per repo, 30 KB each) whose `repo_url` frontmatter
  matches the repo; each becomes its own `github--<repo>--<stem>.md` project
  source and replaces that repo's README virtual doc. Manual uploads still
  supersede all harvested docs for the repo. `project_extractor.py` can emit exactly one Project
  plus skills, never Experience or Education. GitHub failures become build
  warnings; rate-limited harvests stop early without deleting existing sources.
- **Profile rebuilds regenerate inferred skills.** `profile build` strips and re-derives
  all `inferred=true` skills; durable corrections belong in `data/profile/overrides.yaml`,
  not hand-edits to facts.json.
- **Synthesis ingest is text-only.** markitdown converts slide text frames, tables, and
  speaker notes; images/diagrams are skipped, and an LLM image description is never
  verification evidence (it would punch a hole in fact-lock). Put key numbers in slide
  text or speaker notes so they are extractable.
- **Profile build fans out per document.** `extract_fragments` /
  `extract_synthesis_fragments` share one cache walk; production runs concurrently via
  `gather_isolated` with the permit acquired only in `llm_runner.acall`. The CLI and API both
  build through `services/profile_build.run_corpus_build` -- the single place the facts+matrix
  bound-artifact pair is written.
