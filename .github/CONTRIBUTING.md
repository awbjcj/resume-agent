# Contributing to Resume Agent

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
