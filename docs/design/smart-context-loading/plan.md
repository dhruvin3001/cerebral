# Smart Context Loading — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Replace blind semantic-search-based context loading with a two-tier model: deterministic always-on brief at session start, aggressive on-demand retrieval mid-session.

**Architecture:** `_do_load_context` switches from `mem0.search` to `mem0.get_all` filtered by type. Returns ALL warnings + corrections + global preferences + project decisions — no semantic filtering. Judgment framework adds explicit mid-session search triggers and a compaction-recovery rule.

**Tech Stack:** Python, mem0 (`get_all` with filters), pytest

---

## Task 1: Refactor `_do_load_context` to deterministic brief (SERIAL)

**Files:**
- Modify: `/Users/dhruvin07/agent-ws/cerebral/main.py:71-126`
- Test: `/Users/dhruvin07/agent-ws/cerebral/tests/test_load_context.py` (new)

**Step 1: Write the failing tests**

```python
# tests/test_load_context.py
from unittest.mock import MagicMock
from main import _do_load_context, GLOBAL_USER_ID
from memory import project_user_id


def _mk_results(*texts):
    return {"results": [{"memory": t} for t in texts]}


def _mk_mem0(global_by_type=None, project_by_type=None):
    """Build a mock mem0 whose get_all returns memories keyed by (user_id, cerebral_type)."""
    global_by_type = global_by_type or {}
    project_by_type = project_by_type or {}
    p_uid = project_user_id("test-project")

    def get_all(filters=None):
        uid = filters.get("user_id") if filters else None
        ctype = filters.get("cerebral_type") if filters else None
        if uid == GLOBAL_USER_ID:
            return _mk_results(*global_by_type.get(ctype, []))
        if uid == p_uid:
            return _mk_results(*project_by_type.get(ctype, []))
        return _mk_results()

    mock = MagicMock()
    mock.get_all.side_effect = get_all
    return mock


def test_loads_all_warnings_no_limit():
    mem0 = _mk_mem0(
        global_by_type={"warning": [f"warning {i}" for i in range(10)]},
    )
    result = _do_load_context(mem0, "test-project")
    for i in range(10):
        assert f"warning {i}" in result


def test_loads_all_corrections_both_scopes():
    mem0 = _mk_mem0(
        global_by_type={"correction": ["global correction"]},
        project_by_type={"correction": ["project correction"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "global correction" in result
    assert "project correction" in result


def test_loads_global_preferences_not_project_preferences():
    mem0 = _mk_mem0(
        global_by_type={"preference": ["global pref"]},
        project_by_type={"preference": ["project pref - should be excluded"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "global pref" in result
    assert "project pref" not in result


def test_loads_project_decisions_not_global_decisions():
    mem0 = _mk_mem0(
        global_by_type={"decision": ["global decision - excluded"]},
        project_by_type={"decision": ["project decision"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "project decision" in result
    assert "global decision" not in result


def test_excludes_facts_workarounds_patterns_from_brief():
    mem0 = _mk_mem0(
        global_by_type={
            "fact": ["a fact - lazy only"],
            "workaround": ["a workaround - lazy only"],
            "pattern": ["a pattern - lazy only"],
        },
        project_by_type={
            "fact": ["project fact - lazy only"],
            "workaround": ["project workaround - lazy only"],
            "pattern": ["project pattern - lazy only"],
        },
    )
    result = _do_load_context(mem0, "test-project")
    assert "lazy only" not in result


def test_no_memories_returns_empty_brief_message():
    mem0 = _mk_mem0()
    result = _do_load_context(mem0, "test-project")
    assert "No memories found" in result


def test_deduplicates_repeated_memories():
    mem0 = _mk_mem0(
        global_by_type={"warning": ["dup warning", "dup warning", "unique warning"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert result.count("dup warning") == 1
    assert "unique warning" in result


def test_brief_uses_get_all_not_search():
    mem0 = _mk_mem0(global_by_type={"warning": ["w"]})
    _do_load_context(mem0, "test-project")
    mem0.get_all.assert_called()
    mem0.search.assert_not_called()
```

