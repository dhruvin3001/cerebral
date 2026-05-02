# Async Saves + Typed Memories — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Add async saves (non-blocking) and typed memories to cerebral.

**Architecture:** Async saves wrap the blocking `mem0.add()` call in a background thread via `asyncio.create_task` + `run_in_executor`, returning immediately to the agent. Typed memories add a `cerebral_type` metadata field to every `save_memory` call, stored in Qdrant payload, and used to structure the `load_context` brief into three priority tiers: Critical → Behavioral → Reference.

**Memory types** (defined as `MEMORY_TYPES` constant in `main.py`, invalid values silently default to `"fact"`):

| Type | When to use |
|------|-------------|
| `warning` | External hazards, known traps, "never do X" |
| `correction` | Agent was explicitly wrong — user reversed a belief |
| `preference` | User's style/approach choices |
| `pattern` | Recurring conventions in this codebase |
| `fact` | Technical truths, API behaviors, project context |
| `decision` | Architectural choices with reasoning |
| `workaround` | Non-obvious fixes for specific bugs/quirks |

**Brief priority tiers:**
1. **Critical** — `warning` + `correction` (things that cause mistakes, always read)
2. **Behavioral** — `preference` + `pattern` (how to work)
3. **Reference** — `fact` + `decision` + `workaround` (look up as needed)

**Tech Stack:** Python asyncio, ThreadPoolExecutor, mem0 `metadata=` param, Qdrant payload filters, pytest-asyncio

**Baseline:** 13 tests passing. All tests are in `tests/` and run with `uv run pytest`.

---

## All tasks are SERIAL — each depends on the previous.

---

### Task 1: Async save infrastructure

**Files:**
- Modify: `main.py`
- Create: `tests/test_async.py`

**Context:** `mem0.add()` calls Ollama for fact extraction (~2–5s). We need to fire it in a background thread so the MCP tool returns immediately. We'll add a `_schedule_save` helper that wraps any blocking function in a background asyncio task.

---

**Step 1: Write the failing test**

Create `tests/test_async.py`:

```python
import asyncio
import time
import pytest
from main import _schedule_save


@pytest.mark.asyncio
async def test_schedule_save_returns_before_completion():
    completed = []

    def slow_fn():
        time.sleep(0.3)
        completed.append(True)

    task = await _schedule_save(slow_fn)
    assert not completed          # function hasn't finished yet
    await task
    assert completed              # now it has


@pytest.mark.asyncio
async def test_schedule_save_handles_exception_silently():
    def failing_fn():
        raise RuntimeError("simulated save failure")

    task = await _schedule_save(failing_fn)
    await task                   # should not raise
```

**Step 2: Run to verify it fails**

```bash
cd /Users/dhruvin07/agent-ws/cerebral && uv run pytest tests/test_async.py -v
```

Expected: `ImportError: cannot import name '_schedule_save' from 'main'`

---

**Step 3: Implement `_schedule_save` in `main.py`**

Add after the `logging.basicConfig` line and before the `@dataclass`:

```python
import asyncio
import threading

async def _run_in_background(fn, *args):
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, fn, *args)
    except Exception as e:
        logging.error(f"Background save failed: {e}")


async def _schedule_save(fn, *args) -> asyncio.Task:
    """Fire a blocking save function in a thread pool. Returns immediately."""
    return asyncio.create_task(_run_in_background(fn, *args))
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_async.py -v
```

Expected: `2 passed`

**Step 5: Commit**

```bash
git add main.py tests/test_async.py
git commit -m "feat: add _schedule_save helper for non-blocking mem0 writes"
```

---

### Task 2: Make save_memory and save_session_learnings non-blocking

**Files:**
- Modify: `main.py` (MCP tool wrappers only — `_do_*` functions stay synchronous)

**Context:** Only the MCP tool wrappers change. The `_do_save_memory` and `_do_save_session_learnings` core functions stay synchronous — that's what the existing tests use.

---

**Step 1: Write the failing test**

Add to `tests/test_async.py`:

