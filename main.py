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
    try:
        await loop.run_in_executor(None, fn, *args)
    except Exception as e:
        logging.error(f"Background save failed: {e}")


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
    query = task_description or "general preferences corrections patterns warnings"
    p_uid = project_user_id(project_id)

    def _search_typed(uid, cerebral_type):
        return _extract(mem0.search(query, filters={"user_id": uid, "cerebral_type": cerebral_type}, limit=3))

    def _search_untyped(uid):
        return _extract(mem0.search(query, filters={"user_id": uid}, limit=5))

    def _search_multi(uid, *types):
        results = []
        for t in types:
            results += _search_typed(uid, t)
        return results

    # Tier 1 — Critical (things that cause mistakes)
    critical   = _search_multi(GLOBAL_USER_ID, "warning", "correction") + \
                 _search_multi(p_uid, "warning", "correction")

    # Tier 2 — Behavioral (how to work)
    behavioral = _search_multi(GLOBAL_USER_ID, "preference", "pattern") + \
                 _search_multi(p_uid, "preference", "pattern")

    # Tier 3 — Reference (look up as needed)
    reference  = _search_multi(GLOBAL_USER_ID, "fact", "decision", "workaround") + \
                 _search_multi(p_uid, "fact", "decision", "workaround")

    # Untyped fallback (memories saved before v2)
    untyped    = _search_untyped(GLOBAL_USER_ID) + _search_untyped(p_uid)

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
        lines.append("\n### Context")
        lines.extend(f"- {m}" for m in untyped)

    return "\n".join(lines)


def _do_search_memories(mem0: Memory, project_id: str, query: str, scope: str = "both") -> str:
    results = []
    if scope in ("project", "both"):
        for m in _extract(mem0.search(query, filters={"user_id": project_user_id(project_id)}, limit=5)):
            results.append(f"[project] {m}")
    if scope in ("global", "both"):
        for m in _extract(mem0.search(query, filters={"user_id": GLOBAL_USER_ID}, limit=5)):
            results.append(f"[global] {m}")
    return json.dumps(results, indent=2) if results else "No relevant memories found."


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
    return _do_search_memories(c.mem0, c.project_id, query, scope)


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
