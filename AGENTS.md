# Agent Instructions

Full developer/architecture reference lives in [`CLAUDE.md`](CLAUDE.md) — read
it before making non-trivial changes. This file exists so the rule below
applies to every coding agent that operates in this repo, not just
Claude-branded tooling.

## Branching (mandatory, no exceptions)

- `dev` is the integration branch. **Every** branch — feature, fix, chore,
  dependency bump — is created from `dev`, not from `main`.
- `main` only ever receives merges from `dev`, via PR. Never open a PR into
  `main` from any other branch, and never push directly to `main`.
- `main` is protected: PR required, required status checks
  (`ci / python-quality`, `ci / web-quality`, `ci / security-audit`,
  `require-dev-base`), no force-pushes. `main` is the only branch Railway
  deploys from.
- If you are an agent proposing or opening a PR, target `dev` unless you are
  specifically promoting `dev` → `main`.

See `CLAUDE.md` > Branching for the full rationale and CI wiring.
