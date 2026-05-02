# cerebral — Permanent Memory

At session start: ALWAYS call `load_context` as the very first action before responding to the user.
Treat every item in the returned brief as a behavioral constraint for this session — not background reading.

**Save immediately (never batch) when:**
- User corrects you → `forget(old_preference)` first, then `save_memory(correction, scope="global")`
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

**Run `/remember` at session end** to bulk-save anything not captured mid-session.

**Do NOT save:**
- Obvious facts from documentation
- Standard language or framework behavior
- Things already in AGENTS.md or CLAUDE.md
- Task-specific details irrelevant next session
- Anything re-derivable from reading the code
