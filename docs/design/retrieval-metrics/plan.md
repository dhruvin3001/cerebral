# Retrieval Metrics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Instrument cerebral so every memory tracks retrieval count and recency, exposed via CLI inspection. Foundation for the feedback loop (Wall 3 fix). No decay/archive yet — that's Phase A.5 after observing real data.

**Architecture:** New `metrics.py` module wraps `qdrant_client` to mutate memory payload metadata directly (bypassing mem0 to avoid LLM re-extraction). Hooked into `search_memories` via the existing `_schedule_save` async pattern so metric updates never block tool responses. New `cli.py inspect` subcommand for human-readable readout.

**Tech Stack:** Python, qdrant-client (already a dep), pytest, mem0 only for reads.

---

## Task 1: `metrics.py` — Qdrant payload mutation helper (SERIAL)

**Files:**
- Create: `/Users/dhruvin07/agent-ws/cerebral/metrics.py`
- Create: `/Users/dhruvin07/agent-ws/cerebral/tests/test_metrics.py`

**Step 1: Write the failing tests**

```python
# tests/test_metrics.py
from datetime import datetime
from unittest.mock import MagicMock, patch
from metrics import bump_retrieval, _build_payload_update


def test_build_payload_update_initializes_count_and_timestamp():
    update = _build_payload_update(existing_metadata=None)
    assert update["metadata"]["retrieval_count"] == 1
    assert "last_retrieved_at" in update["metadata"]
    # Timestamp is ISO-8601 parseable
    datetime.fromisoformat(update["metadata"]["last_retrieved_at"])


def test_build_payload_update_increments_existing_count():
    existing = {"cerebral_type": "preference", "retrieval_count": 5}
    update = _build_payload_update(existing_metadata=existing)
    assert update["metadata"]["retrieval_count"] == 6
    assert update["metadata"]["cerebral_type"] == "preference"


def test_build_payload_update_handles_partial_metadata():
    """Pre-metrics memories may have cerebral_type but no retrieval_count."""
    existing = {"cerebral_type": "warning"}
    update = _build_payload_update(existing_metadata=existing)
    assert update["metadata"]["retrieval_count"] == 1
    assert update["metadata"]["cerebral_type"] == "warning"


def test_bump_retrieval_calls_qdrant_set_payload():
    mock_client = MagicMock()
    mock_client.retrieve.return_value = [
        MagicMock(id="mem-1", payload={"metadata": {"retrieval_count": 2}}),
        MagicMock(id="mem-2", payload={"metadata": None}),
    ]
    bump_retrieval(mock_client, "cerebral", ["mem-1", "mem-2"])
    assert mock_client.set_payload.call_count == 2


def test_bump_retrieval_handles_empty_id_list():
    mock_client = MagicMock()
    bump_retrieval(mock_client, "cerebral", [])
    mock_client.set_payload.assert_not_called()
    mock_client.retrieve.assert_not_called()


def test_bump_retrieval_swallows_exceptions():
    """A metric update failure must never break the calling search."""
    mock_client = MagicMock()
    mock_client.retrieve.side_effect = RuntimeError("qdrant down")
    # Should not raise
    bump_retrieval(mock_client, "cerebral", ["mem-1"])
```

**Step 2: Run tests — verify they fail**

```bash
cd /Users/dhruvin07/agent-ws/cerebral
uv run pytest tests/test_metrics.py -v
```

Expected: `ModuleNotFoundError: No module named 'metrics'`

**Step 3: Implement `metrics.py`**

```python
import logging
from datetime import datetime, timezone

from qdrant_client import QdrantClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_payload_update(existing_metadata: dict | None) -> dict:
    """
    Merge metric fields into existing metadata. Preserves cerebral_type and any
    other fields. Initializes retrieval_count to 1 if absent (covers pre-metrics memories).
    """
    metadata = dict(existing_metadata) if existing_metadata else {}
    metadata["retrieval_count"] = int(metadata.get("retrieval_count", 0)) + 1
    metadata["last_retrieved_at"] = _now_iso()
    return {"metadata": metadata}


def bump_retrieval(client: QdrantClient, collection: str, memory_ids: list[str]) -> None:
    """
    Increment retrieval_count and update last_retrieved_at for each memory id.
    Designed to run in a background task — exceptions are logged, never raised.
    """
    if not memory_ids:
        return
    try:
        points = client.retrieve(
            collection_name=collection,
            ids=memory_ids,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            existing = (point.payload or {}).get("metadata")
            update = _build_payload_update(existing)
            client.set_payload(
                collection_name=collection,
                payload=update,
                points=[point.id],
            )
    except Exception as e:
        logging.error(f"bump_retrieval failed: {e}")
```

**Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_metrics.py -v
```

Expected: 6 passed.

**Step 5: Commit**

```bash
git add metrics.py tests/test_metrics.py
git commit -m "feat: metrics.py — qdrant payload mutation for retrieval counts

