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
