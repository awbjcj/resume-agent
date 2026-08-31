# Open-Source Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `resume-tailor-harness` safe and feasible to publish as a public GitHub repo — automated CI quality gates, MIT license, security tooling, and community-health files.

**Architecture:** Add GitHub-native config and docs only. CI mirrors the existing `Makefile` targets so `make verify` and CI stay in lockstep. Two toolchains (`uv`/Python 3.13, `npm`/Vite) each get their own parallel CI job. No application code changes; no git-history rewrite (history is already secret-free).

**Tech Stack:** GitHub Actions, `astral-sh/setup-uv`, `actions/setup-node`, CodeQL, Dependabot, ruff, pytest, eslint, vitest.

## Global Constraints

- License: **MIT**, `Copyright (c) 2026 awbjcj`.
- Python: **3.13** (`.python-version` = `3.13`); package manager **uv** (`uv.lock` committed).
- Web: **Node 22**, package manager **npm** (`web/package-lock.json` committed); all web commands run in `web/`.
- Python tests are **fully offline** — no API key, no network, no Playwright browser install in CI.
- CI is **verify-only** — no deploy jobs. Railway stays manual.
- security-audit job is **non-blocking** (`continue-on-error: true`).
- CI job names that become required checks: **`python-quality`** and **`web-quality`**.
- Do **not** modify application code, dependencies, or the fact-lock / tenancy invariants.
- Ruff has no `[tool.ruff]` config — CI uses the same invocation as the Makefile: `ruff check src tests evals`.
- All new GitHub files live under `.github/` except `LICENSE` (repo root).

---

### Task 1: MIT LICENSE

**Files:**
- Create: `LICENSE`

**Interfaces:**
- Produces: a repo-root `LICENSE` file GitHub auto-detects as MIT; referenced by README (Task 8) and `pyproject.toml` is already `version = "0.1.0"` (no change needed).

- [ ] **Step 1: Create `LICENSE`**

```text
MIT License

Copyright (c) 2026 awbjcj

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify**

Run: `head -1 LICENSE`
Expected: `MIT License`

- [ ] **Step 3: Commit**

```bash
git add LICENSE
git commit -m "Add MIT license"
```

---

### Task 2: CI workflow (python-quality + web-quality)

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: existing Makefile-equivalent commands (`ruff check src tests evals`, `uv run pytest tests`, `npm ci`, `npm run lint`, `npm run test:run`, `npm run build`).
- Produces: two required status checks named `python-quality` and `web-quality`, plus a non-blocking `security-audit` job. These check names are referenced by the branch-protection checklist (Task 9) and the README CI badge (Task 8).

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  python-quality:
    name: python-quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version: "3.13"
      - name: Sync dependencies
        run: uv sync --frozen
      - name: Lint (ruff)
        run: uv run ruff check src tests evals
      - name: Test (pytest, offline)
        run: uv run pytest tests

  web-quality:
    name: web-quality
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json
      - name: Install dependencies
        run: npm ci
      - name: Lint (eslint)
        run: npm run lint
      - name: Test (vitest)
        run: npm run test:run
      - name: Build
        run: npm run build

  security-audit:
    name: security-audit
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          python-version: "3.13"
      - name: Python dependency audit
        run: uvx pip-audit || true
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json
      - name: Web dependency audit
        working-directory: web
        run: npm audit --audit-level=high || true
```

- [ ] **Step 2: Validate YAML locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid yaml')"`
Expected: `valid yaml`

- [ ] **Step 3: Confirm the CI commands match local reality**

Run: `uv run ruff check src tests evals && uv run pytest tests -q`
Expected: ruff passes; pytest reports all tests passing (this is the exact python-quality job).