**Step 2: Run tests — verify they fail**

```bash
cd /Users/dhruvin07/agent-ws/cerebral
uv run pytest tests/test_load_context.py -v
```

Expected: failures (current implementation uses `mem0.search`, not `mem0.get_all`).

**Step 3: Replace `_do_load_context` implementation**

Replace lines 71–126 of `main.py` with:

```python
def _do_load_context(mem0: Memory, project_id: str, task_description: str = "") -> str:
    """
    Returns the always-on Behavioral Brief: warnings, corrections, global preferences,
    project decisions. Loaded at session start and after compaction. Reference-type
    memories (facts, workarounds, patterns) are intentionally excluded — those are
    retrieved on-demand mid-session via search_memories.
    """
    p_uid = project_user_id(project_id)

    def _get_all_typed(uid, cerebral_type):
        return _extract(mem0.get_all(filters={"user_id": uid, "cerebral_type": cerebral_type}))

    # Constraints — apply every session, no semantic filtering
    warnings    = _get_all_typed(GLOBAL_USER_ID, "warning")    + _get_all_typed(p_uid, "warning")
    corrections = _get_all_typed(GLOBAL_USER_ID, "correction") + _get_all_typed(p_uid, "correction")
    preferences = _get_all_typed(GLOBAL_USER_ID, "preference")  # global only — about you, not the codebase
    decisions   = _get_all_typed(p_uid, "decision")             # project only — codebase-specific arch

    # Untyped fallback for pre-v2 memories (no cerebral_type tag)
    untyped = []
    for uid in (GLOBAL_USER_ID, p_uid):
        all_mems = _extract(mem0.get_all(filters={"user_id": uid}))
        typed_set = set(warnings + corrections + preferences + decisions)
        untyped += [m for m in all_mems if m not in typed_set]

    has_typed   = any([warnings, corrections, preferences, decisions])
    has_untyped = bool(untyped)

    if not has_typed and not has_untyped:
        return "No memories found. This may be a new session or new project."

    def _dedup(items):
        seen, out = set(), []
        for m in items:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    lines = ["## Behavioral Brief — Apply These This Session\n"]

    critical = _dedup(warnings + corrections)
    if critical:
        lines.append("### ⚠ Critical (warnings & corrections — never repeat)")
        lines.extend(f"- {m}" for m in critical)

    if preferences:
        lines.append("\n### Preferences (how you work)")
        lines.extend(f"- {m}" for m in _dedup(preferences))

    if decisions:
        lines.append("\n### Project Decisions (architectural choices in this codebase)")
        lines.extend(f"- {m}" for m in _dedup(decisions))

    if not has_typed and has_untyped:
        lines.append("\n### Context (legacy untyped memories)")
        lines.extend(f"- {m}" for m in _dedup(untyped))

    lines.append(
        "\n---\n"
        "Reference memories (facts, workarounds, patterns) are not loaded here. "
        "Use `search_memories` mid-session when topics activate them."
    )

    return "\n".join(lines)
```

**Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_load_context.py -v
```

Expected: 8 passed.

**Step 5: Run full unit test suite to confirm no regressions**

```bash
uv run pytest tests/test_async.py tests/test_project.py tests/test_load_context.py -v
```

Expected: all pass.

**Step 6: Commit**

```bash
git add main.py tests/test_load_context.py
git commit -m "feat: deterministic always-on brief in load_context

Switch from semantic search to get_all filtered by type. Brief now contains
ALL warnings, corrections, global preferences, project decisions — no
similarity filtering. Reference-type memories (facts, workarounds, patterns)
intentionally excluded; retrieved on-demand via search_memories instead.

