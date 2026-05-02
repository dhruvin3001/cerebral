# cerebral v3 — Smart Context Loading

**Date:** 2026-05-02
**Status:** Validated

## Context

Current `load_context` runs 14 semantic searches against a meaningless generic query (`"general preferences corrections patterns warnings"`), each capped at `limit=3`. Most stored memories never surface. The brief is the same noisy blob every session because the query has nothing to do with what the agent is about to do. This conflates two fundamentally different memory types:

- **Always-on memories** (constraints): warnings, corrections, preferences, project decisions — should ambient, every session
- **On-demand memories** (references): facts, workarounds, patterns — only relevant when topic activates them

## Decision

Split context loading into two distinct mechanisms modeled on how human recall actually works:

1. **`load_context` becomes the always-on brief.** Deterministic, lean, no semantic search. Loads ALL warnings + corrections + global preferences + project decisions via `get_all`. Same brief every session because constraints don't change session-to-session.

2. **Mid-session active recall via `search_memories`.** The judgment framework gets explicit, aggressive triggers for when to search. The agent queries memory reactively as topics surface in conversation — not predictively at session start.

## Requirements

- `load_context` returns ALL memories of constraint types, not top-N filtered by similarity
- Constraint types: `warning`, `correction`, `preference` (global only), `decision` (project only)
- Reference types (`fact`, `workaround`, `pattern`) excluded from session-start brief
- Untyped fallback retained for pre-v2 memories
- Judgment framework adds compaction-recovery trigger ("if brief is no longer visible, reload")
- Judgment framework adds 4+ explicit mid-session search triggers

## Constraints

- No new MCP tools — reuse `load_context` and `search_memories`
- Backwards compat with pre-v2 untyped memories
- Brief should stay under ~30 bullets in practice (warnings/corrections should be rare; consolidation in roadmap if they aren't)

## Out of Scope

- Memory consolidation (separate roadmap item #5)
- File-tagged memories (separate roadmap item)
- Confidence/staleness decay (separate roadmap item)
- Auto-detection of compaction (handled in judgment framework via "if brief missing, reload")

## Open Questions

- [ ] Cap on always-on brief size if warnings grow large? Or rely on consolidation later?
- [ ] Should the brief include `pattern` memories scoped to the current project? (Project patterns are arguably constraints — the codebase's conventions.)

## Success Criteria

- [ ] Session start shows ALL warnings + corrections (not top-3 by query similarity)
- [ ] Brief excludes facts/workarounds (lazy-loaded only)
- [ ] Brief is deterministic across sessions when memories haven't changed
- [ ] Judgment framework documents explicit mid-session search triggers
- [ ] Agent visibly searches memories during work (not just at session start) in real usage
