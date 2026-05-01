# cerebral

Permanent memory for AI coding agents. Gives Claude Code and opencode a persistent, self-improving memory that survives session compaction, context resets, and tool restarts — backed by [mem0](https://github.com/mem0ai/mem0), [Ollama](https://ollama.com), and [Qdrant](https://qdrant.tech).

## Why

Every AI coding session starts from zero. Hard-won debugging insights, project-specific patterns, and your preferences — all gone when the context window fills up or you start a new session. cerebral fixes that.

**The self-learning loop:**
1. Agent loads context at session start
2. Saves corrections and discoveries mid-session (autonomous)
3. Bulk-captures everything important before compaction or session end
4. Next session begins with full context

All inference runs locally. No API calls, no token costs, no data leaving your machine.

## Architecture

```
Claude Code / opencode
        │
        │  MCP (stdio)
        ▼
   cerebral (FastMCP server)
        │
        ├── mem0 ──► Ollama (llama3.2:3b) — fact extraction
        │       └──► Ollama (nomic-embed-text) — embeddings
        │
        └──────────► Qdrant (Docker) — vector storage
```

Two memory pools:
- **Global** (`user_id="dhruvin"`) — preferences, corrections, cross-project patterns
- **Project** (`user_id="project:<name>"`) — codebase facts, decisions, API quirks

## Prerequisites

### 1. Docker

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.

### 2. Qdrant

```bash
docker run -d --name qdrant --restart always -p 6333:6333 qdrant/qdrant
```

### 3. Ollama

Install from [ollama.com](https://ollama.com), then pull the required models:

```bash
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 4. uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) — the Python package manager used to run cerebral:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Installation

```bash
git clone https://github.com/dhruvin3001/cerebral
cd cerebral
uv sync
```

## Configuration

### Claude Code

Register cerebral as an MCP server:

```bash
claude mcp add cerebral --scope user -- uv run /path/to/cerebral/main.py
```

Add the judgment framework to `~/.claude/CLAUDE.md`:

```markdown
# cerebral — Permanent Memory

At session start: ALWAYS call `load_context` as the very first action before responding to the user.
Treat every item in the returned brief as a behavioral constraint for this session — not background reading.

**Save immediately (never batch) when:**
- User corrects you → `save_memory(correction, scope="global")`
- User confirms a non-obvious approach worked → `save_memory(confirmation, scope="global")`
- You discover something surprising about the codebase → `save_memory(fact, scope="project")`
- API quirk, workaround, or undocumented behavior found → `save_memory(fact, scope="project")`
- Architectural decision made with reasoning → `save_memory(decision, scope="project")`
- You had to look something up you'll likely need again → `save_memory(fact, scope="project")`

**Scope rule:**
- About how you work or user preferences → `scope="global"`
- About this specific codebase → `scope="project"`

**Search before:**
- Starting work in an area of the codebase not touched this session
- Making an architectural decision
- Writing a pattern you have uncertainty about

**Pre-compaction:** When the conversation is getting long, call `save_session_learnings` with a summary of all corrections, discoveries, and decisions so far. Compaction erases context. cerebral does not.

**Do NOT save:**
- Obvious facts from documentation
- Standard language or framework behavior
- Things already in CLAUDE.md
- Task-specific details irrelevant next session
- Anything re-derivable from reading the code
```

#### Auto-save hook (optional)

Add this to `~/.claude/settings.json` to automatically save session learnings when Claude Code stops:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cd /path/to/cerebral && uv run cli.py save-session",
            "async": true
          }
        ]
      }
    ]
  }
}
```

### opencode

Add cerebral to `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "cerebral": {
      "type": "local",
      "command": ["uv", "run", "/path/to/cerebral/main.py"],
      "enabled": true
    }
  }
}
```

Copy the slash command:

```bash
cp commands/remember.md ~/.config/opencode/commands/remember.md
```

Add the judgment framework to `~/.config/opencode/AGENTS.md` (same content as CLAUDE.md above, with one addition at the end):

```markdown
**Run `/remember` at session end** to bulk-save anything not captured mid-session.
```

## Project detection

cerebral scopes memories to the current project automatically. Detection priority:

1. `CEREBRAL_PROJECT` environment variable (highest priority)
2. `.cerebral` config file anywhere in the directory tree:
   ```json
   { "project_id": "my-project" }
   ```
3. Git remote URL (e.g. `github.com/dhruvin3001/drobe`)
4. Current directory name (fallback)

## MCP Tools

| Tool | Description |
|------|-------------|
| `load_context` | Load all memories for the current project. Call this first at session start. |
| `save_memory(text, scope)` | Save a memory. `scope`: `"global"` or `"project"`. |
| `search_memories(query, scope?)` | Semantic search. `scope`: `"global"`, `"project"`, or `"both"` (default). |
| `save_session_learnings(summary)` | Bulk-save end-of-session learnings to both pools. |
| `forget(query)` | Delete memories matching a query. |

## CLI

The `cli.py` script is used by the auto-save hook:

```bash
# Save a summary directly
uv run cli.py save-session --summary "Learned that mem0 search() requires filters= not user_id="

# Pipe a summary from stdin
echo "session summary" | uv run cli.py save-session

# No-op if no summary provided (used by hook when nothing to save)
uv run cli.py save-session
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CEREBRAL_USER_ID` | `dhruvin` | User ID for global memory pool |
| `CEREBRAL_PROJECT` | auto-detected | Override project name |

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov

# Run a specific test
uv run pytest tests/test_project.py -v
```

## License

MIT
