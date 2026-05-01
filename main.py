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
    query = task_description or "general preferences corrections patterns"
    global_mems = _extract(mem0.search(query, filters={"user_id": GLOBAL_USER_ID}, limit=5))
    project_mems = _extract(mem0.search(query, filters={"user_id": project_user_id(project_id)}, limit=5))

    if not global_mems and not project_mems:
        return "No memories found. This may be a new session or new project."

    lines = ["## Behavioral Brief — Apply These This Session\n"]
    if global_mems:
        lines.append("### Global Constraints (always apply)")
        lines.extend(f"- {m}" for m in global_mems)
    if project_mems:
        lines.append(f"\n### Project Context ({project_id})")
        lines.extend(f"- {m}" for m in project_mems)
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


def _do_save_memory(mem0: Memory, project_id: str, text: str, scope: str) -> str:
    user_id = GLOBAL_USER_ID if scope == "global" else project_user_id(project_id)
    mem0.add([{"role": "user", "content": text}], user_id=user_id)
    return f"Saved to {scope} memory: {text[:80]}{'...' if len(text) > 80 else ''}"


def _do_save_session_learnings(mem0: Memory, project_id: str, session_summary: str) -> str:
    mem0.add([{"role": "user", "content": session_summary}], user_id=GLOBAL_USER_ID)
    mem0.add([{"role": "user", "content": session_summary}], user_id=project_user_id(project_id))
    return "Session learnings saved to both global and project memory."


def _do_get_project_memories(mem0: Memory, project_id: str) -> str:
    results = mem0.get_all(filters={"user_id": project_user_id(project_id)})
    memories = _extract(results)
    return json.dumps(memories, indent=2) if memories else "No project memories yet."


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
async def save_memory(ctx: Context, text: str, scope: str) -> str:
    """Save a memory. scope: 'global' for preferences/corrections, 'project' for codebase facts."""
    c = ctx.request_context.lifespan_context
    return _do_save_memory(c.mem0, c.project_id, text, scope)


@mcp.tool()
async def save_session_learnings(ctx: Context, session_summary: str) -> str:
    """Bulk save end-of-session learnings. Pass a freeform summary; mem0 extracts individual facts."""
    c = ctx.request_context.lifespan_context
    return _do_save_session_learnings(c.mem0, c.project_id, session_summary)


@mcp.tool()
async def get_project_memories(ctx: Context) -> str:
    """Get ALL memories for the current project. No semantic search — full dump."""
    c = ctx.request_context.lifespan_context
    return _do_get_project_memories(c.mem0, c.project_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