Run: `cd web && npm run lint && npm run test:run && npm run build; cd ..`
Expected: eslint clean, vitest green, build produces `web/dist/` (this is the exact web-quality job). If any of these already fail locally on `main`, STOP and report — CI must not be shipped red.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "Add CI workflow: python + web quality gates, non-blocking audit"
```

---

### Task 3: CodeQL workflow

**Files:**
- Create: `.github/workflows/codeql.yml`

**Interfaces:**
- Produces: a CodeQL analysis workflow for `python` and `javascript-typescript`; results appear in the repo Security tab. Independent of Task 2.

- [ ] **Step 1: Create `.github/workflows/codeql.yml`**

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 6 * * 1"

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    name: analyze (${{ matrix.language }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: [python, javascript-typescript]
    steps:
      - uses: actions/checkout@v4
      - name: Initialize CodeQL
        uses: github/codeql-action/init@v3
        with:
          language: ${{ matrix.language }}
      - name: Autobuild
        uses: github/codeql-action/autobuild@v3
      - name: Perform CodeQL analysis
        uses: github/codeql-action/analyze@v3
        with:
          category: "/language:${{ matrix.language }}"
```

- [ ] **Step 2: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/codeql.yml')); print('valid yaml')"`
Expected: `valid yaml`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/codeql.yml
git commit -m "Add CodeQL static analysis workflow"
```

---

### Task 4: Dependabot

**Files:**
- Create: `.github/dependabot.yml`

**Interfaces:**
- Produces: weekly dependency-update PRs for `pip`, `npm` (`/web`), and `github-actions`.

- [ ] **Step 1: Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
    open-pull-requests-limit: 5

  - package-ecosystem: npm
    directory: /web
    schedule:
      interval: weekly
    open-pull-requests-limit: 5

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    open-pull-requests-limit: 5
```

- [ ] **Step 2: Validate YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml')); print('valid yaml')"`
Expected: `valid yaml`

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "Add Dependabot for pip, npm, and github-actions"
```

---

### Task 5: CONTRIBUTING.md

**Files:**
- Create: `.github/CONTRIBUTING.md`

**Interfaces:**
- Consumes: CI check names from Task 2 (`python-quality`, `web-quality`).
- Produces: contributor guide referenced by the PR template (Task 7) and README (Task 8).

- [ ] **Step 1: Create `.github/CONTRIBUTING.md`**

```markdown
# Contributing to Résumé Tailor Harness

Thanks for your interest in contributing! This guide covers local setup and the
checks your change must pass.

## Prerequisites

