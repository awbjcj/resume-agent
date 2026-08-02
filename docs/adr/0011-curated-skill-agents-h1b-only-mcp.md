# 11. Use curated single-skill agents and isolate H-1B as the only MCP toolset

## Status

Accepted.

## Date

2026-08-02

## Decision

Career procedures are supplied to curated Agno agent families through a
verified local skill registry. One task agent sees exactly one hash-pinned
skill. Specialized workflows select their skill deterministically; Career Lab
may use a tool-free structured router constrained to its closed skill enum.
Application services retain routing, validation, persistence, scoring,
fact-lock, approval, and mutation authority.

H-1B sponsorship research is the only MCP integration in this release. A
dedicated Sponsorship Research Agent owns one prefixed, read-only `MCPTools`
instance for a batch. It runs only for sponsorship-required jobs whose posting
is silent, and returns historical company evidence that cannot become a
current-role sponsorship claim. Other agents consume validated evidence and
never receive raw MCP access.

## Consequences

- All career skills remain available without giving one model a large combined
  instruction or tool surface.
- Skill identity, version, and hash become auditable run/artifact metadata.
- Bad skill locks fail closed per capability; H-1B failure degrades to explicit
  unavailable evidence without blocking discovery.
- A new Career Lab session surface is required for skills without an existing
  specialized workflow.
- The repository adds Agno's MCP dependency and H-1B configuration, caching,
  fixtures, and lifecycle tests, but does not vendor an MCP server.
- Other MCP servers and all external write actions require separate decisions.
