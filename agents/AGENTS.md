# cerebral — Permanent Memory

At session start: ALWAYS call `load_context` as the very first action before responding to the user.
Treat every item in the returned brief as a behavioral constraint for this session — not background reading.

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

**Search before:**
- Starting work in an area of the codebase not touched this session
- Making an architectural decision
- Writing a pattern you have uncertainty about

**Pre-compaction:** When the conversation is getting long, call `save_session_learnings` with a summary of all corrections, discoveries, and decisions so far. Compaction erases context. cerebral does not.

**Run `/remember` at session end** to bulk-save anything not captured mid-session.

**Do NOT save:**
- Obvious facts from documentation
- Standard language or framework behavior
- Things already in AGENTS.md or CLAUDE.md
- Task-specific details irrelevant next session
- Anything re-derivable from reading the code