- **Python 3.13** and [`uv`](https://docs.astral.sh/uv/)
- **Node 22** and `npm`

## Setup

```bash
make setup           # uv sync + npm install (in web/)
make setup-browser   # optional: Playwright Chromium, only for live scraping
```

## Running the app

```bash
make dev             # FastAPI backend + Vite frontend together
```

## Before you open a PR

Run the full local gate — it mirrors CI exactly:

```bash
make verify          # lint + tests + web build
```

Or individually:

```bash
make lint            # ruff (Python) + eslint (web)
make test            # pytest (API) + vitest (web)
make build           # web production build
```

The Python suite is **fully offline** — agents and the browser are faked, so it
needs no API key and no network. Please keep new tests offline; use fixtures, not
live endpoints.

## Ground rules

- **Fact-lock is sacred.** Every bullet a tailored resume produces must trace to a
  fact in the profile. Do not add code paths that let agents invent experience,
  and do not weaken the `fact-check` review gate.
- Match the surrounding code's style, naming, and structure.
- Keep commits focused; write a clear commit message.

## CI

Every PR runs `python-quality` and `web-quality` (both must pass to merge) plus a
non-blocking security audit and CodeQL analysis. Fix failures — don't skip tests
or disable lint rules to get green.

## Branch protection

`main` requires passing CI and at least one review. Please branch from `main` and
open a PR rather than pushing directly.
```

- [ ] **Step 2: Verify**

Run: `head -1 .github/CONTRIBUTING.md`
Expected: `# Contributing to Résumé Tailor Harness`

- [ ] **Step 3: Commit**

```bash
git add .github/CONTRIBUTING.md
git commit -m "Add CONTRIBUTING guide"
```

---

### Task 6: SECURITY.md + CODE_OF_CONDUCT.md

**Files:**
- Create: `.github/SECURITY.md`
- Create: `.github/CODE_OF_CONDUCT.md`

**Interfaces:**
- Produces: GitHub-recognized security policy and code of conduct (both surface in Insights → Community Standards).

- [ ] **Step 1: Create `.github/SECURITY.md`**

```markdown
# Security Policy

## Supported versions

This project is developed on `main`. Security fixes are applied to `main` only.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's
[Security Advisories](https://github.com/awbjcj/resume-tailor-harness/security/advisories/new)
("Report a vulnerability" button). Include:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- any known mitigations.

You can expect an initial acknowledgement within a few days. Once a fix is ready,
we will coordinate disclosure.

## Scope notes

- This is a local-first application: secrets (API keys, OAuth tokens) live in a
  local `.env` and per-user workspace files that are **never** committed. Reports
  about committed secrets should reference a specific tracked file.
- Third-party dependency CVEs are tracked via Dependabot; report only if you have
  a concrete exploit path through this project's code.
```

- [ ] **Step 2: Create `.github/CODE_OF_CONDUCT.md`**

```markdown
# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone, regardless of age, body
size, visible or invisible disability, ethnicity, sex characteristics, gender
identity and expression, level of experience, education, socio-economic status,
nationality, personal appearance, race, religion, or sexual identity and
orientation.

## Our Standards

Examples of behavior that contributes to a positive environment:

- Demonstrating empathy and kindness toward other people
- Being respectful of differing opinions, viewpoints, and experiences
- Giving and gracefully accepting constructive feedback
- Accepting responsibility and apologizing to those affected by our mistakes

Examples of unacceptable behavior:

- The use of sexualized language or imagery, and sexual attention or advances
- Trolling, insulting or derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the project maintainer through GitHub. All complaints will be
reviewed and investigated promptly and fairly.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant][homepage],
version 2.1, available at
https://www.contributor-covenant.org/version/2/1/code_of_conduct.html.

[homepage]: https://www.contributor-covenant.org
```

- [ ] **Step 3: Verify both**

Run: `head -1 .github/SECURITY.md .github/CODE_OF_CONDUCT.md`
Expected: shows `# Security Policy` and `# Contributor Covenant Code of Conduct`

- [ ] **Step 4: Commit**

```bash
git add .github/SECURITY.md .github/CODE_OF_CONDUCT.md
git commit -m "Add security policy and code of conduct"
```

---

### Task 7: Issue + PR templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/pull_request_template.md`

**Interfaces:**
- Consumes: `make verify` (Task 5 setup) and CI check names (Task 2) referenced in the PR checklist.
- Produces: GitHub-detected issue forms and PR template.

- [ ] **Step 1: Create `.github/ISSUE_TEMPLATE/bug_report.md`**

```markdown
---
name: Bug report
about: Report something that isn't working
title: "[Bug] "
labels: bug
---

**Describe the bug**
A clear and concise description of what the bug is.

**To reproduce**
Steps to reproduce the behavior (command, endpoint, or UI action):

1.
2.

**Expected behavior**
What you expected to happen.

**Environment**
- OS:
- Python version (`python --version`):
- Node version (`node --version`):
- Interface: CLI / web / API

**Logs / output**
Paste relevant output. **Redact any API keys, tokens, or personal data.**
```

- [ ] **Step 2: Create `.github/ISSUE_TEMPLATE/feature_request.md`**

```markdown
---
name: Feature request
about: Suggest an idea or improvement
title: "[Feature] "
labels: enhancement
---

**Problem**
What problem does this solve? What are you trying to do?

**Proposed solution**
A clear and concise description of what you want to happen.

**Alternatives considered**
Any alternative approaches you've thought about.

**Additional context**
Anything else — mockups, links, examples.
```

- [ ] **Step 3: Create `.github/ISSUE_TEMPLATE/config.yml`**

```yaml
blank_issues_enabled: false
contact_links:
  - name: Security vulnerability
    url: https://github.com/awbjcj/resume-tailor-harness/security/advisories/new
    about: Please report security issues privately, not as public issues.
```

- [ ] **Step 4: Create `.github/pull_request_template.md`**

```markdown
## Summary

<!-- What does this change and why? -->

## Related issue

<!-- e.g. Closes #123 -->

## Checklist

- [ ] `make verify` passes locally (lint + tests + web build)
- [ ] New tests are offline (no live API/network calls)
- [ ] Does not weaken fact-lock or the `fact-check` review gate
- [ ] Docs/README updated if behavior or commands changed
```

- [ ] **Step 5: Verify structure**

Run: `ls .github/ISSUE_TEMPLATE/ && ls .github/pull_request_template.md`
Expected: lists `bug_report.md  config.yml  feature_request.md` and the PR template path.

Run: `python -c "import yaml; yaml.safe_load(open('.github/ISSUE_TEMPLATE/config.yml')); print('valid yaml')"`
Expected: `valid yaml`

- [ ] **Step 6: Commit**

```bash
git add .github/ISSUE_TEMPLATE .github/pull_request_template.md
git commit -m "Add issue and pull request templates"
```

---

### Task 8: README polish (badges + sections + opening reframe)

**Files:**
- Modify: `README.md` (top: title + opening; bottom: append sections)

**Interfaces:**
- Consumes: `LICENSE` (Task 1), `.github/CONTRIBUTING.md` (Task 5), `.github/SECURITY.md` (Task 6), CI workflow name `CI` (Task 2).
- Produces: badges and Contributing/Security/License sections.

- [ ] **Step 1: Add badge row + reframe the opening**

Replace the current top of `README.md`:

```markdown
# Résumé Tailor Harness

A personal, command-line job-hunt pipeline. It pulls job posts from multiple
sources (job-board connectors, LinkedIn, or hand-pasted), scores them against a
**fact-locked** profile of _your_ real experience, helps you tailor a resume
through a panel of reviewer agents, drafts a matching cover letter, renders both
to PDF, and tracks every application — auto-syncing statuses from your Gmail —
all on your own machine, in one SQLite database.
```

with:

```markdown
# Résumé Tailor Harness

[![CI](https://github.com/awbjcj/resume-tailor-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/awbjcj/resume-tailor-harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)

A local-first, command-line and web job-hunt pipeline. Point it at your own
resume and API keys, and it pulls job posts from multiple sources (job-board
connectors, LinkedIn, or hand-pasted), scores them against a **fact-locked**
profile of your real experience, helps you tailor a resume through a panel of
reviewer agents, drafts a matching cover letter, renders both to PDF, and tracks
every application — auto-syncing statuses from your Gmail — all on your own
machine, in one SQLite database.
```

- [ ] **Step 2: Append community sections at the end of `README.md`**

Add after the final line:

```markdown

## Contributing

Contributions are welcome. See [CONTRIBUTING](.github/CONTRIBUTING.md) for local
setup and the checks your change must pass (`make verify`). Please branch from
`main` and open a PR.

## Security

Found a vulnerability? Please report it privately — see the
[security policy](.github/SECURITY.md). Do not open a public issue for security
reports.

## License

[MIT](LICENSE) © awbjcj
```

- [ ] **Step 3: Verify**

Run: `grep -c "badge" README.md && grep -q "## License" README.md && echo "sections present"`
Expected: badge count ≥ 3 and `sections present`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Polish README: badges, contributing/security/license sections, open-source framing"
```

---

### Task 9: Branch-protection checklist (owner hand-off)

**Files:**
- None (documentation delivered in final summary; no repo file required).

**Interfaces:**
- Consumes: CI check names `python-quality`, `web-quality` (Task 2).
- Produces: a checklist the repo owner applies in GitHub settings (cannot be set from code).

- [ ] **Step 1: Produce the checklist**

Present this to the owner (also fine to paste into the PR description):

```
GitHub → Settings → Branches → Add branch protection rule for `main`:
- [ ] Require a pull request before merging (≥ 1 approval)
- [ ] Dismiss stale approvals when new commits are pushed
- [ ] Require status checks to pass before merging:
      - python-quality
      - web-quality
- [ ] Require branches to be up to date before merging
- [ ] Do not allow force pushes; do not allow deletions

GitHub → Settings → Code security:
- [ ] Enable Dependabot alerts + security updates
- [ ] Enable secret scanning + push protection
- [ ] CodeQL runs automatically once ci/codeql workflows are on the default branch

Only after CI is green on this branch: make the repository public.
```

- [ ] **Step 2: No commit** (nothing to commit for this task).

---

## Final verification (after all tasks)

- [ ] `make verify` passes locally (lint + tests + web build) — CI parity.
- [ ] All YAML workflows/config parse (`python -c "import yaml; ..."` for each).
- [ ] GitHub Insights → Community Standards shows LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue + PR templates all detected (checked after push/PR).
- [ ] CI run on the PR shows `python-quality` and `web-quality` green.
- [ ] Owner has the branch-protection checklist (Task 9).
