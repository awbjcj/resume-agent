# Agent prompts developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_tailor_harness/prompts/`.

- **Agent prompts are registry-projected; guidance is layered.**
  `prompts/registry.py` imports the complete invariant instruction composition
  from each production agent builder. Per-agent guidance lives in
  `config/agent_guidance.yaml`, is capped at 4,000 characters, and is appended
  beneath immutable rules by `prompts/guidance.py:with_guidance`; it may steer
  tone, emphasis, or process, never facts. `reviewer-fact-check` is the only
  non-editable integrity gate. API: `GET /api/agents/prompts` and
  `PUT /api/agents/prompts/{key}`.
