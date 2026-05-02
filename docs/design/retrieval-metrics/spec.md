# Per-Memory Retrieval Metrics (Phase A)

**Date:** 2026-05-02
**Status:** Validated

## Context

Cerebral has no feedback loop. There's no way to tell whether the brief actually changed agent behavior, whether a saved memory was ever retrieved again, or whether a memory is signal vs noise. The system can grow indefinitely but cannot get smarter — it has no metric for "useful." Identified as **Wall 3** in the honest assessment of the cerebral roadmap.

## Decision

Phase A — instrument retrieval. Phases B/C (agent-side "applied" signal) deferred until we observe what raw retrieval data actually looks like.

Add two metric fields to memory metadata, increment them on `search_memories` hits (not on `load_context` — see rationale below), and expose introspection via a CLI command. No automatic decay or archive logic yet — that's Phase A.5, after we have data to inform the threshold.

YAGNI: don't design the archive policy without evidence. Ship instrumentation, observe, iterate.

## Requirements

- Every memory carries `retrieval_count` (int) and `last_retrieved_at` (ISO-8601 string) in its metadata
- `search_memories` increments these for every memory in the result set
- `load_context` does NOT increment metrics (rationale: every always-on memory loads every session — a uniform bump conveys no signal)
- New memories from `save_memory` initialize with `retrieval_count=0, last_retrieved_at=null`
- Existing pre-metrics memories with `metadata=None` get lazy-backfilled on first retrieval
- Metric updates run async (background task) — never block search response
- `cli.py inspect` shows memories ranked by retrieval count, scoped optionally

## Constraints

- Use `qdrant_client` directly for metric updates — `mem0.update()` re-runs LLM extraction (expensive, lossy). Bypass mem0 for metric-only mutations.
- mem0 stores user metadata as a nested `metadata` field in the Qdrant payload — metric updates must merge into that nested dict, not overwrite it
- No new dependencies — `qdrant-client` is already in `pyproject.toml`

## Out of Scope (Phase A.5+)

- Automatic archive of zero-retrieval memories
- Confidence formula derived from count + recency
- Decay function
- Agent-side `mark_applied(memory_id)` tool (Phase B)
- End-of-session evaluation tool (Phase C)
- Dashboard / TUI (separate roadmap item)

## Open Questions (deferred to A.5)

- [ ] What's the right retrieval-count threshold to flag a memory as "never used"? Will be informed by actual distribution after a few weeks.
- [ ] Should `load_context` bump a separate `loaded_count` counter just for observability, even though we don't act on it?
- [ ] Decay window — 30 days? 90 days? Same — needs data.

## Success Criteria

- [ ] Searching a memory increments its `retrieval_count` and updates `last_retrieved_at`
- [ ] `load_context` calls leave metrics untouched
- [ ] Search responses are not slowed by metric writes (verified via timing test)
- [ ] Pre-metrics memories with null metadata get backfilled cleanly on first hit
- [ ] `uv run cli.py inspect` prints a readable table of memories sorted by retrieval count
- [ ] All existing tests still pass; new tests cover metric increments, async behavior, backfill

## References

- Honest assessment / Wall 3: `obs-braindump/cerebral/cerebral-improvements.md` (section "The 3 Walls Beyond v3")
- Existing async pattern: `main.py:_schedule_save`
- Qdrant `set_payload` docs: https://qdrant.tech/documentation/concepts/payload/#set-payload