New module that bypasses mem0 to update memory metadata directly via
qdrant_client. Avoids re-running LLM extraction on every metric write.
Idempotent merge — preserves cerebral_type and other existing fields."
```

---

## Task 2: Hook `search_memories` to bump retrieval counts (SERIAL after Task 1)

**Files:**
- Modify: `/Users/dhruvin07/agent-ws/cerebral/main.py` — `_do_search_memories`, plus async hook in `search_memories` MCP tool
- Modify: `/Users/dhruvin07/agent-ws/cerebral/memory.py` — expose qdrant client so metrics module can use it
- Test: `/Users/dhruvin07/agent-ws/cerebral/tests/test_metrics_hook.py`

**Step 1: Expose Qdrant client from `memory.py`**

Add to `memory.py`:

```python
from qdrant_client import QdrantClient

_qdrant: QdrantClient | None = None
QDRANT_COLLECTION = "cerebral"


def get_qdrant_client() -> QdrantClient:
    global _qdrant
    if _qdrant is None:
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        _qdrant = QdrantClient(url=qdrant_url)
    return _qdrant
```

**Step 2: Modify `_do_search_memories` to return memory IDs alongside text**

Currently `_extract` only returns text. We need IDs for the bump call. Add a sibling:

```python
def _extract_with_ids(results) -> list[dict]:
    """Already exists in main.py — reuse it. Returns [{id, text}, ...]"""
```

(Already defined in `main.py:171` — just reuse.)

Refactor `_do_search_memories` to capture IDs from raw mem0 results, return both the formatted text output AND the list of IDs:

```python
def _do_search_memories(mem0, project_id, query, scope="both") -> tuple[str, list[str]]:
    results = []
    ids = []
    if scope in ("project", "both"):
        raw = mem0.search(query, filters={"user_id": project_user_id(project_id)}, limit=5)
        for m in _extract_with_ids(raw):
            results.append(f"[project] {m['text']}")
            ids.append(m["id"])
    if scope in ("global", "both"):
        raw = mem0.search(query, filters={"user_id": GLOBAL_USER_ID}, limit=5)
        for m in _extract_with_ids(raw):
            results.append(f"[global] {m['text']}")
            ids.append(m["id"])
    text = json.dumps(results, indent=2) if results else "No relevant memories found."
    return text, ids
```

**Step 3: Update the MCP tool wrapper to fire the bump asynchronously**

```python
@mcp.tool()
async def search_memories(ctx: Context, query: str, scope: str = "both") -> str:
    """Search memories by meaning. scope: 'global', 'project', or 'both' (default)."""
    c = ctx.request_context.lifespan_context
    text, ids = _do_search_memories(c.mem0, c.project_id, query, scope)
    if ids:
        from metrics import bump_retrieval
        from memory import get_qdrant_client, QDRANT_COLLECTION
        await _schedule_save(bump_retrieval, get_qdrant_client(), QDRANT_COLLECTION, ids)
    return text
```

**Step 4: Write tests**

```python
# tests/test_metrics_hook.py
import asyncio
from unittest.mock import MagicMock, patch
from main import _do_search_memories


def test_search_memories_returns_ids_alongside_text():
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"id": "id-1", "memory": "first match"},
            {"id": "id-2", "memory": "second match"},
        ]
    }
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "global")
    assert "first match" in text
    assert ids == ["id-1", "id-2"]


def test_search_memories_returns_empty_ids_when_no_results():
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {"results": []}
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "global")
    assert ids == []
    assert "No relevant memories" in text


def test_search_memories_returns_ids_from_both_scopes():
    mock_mem0 = MagicMock()

    def search(query, filters, limit):
        if filters["user_id"].startswith("project:"):
            return {"results": [{"id": "p-1", "memory": "project mem"}]}
        return {"results": [{"id": "g-1", "memory": "global mem"}]}

    mock_mem0.search.side_effect = search
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "both")
    assert set(ids) == {"p-1", "g-1"}
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_metrics_hook.py tests/test_metrics.py -v
```

Expected: all pass.

**Step 6: Run full unit test suite to confirm no regressions**

```bash
uv run pytest tests/test_async.py tests/test_project.py tests/test_load_context.py tests/test_metrics.py tests/test_metrics_hook.py -v
```

Expected: all unit tests still pass.

**Step 7: Commit**

```bash
git add main.py memory.py tests/test_metrics_hook.py
git commit -m "feat: bump retrieval metrics on search_memories

Hook search_memories into metrics.py via the async _schedule_save pattern.
Metric updates run in the background — search responses return immediately.
load_context intentionally untouched (every always-on memory would bump
every session, which is no signal). Only explicit recall counts."
```

---

## Task 3: `cli.py inspect` subcommand (SERIAL after Task 2)

**Files:**
- Modify: `/Users/dhruvin07/agent-ws/cerebral/cli.py`
- Test: `/Users/dhruvin07/agent-ws/cerebral/tests/test_cli_inspect.py`

**Step 1: Write the failing tests**

```python
# tests/test_cli_inspect.py
from unittest.mock import MagicMock, patch
from cli import _format_inspect_table


