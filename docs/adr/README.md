# Architecture Decision Records

Decisions the architecture reviews must not re-litigate. Newest last.

| ADR | Decision | One-line summary |
| --- | --- | --- |
| [0001](0001-dedup-key-plus-location-guard.md) | Dedup key + location guard | `compute_dedup_key` stays `company\|normalized_title`; `find_existing` adds a location-compatibility guard so multi-location same-title reqs become sibling rows. |
| [0002](0002-single-service-sqlite-volume-whole-root-custody.md) | Single service, whole-root custody | One Railway service owns one SQLite volume; export/import moves the whole Data root, never a slice. |
| [0003](0003-contextvar-tenancy-propagation.md) | ContextVar tenancy propagation | The active `UserContext` rides a contextvar set at the API dependency, `RunManager.submit`, and the CLI callback; no second propagation mechanism. |
| [0004](0004-company-rename-recomputes-dedup-key-skip-on-collision.md) | Company rename recomputes dedup key | Renames recompute `dedup_key`; collisions skip rather than merge. |
| [0005](0005-read-only-agent-tools-deterministic-writes.md) | Read-only agent tools | Every tool inside an agent loop is read-only; writes happen after the loop through deterministic services behind user approval. |
| [0006](0006-turn-per-run-conversational-sessions.md) | Turn-per-run conversational sessions | Durable session JSON per conversation; one user message → one run → one typed turn. The Session substrate (`sessions/store.py`) is its custody implementation. |
