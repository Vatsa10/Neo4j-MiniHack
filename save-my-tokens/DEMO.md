# Save My Tokens — demo runbook (for judging)

**Pitch:** coding agents re-discover the same project every new session, burning thousands of
tokens. Save My Tokens gives them persistent memory (NAMS) + a repo knowledge graph (Neo4j Aura)
so a warm session recalls instead of re-reading. Same task, far fewer tokens.

Both required integrations are used:
- **Aura Document Intelligence** + our hybrid ingest → codebase knowledge graph in AuraDB.
- **NAMS** (Neo4j Agent Memory Service) → durable facts the agent learned, across sessions.
- `connector/context_engine.py` is the **real-time bridge** that joins both per query.

> **The combine, made literal:** this NAMS workspace runs in `external` db mode pointing at the
> *same* AuraDB. So memory (`:Entity`) and the code KG (`:File/:Concept`) sit in one graph — the
> bridge is a single Cypher join on entity name, no cross-service call. (REST path kept via `--rest`.)

---

## Architecture

```
   target repo ──► connector/ingest_repo.py ─┐         console ──► Aura Document
   (e.g. flask)    (walk + gpt-4o-mini)       │         Intelligence (repo docs)
                                              ▼                 │
                                    ┌──────── AuraDB KG ◄────────┘
                                    │  File·Symbol·Module·Concept · Document·Chunk·Entity
   task query ──► context_engine.py ┤
                  (the bridge)       │
                                    └──────── NAMS memory  (durable facts, POLE+O)
                                              ▼
                                    compact context  ◄── 99% fewer tokens than reading files
```

## 0. Setup (once)
- `pip install -r connector/requirements.txt`
- `.env` holds `NEO4J_*`, `NAMS_API_KEY`, `NAMS_WORKSPACE_ID`. Export before running.

## 1. Generate the graph — hybrid ingest (the "build a graph" step)
```
git clone --depth 1 https://github.com/pallets/flask target-repo      # any repo
python3 connector/ingest_repo.py target-repo/src --llm
```
- Deterministic walk → `File`, `Symbol`, `Module` nodes + `IMPORTS` / `DEFINES` edges (free, scales).
- gpt-4o-mini → `Concept` nodes + `ABOUT` edges (semantic layer).
- Verified on flask: **24 files, 387 symbols, 103 modules, 37 concepts.**
```
python3 connector/embed_kg.py        # embed concepts + build the concept_vec vector index
```

## 1b. Accuracy — hybrid graph retrieval (the differentiator)
Recall is **not** substring matching. For each task the engine:
- **memory**: NAMS *vector* search (semantic, scored) over agent-memory entities.
- **code**: vector search over Concept embeddings → traverse `ABOUT` to files, **unioned** with
  symbol/keyword hits, then **graph-ranked** (similarity + a bonus per independent signal — a file
  reached by *both* meaning and structure ranks higher). Each result shows *why* it matched.
- Example: `"how is configuration loaded at startup"` (no word "config") still ranks
  `flask/config.py` #1 via the `configuration` concept. Substring matching returns nothing.
  "Vector gives similarity; the graph gives understanding."

## 2. Add the Document-Intelligence layer (Aura console)
- Open Document Intelligence:
  https://console.neo4j.io/projects/54f6b9de-d0af-4494-8b99-4f958b4d2697/tools/document-intelligence
- Upload the repo's prose docs (`README`, `docs/`, `CHANGES`) → builds `Document→Chunk→Entity`
  in the **same AuraDB**. Now structure (our ingest) + meaning (Doc-Intel) live in one graph.

## 3. Seed memory (NAMS)
- Run the durable facts in `../save-my-tokens/seed_memory.md`, or let the agent write them as it works
  (`memory_add_entity` / `memory_add_preference`). These survive across sessions.

## 4. The real-time bridge — token proof
```
python3 connector/context_engine.py "how does flask handle app config?"
```
Joins NAMS memory + AuraDB KG slice into a compact context and prints the token comparison.
Verified result:
```
Recalled memory : flask config (concept), Flask (tool)
KG files matched: 4  (app.py, sansio/app.py, config.py, wrappers.py)
Cold (read files): 32400 tokens
Warm (this ctx)  :   171 tokens
Saved            : 32229 tokens (99.5%)
```

## 4b. True real-time — the MCP server (no manual script)
`connector/mcp_server.py` wraps the bridge as an MCP server (registered as `save-my-tokens` in
`.mcp.json`). Any agent — Claude Code, Cursor, Codex — calls it automatically:
- `recall_context(task)` → joins NAMS memory + Doc-Intel/code KG → compact context. Agent calls
  this **before** reading files. Both required services exercised in one call.
- `remember_fact(name, description, type)` → writes a durable fact to **NAMS** for next session.

Add to any agent (Cursor/Codex use the same stdio entry):
```
"save-my-tokens": { "command": "python", "args": ["connector/mcp_server.py"], "env": { ...NEO4J_*, NAMS_* } }
```
Then the agent's instruction is just: "call recall_context before exploring; remember_fact when you learn something durable."

## 5. Live agent proof (real /cost)
- Cold Claude Code session does task T → `/cost`.
- Warm session: agent runs the bridge first (recall + KG slice) → `/cost`. Warm < cold.
- Repeatable approximation: `python3 save-my-tokens/measure/token_compare.py`.

## 6. Show the graphs + the join
- AuraDB Browser: `MATCH (c:Concept)<-[:ABOUT]-(f:File) RETURN c,f LIMIT 50` — the code KG.
- NAMS console (memory.neo4jlabs.com): entities/facts growing between sessions.
- **The bridge**: a NAMS entity ("flask config") and a KG `Concept`/`File` share a name → memory
  knows *what you were doing*, the KG knows *where the code is*. Vector-only RAG can't make that join.

## Reset
```
# code KG only (keeps Doc-Intel + memory):
source .env; cypher-shell -a $NEO4J_URI -u $NEO4J_USERNAME -p $NEO4J_PASSWORD --file connector/reset.cypher
```

---

## Talk track (30s)
"Every new agent session relearns your repo — tens of thousands of tokens, every time. We build a
knowledge graph of the code (deterministic walk + gpt-4o-mini) alongside Aura Document Intelligence,
and we persist what the agent learns in Neo4j Agent Memory. Next session the bridge joins memory +
graph and returns ~170 tokens of exactly-relevant context instead of 32,000 tokens of files. 99%
less context, same answer — and because both are graphs, memory and code join on shared entities."
