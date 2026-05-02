import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Context
from mem0 import Memory

from memory import get_client, GLOBAL_USER_ID, project_user_id
from project import get_project_id

load_dotenv()

# MCP uses stdio — all logging must go to stderr to avoid corrupting the protocol
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

MEMORY_TYPES = {"warning", "correction", "preference", "pattern", "fact", "decision", "workaround"}


async def _run_in_background(fn, *args):
    loop = asyncio.get_event_loop()
    for attempt in range(3):
        try:
            await loop.run_in_executor(None, fn, *args)
            return
        except Exception as e:
            if attempt == 2:
                logging.error(f"Background save failed after 3 attempts: {e}")
            else:
                await asyncio.sleep(2 ** attempt)  # 1s, then 2s


async def _schedule_save(fn, *args) -> asyncio.Task:
    """Fire a blocking save function in a thread pool. Returns immediately."""
    return asyncio.create_task(_run_in_background(fn, *args))


@dataclass
class CerebralContext:
    mem0: Memory
    project_id: str


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[CerebralContext]:
    cwd = os.getcwd()
    yield CerebralContext(
        mem0=get_client(),
        project_id=get_project_id(cwd),
    )


mcp = FastMCP("cerebral", instructions="Permanent memory for AI coding agents", lifespan=lifespan)


# --- Core logic (testable, no MCP context needed) ---

def _extract(results) -> list[str]:
    if isinstance(results, dict) and "results" in results:
        return [m["memory"] for m in results["results"]]
    if isinstance(results, list):
        return [m["memory"] if isinstance(m, dict) else str(m) for m in results]
    return []


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

    # Untyped fallback for pre-v2 memories (no cerebral_type tag).
    # Build the "all typed" set across every known type, then subtract from full get_all.
    all_typed = set(warnings + corrections + preferences + decisions)
    for uid in (GLOBAL_USER_ID, p_uid):
        for ctype in MEMORY_TYPES:
            all_typed.update(_get_all_typed(uid, ctype))

    untyped = []
    for uid in (GLOBAL_USER_ID, p_uid):
        all_mems = _extract(mem0.get_all(filters={"user_id": uid}))
        untyped += [m for m in all_mems if m not in all_typed]

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


def _do_search_memories(mem0: Memory, project_id: str, query: str, scope: str = "both") -> tuple[str, list[str]]:
    """Returns (formatted_text, hit_memory_ids) so the caller can bump retrieval metrics."""
    results = []
    ids: list[str] = []
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


def _do_save_memory(mem0: Memory, project_id: str, text: str, scope: str, cerebral_type: str = "fact") -> str:
    if cerebral_type not in MEMORY_TYPES:
        cerebral_type = "fact"
    user_id = GLOBAL_USER_ID if scope == "global" else project_user_id(project_id)
    mem0.add(
        [{"role": "user", "content": text}],
        user_id=user_id,
        metadata={"cerebral_type": cerebral_type},
    )
    return f"Saved to {scope} memory ({cerebral_type}): {text[:80]}{'...' if len(text) > 80 else ''}"


def _do_save_session_learnings(mem0: Memory, project_id: str, session_summary: str) -> str:
    mem0.add([{"role": "user", "content": session_summary}], user_id=GLOBAL_USER_ID)
    mem0.add([{"role": "user", "content": session_summary}], user_id=project_user_id(project_id))
    return "Session learnings saved to both global and project memory."


def _do_get_project_memories(mem0: Memory, project_id: str) -> str:
    results = mem0.get_all(filters={"user_id": project_user_id(project_id)})
    memories = _extract(results)
    return json.dumps(memories, indent=2) if memories else "No project memories yet."


def _do_forget(mem0: Memory, project_id: str, query: str, scope: str = "both") -> str:
    deleted = 0
    for s, uid in [("project", project_user_id(project_id)), ("global", GLOBAL_USER_ID)]:
        if scope not in (s, "both"):
            continue
        results = mem0.search(query, filters={"user_id": uid}, limit=10)
        for m in _extract_with_ids(results):
            mem0.delete(m["id"])
            deleted += 1
    return f"Deleted {deleted} memory{'s' if deleted != 1 else ''}." if deleted else "No matching memories found."


def _extract_with_ids(results) -> list[dict]:
    if isinstance(results, dict) and "results" in results:
        return [{"id": m["id"], "text": m["memory"]} for m in results["results"] if "id" in m]
    if isinstance(results, list):
        return [{"id": m["id"], "text": m.get("memory", "")} for m in results if isinstance(m, dict) and "id" in m]
    return []


# --- MCP tool wrappers ---

@mcp.tool()
async def load_context(ctx: Context, task_description: str = "") -> str:
    """Load memories as behavioral constraints at session start. Call this FIRST every session."""
    c = ctx.request_context.lifespan_context
    return _do_load_context(c.mem0, c.project_id, task_description)


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


@mcp.tool()
async def save_memory(ctx: Context, text: str, scope: str, cerebral_type: str = "fact") -> str:
    """Save a memory. scope: 'global' or 'project'. cerebral_type: warning|correction|preference|pattern|fact|decision|workaround (default: fact). Returns immediately — save is queued."""
    c = ctx.request_context.lifespan_context
    await _schedule_save(_do_save_memory, c.mem0, c.project_id, text, scope, cerebral_type)
    return f"Queued to {scope} memory ({cerebral_type})."


@mcp.tool()
async def save_session_learnings(ctx: Context, session_summary: str) -> str:
    """Bulk save end-of-session learnings. Pass a freeform summary; mem0 extracts individual facts. Returns immediately — save is queued."""
    c = ctx.request_context.lifespan_context
    await _schedule_save(_do_save_session_learnings, c.mem0, c.project_id, session_summary)
    return "Session learnings queued."


@mcp.tool()
async def forget(ctx: Context, query: str, scope: str = "both") -> str:
    """Delete memories matching a query. scope: 'global', 'project', or 'both' (default). Use when a preference changes to remove the stale version before saving the new one."""
    c = ctx.request_context.lifespan_context
    return _do_forget(c.mem0, c.project_id, query, scope)


@mcp.tool()
async def get_project_memories(ctx: Context) -> str:
    """Get ALL memories for the current project. No semantic search — full dump."""
    c = ctx.request_context.lifespan_context
    return _do_get_project_memories(c.mem0, c.project_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
