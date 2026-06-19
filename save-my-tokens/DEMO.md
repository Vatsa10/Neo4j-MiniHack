# Save My Tokens — demo runbook (for judging)

**Pitch:** coding agents re-discover the same project every new session, burning thousands of
tokens. Save My Tokens gives them persistent memory (NAMS) + a repo knowledge graph (Aura
Document Intelligence) so a warm session recalls instead of re-reading. Same task, far fewer tokens.

Both integrations are live in `.mcp.json`: `neo4j` (AuraDB KG) + `nams` (memory).

---

## 0. One-time setup
- `pip install -r save-my-tokens/measure/requirements.txt` (tiktoken — exact counts; script also runs without it).
- Export `.env` + launch Claude Code so `neo4j` and `nams` MCPs connect (`/mcp` to check).

## 1. Cold run — the baseline (no memory)
- Fresh Claude Code session. Give it task **T**:
  > "Add a 4th MCP server entry to `.mcp.json` following this repo's conventions."
- It re-reads `CLAUDE.md`, `.mcp.json`, configs to relearn the env-var / no-secret / no-envFile rules.
- Run `/cost` → record **cold input tokens**.

## 2. Seed the memory + ingest the KG
- **Memory:** run the calls in `seed_memory.md` (ontology + durable facts into NAMS).
- **KG:** open the Aura console Document Intelligence tool
  (https://console.neo4j.io/projects/54f6b9de-d0af-4494-8b99-4f958b4d2697/tools/document-intelligence),
  upload `CLAUDE.md`, `.mcp.json`, `save-my-tokens/PROTOCOL.md` → builds Document→Chunk→Entity in AuraDB.

## 3. Warm run — same task, with memory
- New Claude Code session. Same task **T**.
- Agent follows `PROTOCOL.md`: `memory_get_context("add an MCP server here")` returns the rules in
  a few hundred tokens — no repo re-read.
- Run `/cost` → record **warm input tokens**. Warm < cold = the win.

## 4. Show the graph growing
- NAMS web console (memory.neo4jlabs.com) → the entities/facts added between runs.
- AuraDB Browser → the codebase KG (File / Convention / Decision nodes).

## 5. The bridge (combine the two graphs)
Memory entity and KG file node share a name. Pair the lookups:
- `mcp__nams__memory_get_entity(name=".mcp.json")` — what the user did with it (memory).
- `mcp__neo4j__read_neo4j_cypher("MATCH (f:File {name:'.mcp.json'})-[:MENTIONS]->(e) RETURN e.name")` — what it contains (KG).
- Narrate: "memory knows you were configuring MCP; the KG knows `.mcp.json` defines the servers →
  agent jumps straight there." Vector-only RAG can't do this join.

## 6. Repeatable number
```
python3 save-my-tokens/measure/token_compare.py
```
Current baseline on this repo: **~4,948 → ~151 tokens (≈97% saved)**.
(Approximation; `/cost` from steps 1 & 3 is the real per-session number.)

---

## Talk track (30s)
"Every new agent session relearns your repo — thousands of tokens, every time. We persist the
durable facts in Neo4j agent memory and the repo structure in a Document-Intelligence graph. Next
session, the agent recalls in ~150 tokens instead of re-reading 5 files. 97% less context, same
result — and because both live in graphs, memory and code join on shared entities. That's the demo."