def test_format_inspect_table_sorts_by_retrieval_count_desc():
    rows = [
        {"id": "a", "memory": "low use", "metadata": {"retrieval_count": 1, "cerebral_type": "fact"}, "user_id": "g"},
        {"id": "b", "memory": "high use", "metadata": {"retrieval_count": 10, "cerebral_type": "warning"}, "user_id": "g"},
        {"id": "c", "memory": "never", "metadata": None, "user_id": "g"},
    ]
    output = _format_inspect_table(rows)
    # high use should come before low use, low use before never
    assert output.index("high use") < output.index("low use") < output.index("never")


def test_format_inspect_table_handles_missing_metadata():
    rows = [{"id": "a", "memory": "untouched", "metadata": None, "user_id": "g"}]
    output = _format_inspect_table(rows)
    assert "untouched" in output
    assert "0" in output  # zero retrieval count


def test_format_inspect_table_truncates_long_memory_text():
    long_text = "x" * 200
    rows = [{"id": "a", "memory": long_text, "metadata": {"retrieval_count": 1}, "user_id": "g"}]
    output = _format_inspect_table(rows)
    assert "x" * 200 not in output  # full text not present
    assert "..." in output  # truncation marker
```

**Step 2: Run — verify failure**

```bash
uv run pytest tests/test_cli_inspect.py -v
```

Expected: `ImportError: cannot import name '_format_inspect_table' from 'cli'`

**Step 3: Implement the subcommand in `cli.py`**

Add to `cli.py`:

```python
def _format_inspect_table(rows: list[dict]) -> str:
    def get_count(r):
        meta = r.get("metadata") or {}
        return int(meta.get("retrieval_count", 0))

    def get_last(r):
        meta = r.get("metadata") or {}
        return meta.get("last_retrieved_at") or "-"

    def get_type(r):
        meta = r.get("metadata") or {}
        return meta.get("cerebral_type", "untyped")

    rows = sorted(rows, key=lambda r: -get_count(r))
    lines = [f"{'count':>5}  {'last_retrieved':<32}  {'type':<12}  scope    text"]
    lines.append("-" * 100)
    for r in rows:
        text = r.get("memory", "")
        if len(text) > 60:
            text = text[:57] + "..."
        scope = "project" if str(r.get("user_id", "")).startswith("project:") else "global"
        lines.append(f"{get_count(r):>5}  {get_last(r):<32}  {get_type(r):<12}  {scope:<7}  {text}")
    return "\n".join(lines)


def _cmd_inspect(args):
    from memory import get_client, GLOBAL_USER_ID, project_user_id
    from project import get_project_id
    mem0 = get_client()
    rows = []
    if args.scope in ("global", "both"):
        results = mem0.get_all(filters={"user_id": GLOBAL_USER_ID})
        rows.extend(results.get("results", []))
    if args.scope in ("project", "both"):
        project_id = get_project_id(os.getcwd())
        results = mem0.get_all(filters={"user_id": project_user_id(project_id)})
        rows.extend(results.get("results", []))
    print(_format_inspect_table(rows))
```

Add subparser registration in `main()`:

```python
inspect_parser = subparsers.add_parser("inspect", help="Show all memories with retrieval metrics")
inspect_parser.add_argument("--scope", choices=["global", "project", "both"], default="both")
```

And dispatch:

```python
elif args.command == "inspect":
    _cmd_inspect(args)
```

**Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_cli_inspect.py -v
```

Expected: 3 passed.

**Step 5: Run end-to-end inspect on real memories**

```bash
uv run cli.py inspect --scope global
```

Expected: human-readable table of your global memories with their counts (most will show 0 since metrics are new).

**Step 6: Commit**

```bash
git add cli.py tests/test_cli_inspect.py
git commit -m "feat: cli.py inspect — sort memories by retrieval count

Surfaces which memories actually get used. Run \`uv run cli.py inspect\`
to see retrieval counts and last-retrieved timestamps per memory. The
foundation for spotting useless memories — automatic archive comes
in Phase A.5 after we observe real distribution."
```

---

## Task 4: End-to-end manual verification + push (SERIAL — last)

**Step 1: Restart MCP server in Claude Code**

In Claude Code: `/mcp` and reconnect cerebral.

**Step 2: Run a few searches to bump counts**

In any session:
- "Search cerebral for pathlib" (triggers `search_memories`)
- "Search cerebral for qdrant" (another)
- "Search cerebral for compaction" (another)

**Step 3: Inspect**

```bash
cd /Users/dhruvin07/agent-ws/cerebral
uv run cli.py inspect --scope global
```

Expected: memories that were searched have `retrieval_count > 0` and a `last_retrieved_at` timestamp.

**Step 4: Verify search response time was not impacted**

Eyeball the search call latency in the agent UI. Should feel identical to before.

**Step 5: Push**

```bash
git push origin main
```

---

## Task Dependency Summary

All SERIAL — each task depends on the prior step.

```
Task 1 (metrics.py)
    → Task 2 (search_memories hook)
        → Task 3 (cli inspect)
            → Task 4 (manual verify + push)
```

## What's NOT in this plan

- Decay / archive logic — Phase A.5 after observing data
- `mark_applied` MCP tool — Phase B
- End-of-session evaluation tool — Phase C
- TUI / dashboard — separate roadmap item
- Updating the Obsidian roadmap — done at end of Task 4 if deemed worth it
