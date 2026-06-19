# Save My Tokens — per-session memory protocol

The loop every coding-agent session runs so it stops re-discovering this repo from scratch.
Two graphs, one agent: **NAMS** (`nams` MCP) holds durable facts + reasoning; the **Doc-Intel KG**
in AuraDB (`neo4j` MCP) holds repo structure. Recall before you read; write what you learned.

## The loop

### 1. Session start — recall, don't re-read
- `mcp__nams__memory_create_conversation(user_id=...)` → keep the returned `conversation_id` for the whole session.
- `mcp__nams__memory_get_context("<the user's task>")` and/or `memory_search_entities(query=...)`.
- Use what comes back **instead of** grepping the repo or re-reading `CLAUDE.md`. If memory already
  says "uses uvx for mcp-neo4j-cypher", don't go re-derive it.

### 2. Before exploring code — query the KG slice
- Hit the codebase KG instead of dumping files:
  `mcp__neo4j__read_neo4j_cypher("MATCH (f:File)-[:MENTIONS]->(e) WHERE e.name CONTAINS $t RETURN f.name, e.name", {t:"mcp"})`
- Goal: get the 2–3 relevant file/convention names, then read only those — not 5 whole files.

### 3. Act
Do the task using recalled facts + the retrieved slice.

### 4. On failure — record a reasoning trace
- `mcp__nams__memory_record_step` / `memory_record_tool_call` with what was tried and the outcome.
- Next session, `memory_explain_decision` surfaces it so the same dead end isn't retried.
  (e.g. "`neo4j-mcp` binary doesn't exist → use `uvx mcp-neo4j-cypher`".)

### 5. On learning a durable fact — write it back
- `mcp__nams__memory_add_entity` (Tool / File / Convention / Decision) and/or
  `memory_add_preference` for style, and `memory_add_messages` to log the exchange.
- Durable = true next week, not just this turn. Examples for this repo:
  - Tool: "Neo4j MCP runs via `uvx mcp-neo4j-cypher`, not a `neo4j-mcp` binary."
  - Convention: "Cypher comments use `//`; never hardcode creds — read `.env`."
  - Decision: "No `envFile` in Claude Code `.mcp.json` → creds via `${VAR}` env expansion."

## Why it saves tokens
Cold session = re-read `CLAUDE.md` + skill references + configs to relearn the above (~thousands of
input tokens). Warm session = one `get_context` call returns the same knowledge in a few hundred.
The delta is the product. Measure it: `measure/token_compare.py` (repeatable) + Claude Code `/cost` (real).

## The bridge (combine the two graphs)
A NAMS memory entity and a KG file node share a **name**. Match on it:
"user is configuring MCP" (memory) + `.mcp.json` (KG File node) → agent goes straight to the artifact.
See `DEMO.md` for the paired `memory_get_entity` + `read_neo4j_cypher` lookup.
