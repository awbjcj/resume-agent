---
name: project-dossier
description: Generate an evidence-backed project dossier markdown for the resume-agent profile corpus. Use when the user asks to create a project dossier, document a repository for their resume profile, or extract a project profile from the current repository.
---

# Project Dossier

Distill the current repository into one fact-locked markdown source that
resume-agent can ingest in `project` mode. Every claim must be verifiable from
the repository's code, documentation, tests, or git history.

## Workflow

1. Confirm the repository root and inspect its canonical `origin` remote.
2. Read implementation files and tests before relying on README claims.
3. Use git history and shortlog only for contribution role and commit-backed
   outcomes. Do not infer authorship from the working tree alone.
4. Draft the required structure below, citing repository-relative paths and
   commit hashes where they support architecture or quantified claims.
5. Re-read every sentence and remove anything the repository cannot prove.

## Output contract

Write `<repo-name>-dossier.md` at the repository root, or at the location the
user requests. Start with this frontmatter. `repo_url` is the stable identity
resume-agent uses to supersede an auto-harvested GitHub source:

When the repository contains multiple distinct projects (a monorepo), write
one `<project-slug>-dossier.md` per project at the repository root. Every
dossier uses the same `repo_url` (the repository's canonical URL); each file
describes exactly one project in its `# Project:` section.

```yaml
---
repo_url: <canonical HTTPS repository URL derived from git remote get-url origin>
repo_name: <repository directory name>
role: <sole author | maintainer | contributor, supported by git shortlog>
generated_at: <today, YYYY-MM-DD>
---
```

Then use exactly these sections.

### `# Project: <name>`

Give one line positioning what the project is and who it serves.

### `## Summary`

Write 3-6 sentences covering the problem, approach, contributor role, and
current state such as shipped, active, or archived. Include only supported
statements.

### `## Tech stack (evidence-backed)`

Use bullets naming each technology and where it is used, for example:
`- FastAPI - API layer in src/api/ (12 routers)`. Omit technologies mentioned
only in documentation or roadmaps when implementation evidence is absent.

### `## Architecture highlights`

Write 3-8 bullets about visible design decisions, seams, invariants, or
performance structures. Cite the relevant file or module inline.

### `## Quantified outcomes`

Include only repository-backed numbers: checked-in benchmark results, test or
coverage reports, or commit-visible before/after metrics. Cite the evidence.
If none exist, write `None evidenced.` Never estimate.

### `## Skills demonstrated`

Use `category: skill, skill, ...` lines. Include a skill only when repository
work demonstrates it, not when a roadmap merely names it.

## Rules

1. Never make employment, job-title, education, or certification claims. This
   dossier describes a project, even when repository prose mentions a career.
2. Prefer code and tests over README assertions. Omit unsupported README claims.
3. Cite evidence inline for every architectural or quantified statement.
4. Preserve uncertainty. Rich detail is useful, but one fabricated claim
   poisons the profile fact-lock; leave doubtful claims out.
5. Do not include secrets, tokens, private URLs, or sensitive configuration.

## Handoff

Tell the user to run:

```text
resume-agent profile add <repo-name>-dossier.md
resume-agent profile build
```

The `repo_url` frontmatter makes the upload a project source and lets it replace
the shallower auto-harvested document for that repository.

Committing dossiers to the repository root also works without the manual
`profile add`: `resume-agent profile sync-github` discovers root files named
`*dossier*.md` (up to 5 per repository, 30 KB each), validates their
`repo_url` frontmatter, and ingests each as its own project source, replacing
the auto-harvested README document. A manual upload still overrides
everything harvested for that repository.