```python
import time
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_save_memory_tool_returns_before_ollama():
    """MCP save_memory tool must return before mem0.add() completes."""
    save_times = []

    def slow_add(*a, **kw):
        time.sleep(0.5)
        save_times.append(time.time())

    mock_mem0 = MagicMock()
    mock_mem0.add.side_effect = slow_add

    with patch("main._do_save_memory", wraps=lambda *a, **kw: slow_add()):
        start = time.time()
        result = await _call_save_memory_tool(mock_mem0, "test-project", "some fact", "global", "fact")
        elapsed = time.time() - start

    assert elapsed < 0.2        # returned in <200ms despite 500ms save
    assert "queued" in result.lower()
```

Add the helper at the top of `tests/test_async.py`:

```python
from main import _schedule_save, _do_save_memory, _do_save_session_learnings


async def _call_save_memory_tool(mem0, project_id, text, scope, cerebral_type):
    """Simulate what the MCP save_memory tool does."""
    await _schedule_save(_do_save_memory, mem0, project_id, text, scope, cerebral_type)
    return f"Queued to {scope} memory."
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_async.py::test_save_memory_tool_returns_before_ollama -v
```

Expected: `TypeError: _do_save_memory() takes 4 positional arguments but 5 were given` (no `cerebral_type` param yet — that's Task 3, and that's fine, the test will guide us)

---

**Step 3: Update the MCP tool wrappers in `main.py`**

Replace the two tool wrappers (keep `_do_*` functions unchanged):

```python
@mcp.tool()
async def save_memory(ctx: Context, text: str, scope: str, cerebral_type: str = "fact") -> str:
    """Save a memory. scope: 'global' or 'project'. cerebral_type: warning|correction|preference|pattern|fact|decision|workaround (default: fact)"""
    c = ctx.request_context.lifespan_context
    await _schedule_save(_do_save_memory, c.mem0, c.project_id, text, scope, cerebral_type)
    return f"Queued to {scope} memory ({cerebral_type})."


@mcp.tool()
async def save_session_learnings(ctx: Context, session_summary: str) -> str:
    """Bulk save end-of-session learnings. Pass a freeform summary; mem0 extracts individual facts."""
    c = ctx.request_context.lifespan_context
    await _schedule_save(_do_save_session_learnings, c.mem0, c.project_id, session_summary)
    return "Session learnings queued."
```

**Step 4: Run all tests**

```bash
uv run pytest tests/test_async.py tests/test_main.py -v
```

Expected: async tests pass; `test_main.py` passes unchanged (tests `_do_*` directly, not the MCP wrappers)

**Step 5: Commit**

```bash
git add main.py tests/test_async.py
git commit -m "feat: make save_memory and save_session_learnings non-blocking"
```

---

### Task 3: Add `cerebral_type` to `_do_save_memory`

**Files:**
- Modify: `main.py` (`_do_save_memory` function)
- Modify: `tests/test_main.py`

**Context:** mem0's `add()` accepts a `metadata` dict that gets stored in the Qdrant payload. Pass `metadata={"cerebral_type": cerebral_type}` so every saved memory carries its type. Use `cerebral_type` as the key to avoid collision with mem0's built-in `memory_type` parameter (which only handles "procedural_memory").

---

**Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_save_memory_stores_type(mem0):
    _do_save_memory(mem0, PROJECT_ID, "CRITICAL: never commit .env files", "project", "warning")
    results = _do_search_memories(mem0, PROJECT_ID, ".env files security", "project")
    assert len(results) > 2  # memory was saved and is searchable
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_main.py::test_save_memory_stores_type -v
```

Expected: `TypeError: _do_save_memory() takes 4 positional arguments but 5 were given`

---

**Step 3: Update `_do_save_memory` in `main.py`**

First, add the `MEMORY_TYPES` constant after the `logging.basicConfig` line — this is the single source of truth for valid types:

```python
MEMORY_TYPES = {"warning", "correction", "preference", "pattern", "fact", "decision", "workaround"}
```

Then update `_do_save_memory`:

```python
def _do_save_memory(mem0: Memory, project_id: str, text: str, scope: str, cerebral_type: str = "fact") -> str:
    if cerebral_type not in MEMORY_TYPES:
        cerebral_type = "fact"  # safe default — never crash on unknown type
    user_id = GLOBAL_USER_ID if scope == "global" else project_user_id(project_id)
    mem0.add(
        [{"role": "user", "content": text}],
        user_id=user_id,
        metadata={"cerebral_type": cerebral_type},
    )
    return f"Saved to {scope} memory ({cerebral_type}): {text[:80]}{'...' if len(text) > 80 else ''}"
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_main.py -v
```

Expected: all `test_main.py` tests pass including the new one

**Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: store cerebral_type metadata on every saved memory"
```