Models how human recall works: constraints are ambient, references are triggered."
```

---

## Task 2: Update judgment framework with mid-session triggers (SERIAL after Task 1)

**Files:**
- Modify: `/Users/dhruvin07/agent-ws/cerebral/agents/CLAUDE.md`
- Modify: `/Users/dhruvin07/agent-ws/cerebral/agents/AGENTS.md`

**Step 1: Update `agents/CLAUDE.md`**

Replace the `**Search before:**` block with this expanded version, and add a `**Reload after compaction:**` block:

```markdown
**Search memories aggressively when:**
- Opening a file or starting work in an area not touched this session → `search_memories(<file or area>, scope="project")`
- User mentions a specific tech, library, API, or tool → `search_memories(<thing>, scope="both")`
- About to make an architectural decision → `search_memories(<topic>, scope="project")` to find prior decisions
- Hitting an error or unfamiliar behavior → `search_memories(<error keywords>, scope="project")` for prior workarounds
- Writing a pattern you have uncertainty about → `search_memories(<pattern keywords>, scope="project")`
- New noun enters the conversation that you may have memories about → `search_memories(<noun>, scope="both")`

**Reload after compaction:**
- If you no longer see the Behavioral Brief in your context (compaction dropped it) → call `load_context` again immediately before continuing.
```

**Step 2: Apply identical change to `agents/AGENTS.md`** (opencode template)

**Step 3: Commit**

```bash
git add agents/CLAUDE.md agents/AGENTS.md
git commit -m "feat: aggressive mid-session search + compaction-reload triggers

Pair the slim always-on brief with explicit triggers for reactive recall.
Memory retrieval should happen at the moment of relevance, not predictively
at session start."
```

---

## Task 3: Sync deployed judgment framework files (SERIAL after Task 2)

These are the user's *active* agent config files, not part of the cerebral repo. Cannot be committed but must be updated for the change to take effect in this user's sessions.

**Files:**
- Modify: `/Users/dhruvin07/.claude/CLAUDE.md`
- Modify: `/Users/dhruvin07/.config/opencode/AGENTS.md`

**Step 1: Update `~/.claude/CLAUDE.md`** — apply the same changes as Task 2.

**Step 2: Update `~/.config/opencode/AGENTS.md`** — apply the same changes as Task 2.

**Step 3: No commit** — these are user config files outside the repo.

---

## Task 4: Update improvement roadmap and ship docs (SERIAL after Task 3)

**Files:**
- Modify: `/Users/dhruvin07/Documents/Obsidian/obs-braindump/cerebral/cerebral-improvements.md`

**Step 1: Mark task-aware loading sections as done (or restructure)**

Update sections 2.1–2.4 to reflect that the v3 redesign covers them via the always-on/on-demand split. Mark completed items with ✅ and the v3 commit reference.

**Step 2: Update the priority stack table**

Move task-aware loading to "done" tier. Surface contradiction detection as next.

**Step 3: No commit** — Obsidian vault, not git-tracked repo.

---

## Task 5: Manual end-to-end verification (SERIAL — last)

**Step 1: Restart MCP server**

In Claude Code: disconnect and reconnect cerebral MCP (or restart Claude Code).

**Step 2: Verify the brief**

In a fresh Claude Code session, the agent should call `load_context` and the returned brief should:
- Contain ALL of your warnings + corrections (count them against `curl localhost:6333/...`)
- Contain global preferences (the rr-vault/braindump fact, pathlib preference, etc.)
- Contain only project decisions for the current repo
- NOT contain facts/workarounds/patterns

**Step 3: Verify mid-session retrieval kicks in**

Mention something specific (e.g., "auth middleware") and confirm the agent calls `search_memories("auth middleware")` reactively.

**Step 4: Push**

```bash
cd /Users/dhruvin07/agent-ws/cerebral
git push origin main
```

---

## Task Dependency Summary

```
Task 1 (refactor + tests) → Task 2 (repo templates) → Task 3 (deployed files) → Task 4 (roadmap docs) → Task 5 (manual verify + push)
```

All SERIAL — each task depends on the prior step's behavior being in place.
