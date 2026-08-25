# Contributing to Resume Agent

Thanks for your interest in contributing! This guide covers local setup and the
checks your change must pass.

## Prerequisites

- **Python 3.13** and [`uv`](https://docs.astral.sh/uv/)
- **Node 22** and `npm`

## Setup

```bash
uv run --no-project scripts/bootstrap.py
make setup           # equivalent short alias
make setup-browser   # optional: Playwright Chromium, only for live scraping
```

## Running the app

```bash
uv run python scripts/dev.py  # works on Windows, macOS, and Linux
make dev                     # equivalent short alias
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

CI is split by branch. PRs and pushes into `dev` run the quick gate —
`python-quality` and `web-quality` lint + test only, for fast feedback. PRs and
pushes into `main` run the full gate — the same two jobs plus the web
production build and a non-blocking security audit (`pip-audit` +
`npm audit`). Fix failures — don't skip tests or disable lint rules to get
green. CodeQL analysis (`.github/workflows/codeql.yml`) is prepared but
commented out while the repo is private; it activates once the repo goes
public.

## Branch protection

`main` requires passing CI and at least one review. Please branch from `dev`
and open a PR back into `dev` rather than targeting `main` directly.