---

### Task 4: Prioritize by type in `load_context`

**Files:**
- Modify: `main.py` (`_do_load_context` function)
- Modify: `tests/test_main.py`

**Context:** Currently `load_context` runs one generic semantic search and returns a flat list. With types stored, we can make the brief structured: warnings first (critical, always read), preferences second (behavioral), facts/decisions last (reference). This is the payoff for storing types.

---

**Step 1: Write the failing test**

Add to `tests/test_main.py`:

```python
def test_load_context_sections_by_type(mem0):
    _do_save_memory(mem0, PROJECT_ID, "WARNING: rate limit is 10 req/s on the external API", "project", "warning")
    _do_save_memory(mem0, PROJECT_ID, "User prefers verbose logging in dev mode", "project", "preference")
    result = _do_load_context(mem0, PROJECT_ID)
    assert "Warnings" in result or "warnings" in result.lower()
    assert isinstance(result, str)
    assert len(result) > 10
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_main.py::test_load_context_sections_by_type -v
```

Expected: FAIL — `assert "Warnings" in result` fails (no Warnings section yet)

---

**Step 3: Update `_do_load_context` in `main.py`**

```python
def _do_load_context(mem0: Memory, project_id: str, task_description: str = "") -> str:
    query = task_description or "general preferences corrections patterns warnings"

    def _search_typed(uid, cerebral_type):
        return _extract(mem0.search(
            query,
            filters={"user_id": uid, "cerebral_type": cerebral_type},
            limit=3,
        ))

    def _search_untyped(uid):
        return _extract(mem0.search(query, filters={"user_id": uid}, limit=5))

    def _search_multi(uid, *types):
        results = []
        for t in types:
            results += _search_typed(uid, t)
        return results

    p_uid = project_user_id(project_id)

    # Tier 1 — Critical (things that cause mistakes)
    critical    = _search_multi(GLOBAL_USER_ID, "warning", "correction") + \
                  _search_multi(p_uid, "warning", "correction")

    # Tier 2 — Behavioral (how to work)
    behavioral  = _search_multi(GLOBAL_USER_ID, "preference", "pattern") + \
                  _search_multi(p_uid, "preference", "pattern")

    # Tier 3 — Reference (look up as needed)
    reference   = _search_multi(GLOBAL_USER_ID, "fact", "decision", "workaround") + \
                  _search_multi(p_uid, "fact", "decision", "workaround")

    # Untyped fallback (memories saved before v2)
    untyped     = _search_untyped(GLOBAL_USER_ID) + _search_untyped(p_uid)

    has_typed   = any([critical, behavioral, reference])
    has_untyped = bool(untyped)

    if not has_typed and not has_untyped:
        return "No memories found. This may be a new session or new project."

    lines = ["## Behavioral Brief — Apply These This Session\n"]

    if critical:
        lines.append("### ⚠ Critical (warnings & corrections)")
        lines.extend(f"- {m}" for m in critical)

    if behavioral:
        lines.append("\n### Behavioral (preferences & patterns)")
        lines.extend(f"- {m}" for m in behavioral)

    if reference:
        lines.append("\n### Reference (facts, decisions, workarounds)")
        lines.extend(f"- {m}" for m in reference)

    if not has_typed and has_untyped:
        # Legacy fallback for memories saved before typed memories
        lines.append("\n### Context")
        lines.extend(f"- {m}" for m in untyped)

    return "\n".join(lines)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_main.py -v
```

