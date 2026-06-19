# Seed memory — NAMS ontology + durable facts for this repo

Run these MCP calls once to prime NAMS with what a cold agent would otherwise re-derive.
These are `nams` MCP tool calls (Claude executes them), not code.

## 1. Ontology (optional — improves entity readability)

Create a dev-flavoured ontology so entities read as dev concepts, not generic POLE+O:

- `mcp__nams__memory_ontology_create` — entity types: **Project, Tool, Convention, File, Decision, Mistake**.
- `mcp__nams__memory_ontology_activate` — make it the active ontology for the workspace.

Fallback: skip this and use default POLE+O (Tool/Convention/File/Decision all map to **Object**).
Don't block the demo on the custom ontology — it's polish.

## 2. Seed facts (the durable knowledge)

Create one conversation first: `memory_create_conversation(user_id="vatsa")` → keep `conversation_id`.

Then load each as an entity (+ a preference where it's about style):

| Type | Fact |
|------|------|
| Tool | Neo4j MCP runs via `uvx mcp-neo4j-cypher@latest --transport stdio` — there is **no** `neo4j-mcp` binary. |
| Tool | Agent memory = NAMS (hosted, memory.neo4jlabs.com), `nams` MCP, http transport, `Bearer ${NAMS_API_KEY}`. |
| Convention | Cypher comments use `//`, never `--`. |
| Convention | Never hardcode credentials — read from `.env` (gitignored). |
| Decision | Claude Code `.mcp.json` has **no** `envFile` support → creds via `${VAR}` env expansion; export `.env` before launch. |
| Decision | `.env` must have **no spaces** around `=` (`NAME=value`), or `source .env` / parsers break. |
| File | `.mcp.json` — 3 MCP servers: `neo4j`, `nams`, `neo4j-graphacademy`. |
| File | `CLAUDE.md` — project goal + MCP servers + combine architecture. |
| Mistake | Inlining the real password into `.mcp.json` was denied — use `${VAR}` expansion instead. |

Suggested calls per row:
- `memory_add_entity(name="<short name>", type="<Type>", metadata={"detail": "<fact>"})`
- For the two Convention/style rows also: `memory_add_preference(category="coding-style", preference="<fact>")`

## 3. Verify the round-trip
`memory_get_context("how do I add an MCP server to this repo?")` should return the env-var /
no-secret / no-envFile facts in a few hundred tokens — that's the warm payload the demo measures.
