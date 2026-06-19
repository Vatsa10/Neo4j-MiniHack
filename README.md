# Save My Tokens

**Persistent memory for coding agents — built on Neo4j Aura.**

Coding agents (Claude Code, Cursor, Codex) burn thousands of tokens every new session
re-discovering the same project facts. Save My Tokens gives them a graph-native memory
layer: recall, don't re-read.

> **96% fewer tokens** on real queries against the VSCode codebase (2,227 files, 24k symbols).
> Answer was verified correct — all 8 matched symbols matched source line numbers exactly.

## Architecture

```
target repo  ──► ingest.py ──► AuraDB vertical KG
  (2k+ TS files)  (struct walk        File·Symbol·Concept
                  + gpt-4o-mini)      IMPORTS (traversable dep chains)
                                      MEMBER_OF (class→method containment)

agent turn ──► recall_context(task) ──┐
                  ├─ NAMS vector memory (semantic, scored)
                  ├─ concept-vector index (semantic code)
                  ├─ symbol/keyword matching
                  ├─ graph-ranked merge (multi-signal bonus)
                  └─ read exact code from disk via line ranges
                       ▼
                  compact context ← ~97% fewer tokens than reading files
```

Both Neo4j services share **one AuraDB** (NAMS runs in external-db mode). Memory
(`:Entity`) + code KG (`:File/:Symbol/:Concept`) join on entity name — single Cypher
query, no cross-service orchestration.

## User onboarding (3 steps)

### Step 1: Get your services
- **Neo4j Aura** — create a free instance at [console.neo4j.io](https://console.neo4j.io)
- **NAMS** — create workspace at [memory.neo4jlabs.com](https://memory.neo4jlabs.com).
  **Important:** choose **External** database mode and enter your Aura credentials.
  Then Settings → API Keys → create key.
- **OpenAI** — create a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

### Step 2: Run the setup wizard
```bash
git clone <this-repo> && cd Neo4j-MiniHack
pip install -r save-my-tokens/requirements.txt
python -m save_my_tokens.setup          # interactive — tests connections, writes .env
```

Or copy `.env.example` → `.env` and fill in credentials manually.

### Step 3: Ingest your codebase
```bash
python save-my-tokens/ingest.py src/ --llm --llm-limit 200
python save-my-tokens/embed.py
```

That's it. Register with Claude Code and use:
```bash
claude mcp add save-my-tokens -- python save-my-tokens/server.py
```

### Ingest a repo
```bash
python3 save-my-tokens/ingest.py target-vscode/src --llm --llm-limit 250
python3 save-my-tokens/embed.py
```

### Query
```bash
python3 save-my-tokens/engine.py "how does the file service watch for changes"
```

MCP tools:
- `recall_context(task)` — join NAMS memory + vertical code KG into compact context
- `index_file(path)` — deep-index one file on demand (parse + AuraDB + NAMS summary)
- `remember_fact(name, description, type)` — persist a durable fact to agent memory

## The graph (AuraDB)

| Layer | Nodes | Edges |
|-------|-------|-------|
| Files | 2,227 | — |
| Symbols (class/function/method/interface...) | 24,682 | 23,000 DEFINES + 11,352 MEMBER_OF containment |
| Import resolution to real files | — | 2,736 File→File IMPORTS (traversable) |
| External modules | 10,313 | EXT_IMPORT |
| Concepts (gpt-4o-mini) | 399 | 750 ABOUT edges |
| Concepts embedded (text-embedding-3-small) | 399 | vector index `concept_vec` |
| Agent memory (NAMS) | 5 | Entity nodes |

## Verified token savings (VSCode codebase)

| Query | Cold (read files) | Warm (our context) | Saved |
|-------|-------------------|---------------------|-------|
| "undo and redo stack for edits" | 45,667 | 954 | **97.9%** |
| "file watcher event handling" | 24,509 | 860 | **96.5%** |
| "how does the file service watch for changes" | 42,875 | 1,551 | **96.4%** |

Each warm context includes: recalled memory (NAMS), graph-ranked files with match reasons,
matched symbols (exact line numbers), dependency neighbors, and exact code from disk.

## What's where

| Path | What |
|------|------|
| `save-my-tokens/ingest.py` | Repo → vertical KG (deterministic walk + gpt-4o-mini) |
| `save-my-tokens/embed.py` | Embed Concept nodes → `concept_vec` vector index |
| `save-my-tokens/engine.py` | Hybrid retrieval: NAMS memory + KG slice → compact context |
| `save-my-tokens/server.py` | MCP server (3 tools: recall_context, index_file, remember_fact) |
| `save-my-tokens/DEMO.md` | Judging runbook |
| `save-my-tokens/PROTOCOL.md` | Per-session memory protocol |
| `save-my-tokens/measure/` | Token comparison harness |

## The combine

NAMS and the codebase KG share the **same AuraDB** — one Cypher join connects what the
agent learned (memory) with where the code lives (graph):

```cypher
MATCH (mem:Entity)              // NAMS agent memory
MATCH (c:Concept {name: lower(mem.canonicalName)}) // codebase concept
MATCH (c)<-[:ABOUT]-(f:File)    // files about that concept
RETURN mem.name, f.path
```

No REST round-trip needed. No cross-service glue. One graph, two services, one query.

---

Built for the [Neo4j MiniHack](https://neo4j.com) — combining Aura Document Intelligence + Agent Memory Service.