Expected: all tests pass

**Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: load_context brief now sections by type — warnings first"
```

---

### Task 5: Update judgment framework templates

**Files:**
- Modify: `agents/CLAUDE.md`
- Modify: `agents/AGENTS.md`

**Context:** The templates need to tell the agent which `cerebral_type` to pass for each trigger. This is what makes type storage autonomous — the agent infers the type from the situation, not a separate classification step.

---

**Step 1: No test needed — these are markdown config files**

**Step 2: Update `agents/CLAUDE.md` and `agents/AGENTS.md`**

Replace the "Save immediately" section in both files:

```markdown
**Save immediately (never batch) when:**
- User explicitly reverses something you believed → `forget(old_belief)` first, then `save_memory(correction, scope="global", cerebral_type="correction")`
- User corrects a style/approach preference → `forget(old_preference)` first, then `save_memory(new_preference, scope="global", cerebral_type="preference")`
- User confirms a non-obvious approach worked → `save_memory(confirmation, scope="global", cerebral_type="preference")`
- You notice a recurring convention in this codebase → `save_memory(pattern, scope="project", cerebral_type="pattern")`
- API quirk, trap, or undocumented behavior found → `save_memory(fact, scope="project", cerebral_type="warning")`
- Architectural decision made with reasoning → `save_memory(decision, scope="project", cerebral_type="decision")`
- Non-obvious fix or workaround → `save_memory(fact, scope="project", cerebral_type="workaround")`
- You discovered something surprising about the codebase → `save_memory(fact, scope="project", cerebral_type="fact")`
- You had to look something up you'll likely need again → `save_memory(fact, scope="project", cerebral_type="fact")`
```

**Step 3: Verify files look correct**

```bash
cat /Users/dhruvin07/agent-ws/cerebral/agents/CLAUDE.md
cat /Users/dhruvin07/agent-ws/cerebral/agents/AGENTS.md
```

**Step 4: Commit**

```bash
git add agents/CLAUDE.md agents/AGENTS.md
git commit -m "docs: add cerebral_type annotations to judgment framework triggers"
```

---

### Task 6: Update README and sync to Obsidian vault

**Files:**
- Modify: `README.md`
- Modify: `/Users/dhruvin07/Documents/Obsidian/rr-obsidian-vault/Features/cerebral-improvements.md`

---

**Step 1: Update MCP Tools table in `README.md`**

Replace the `save_memory` row:

```markdown
| `save_memory(text, scope, cerebral_type?)` | Save a memory. `scope`: `"global"` or `"project"`. `cerebral_type`: `warning\|correction\|preference\|pattern\|fact\|decision\|workaround` (default: `"fact"`). Returns immediately — save is queued. |
| `save_session_learnings(summary)` | Bulk-save end-of-session learnings. Returns immediately — save is queued. |
```

**Step 2: Mark improvements 1 and 2 as done in the Obsidian vault**

In `/Users/dhruvin07/Documents/Obsidian/rr-obsidian-vault/Features/cerebral-improvements.md`, update the priority stack:

```markdown
| 1 | ~~Async saves~~ ✅ | Core loop | Done |
| 2 | ~~Typed memories~~ ✅ | Foundation | Done |
```

**Step 3: Run full test suite one final time**

```bash
cd /Users/dhruvin07/agent-ws/cerebral && uv run pytest -v
```

Expected: all tests pass

**Step 4: Commit both repos**

```bash
# cerebral repo
git add README.md docs/
git commit -m "docs: update README for async saves and typed memories"
git push origin main

# Obsidian vault
git -C /Users/dhruvin07/Documents/Obsidian/rr-obsidian-vault add Features/cerebral-improvements.md
git -C /Users/dhruvin07/Documents/Obsidian/rr-obsidian-vault commit -m "chore: mark async saves and typed memories as done"
```
