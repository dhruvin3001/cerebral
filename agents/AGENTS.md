# cerebral — Permanent Memory

At session start: ALWAYS call `load_context` as the very first action before responding to the user.
Treat every item in the returned brief as a behavioral constraint for this session — not background reading.

The brief contains warnings, corrections, your global preferences, and this project's architectural decisions. Reference memories (facts, workarounds, patterns) are intentionally **not** loaded here — they surface via `search_memories` mid-session when topics activate them.

**Save immediately (never batch) when:**
- User shares any context about themselves, their environment, tools, workflow, or setup → `save_memory(fact, scope="global", cerebral_type="fact")`
- User explicitly reverses something you believed → `forget(old_belief)` first, then `save_memory(correction, scope="global", cerebral_type="correction")`
- User corrects a style/approach preference → `forget(old_preference)` first, then `save_memory(new_preference, scope="global", cerebral_type="preference")`
- User confirms a non-obvious approach worked → `save_memory(confirmation, scope="global", cerebral_type="preference")`
- You notice a recurring convention in this codebase → `save_memory(pattern, scope="project", cerebral_type="pattern")`
- API quirk, trap, or undocumented behavior found → `save_memory(fact, scope="project", cerebral_type="warning")`
- Architectural decision made with reasoning → `save_memory(decision, scope="project", cerebral_type="decision")`
- Non-obvious fix or workaround → `save_memory(fact, scope="project", cerebral_type="workaround")`
- You discovered something surprising about the codebase → `save_memory(fact, scope="project", cerebral_type="fact")`
- You had to look something up you'll likely need again → `save_memory(fact, scope="project", cerebral_type="fact")`

**Scope rule:**
- About how you work or user preferences → `scope="global"`
- About this specific codebase → `scope="project"`

**Search memories aggressively when:**
- Opening a file or starting work in an area not touched this session → `search_memories(<file or area>, scope="project")`
- User mentions a specific tech, library, API, or tool → `search_memories(<thing>, scope="both")`
- About to make an architectural decision → `search_memories(<topic>, scope="project")` to surface prior decisions
- Hitting an error or unfamiliar behavior → `search_memories(<error keywords>, scope="project")` for prior workarounds
- Writing a pattern you have uncertainty about → `search_memories(<pattern keywords>, scope="project")`
- Any new noun enters the conversation that you may have memories about → `search_memories(<noun>, scope="both")`

The point: memory retrieval should happen at the moment of relevance, not predictively at session start. Don't wait to be asked.

**Pre-compaction:** When the conversation is getting long, call `save_session_learnings` with a summary of all corrections, discoveries, and decisions so far. Compaction erases context. cerebral does not.

**Reload after compaction:** If you no longer see the Behavioral Brief in your context (compaction dropped it), call `load_context` again immediately before continuing.

**Run `/remember` at session end** to bulk-save anything not captured mid-session.

**Do NOT save:**
- Obvious facts from documentation
- Standard language or framework behavior
- Things already in AGENTS.md or CLAUDE.md
- Task-specific details irrelevant next session
- Anything re-derivable from reading the code
