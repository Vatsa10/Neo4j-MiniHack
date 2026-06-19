# CLAUDE.md

Neo4j MiniHack workspace. Building **Save My Tokens** — persistent memory + codebase KG for coding agents.
- `save_my_tokens/PROTOCOL.md` — per-session memory loop · `save_my_tokens/DEMO.md` — judging runbook.
- `save_my_tokens/ingest.py` — repo→**vertical KG** into AuraDB. Model: `(:File)-[:IMPORTS]->(:File)` (resolved, traversable dep chains), `(:File)-[:DEFINES]->(:Symbol{kind,line,endline})`, `(:Symbol)-[:MEMBER_OF]->(:Symbol)` (method→class containment), `(:File)-[:EXT_IMPORT]->(:Module)`, `(:File)-[:ABOUT]->(:Concept)` (gpt-4o-mini). Exact code NOT stored — line ranges let the retriever read precise slices from disk. Batched flat passes + retries (don't use one giant tx — drops Aura connection). Flags `--llm --llm-limit N`.
- `save_my_tokens/embed.py` — embeds Concept nodes + `concept_vec` vector index (run after concepts exist).
- `save_my_tokens/engine.py` — bridge with **hybrid retrieval**: NAMS vector memory + (concept-vector + symbol/keyword) graph-ranked files, each with matched symbols (line ranges), dependency neighbors, and **exact code read from disk**.
- `save_my_tokens/server.py` — MCP server `save-my-tokens`: `recall_context(task)` (returns context + auto-stores exchange), `ingest_folder(path, llm=False)` (adds a folder to the KG live), `index_file(path)` (deep-index one file live → AuraDB + NAMS summary), `remember_fact(...)`.
- Slash command `/add-folder <path>` — ingests a folder into the codebase KG (calls `ingest_folder`). Use for real-time context injection.
- Test bed: `target-vscode/` (sparse `src/vs/platform`+`src/vs/base`, ~2227 TS files). `target-repo/` was flask. `REPO_ROOT` env points the server at the on-disk repo for exact-code reads.
- `.env` adds `NAMS_API_KEY`, `NAMS_WORKSPACE_ID`. NAMS REST needs `X-Workspace-Id` header. Pipeline: ingest → (concepts) → embed_kg → recall.
- **Key fact**: this NAMS workspace (`dbMode=external`) points at the SAME AuraDB (`095a9ba9`). Memory (`:Entity`) and the code KG (`:File/:Symbol/:Concept`) share one graph, so the bridge is a single Cypher join on entity name — no REST needed (default). `--rest` forces the REST path.

## Goal

Build a small AI / GraphRAG experiment on Neo4j Aura (cloud). Two required integrations:
- **Document intelligence** — ingest docs into a knowledge graph (chunk → extract entities → Document→Chunk→Entity), then GraphRAG retrieval. Use `neo4j-document-import-skill` + `neo4j-graphrag-skill`.
- **Agent memory** — graph-native agent memory via neo4j-agent-memory (POLE+O model, MemoryClient / NAMS). Use `neo4j-agent-memory-skill`.

Move fast: lean on the MCP servers and `neo4j-*` skills rather than writing from scratch.

## MCP servers (`.mcp.json`)

- `neo4j` (stdio, `uvx mcp-neo4j-cypher`) — query Aura DB. Reads `NEO4J_*` from env; export `.env` before launching Claude Code (no envFile support).
- `neo4j-graphacademy` (http) — GraphAcademy tutor + builder tools (graph_modeler, import_advisor, mock_data_generator, project_builder, query_builder).
- `nams` (http) — hosted Agent Memory Service (memory.neo4jlabs.com). Auth via `Bearer ${NAMS_API_KEY}` (add `NAMS_API_KEY=nams_...` to env before launch). Short-term + long-term (POLE+O) + reasoning memory.
- `save-my-tokens` (stdio, `python save_my_tokens/server.py`) — the bridge as a tool any agent calls each turn: `recall_context(task)` joins NAMS memory + Doc-Intel/code KG into compact context (call before reading files); `remember_fact(name, description, type)` persists durable facts to NAMS.

## Session memory protocol (AUTO — fire-and-forget)

Agent does NOT call `memory_add_messages` manually. It's automatic:

1. **Before each task**: call `recall_context(task)` → returns context + auto-stores the exchange to NAMS as a side effect (creates conversation on first call, appends messages every call). Entity extraction runs async — the Memory Browser grows without the agent thinking about it.
2. **On learning a durable fact**: call `remember_fact(name, description, type)`.
3. **On opening a new file**: call `index_file(path)` — deep-indexes into AuraDB + NAMS.
4. **On failure**: record via `memory_record_step` (reasining memory differentiator).

## Architecture — combining the two graphs

MCP-only build (no glue code): Claude is the agent, orchestrating the graph per turn.
- **Doc Intelligence KG** + **NAMS agent memory** share the **same AuraDB** (`095a9ba9`, dbMode=external). Memory (`:Entity`) and code KG (`:File/:Symbol/:Concept`) are one graph — bridge is a single Cypher join.
- **Per turn**: recall `nams` memory + retrieve `neo4j` KG slice → answer → store exchange back to `nams` (auto).
- **Bridge**: entity name join across memory + code — "you asked about X before" [memory] + current code [KG].

## What's here

- `.env` — Neo4j Aura connection creds (`NEO4J_URI/USERNAME/PASSWORD/DATABASE`, `AURA_*`). Gitignored. Load via python-dotenv.
- `.agents/skills/neo4j-getting-started-skill/` — bundled skill that drives zero-to-app in 8 stages (prerequisites → context → provision → model → load → explore → query → build). Start at `SKILL.md`; each stage reads its own `references/<stage>.md`.
- `skills-lock.json` — pins the skill to `neo4j-contrib/neo4j-skills` with a content hash.
- `Neo4j-095a9ba9-Created-2026-06-19.txt` — Aura instance creation receipt.

## Building the project

Follow the getting-started skill. It writes generated output to the working dir using this layout:
`schema/` (schema.json, schema.cypher, reset.cypher), `data/` (generate.py/import.py + csv), `queries/queries.cypher`, `scripts/`, and root app artifact (`notebook.ipynb` / `app.py` / `main.py`). Tracks state in `progress.md`; resume by finding the first `status: pending` stage.

## Conventions

- Cypher comments use `//`, not `--`.
- Never hardcode credentials — read from `.env`.
- Re-run commands in any generated README use `python3` (portable, not absolute paths).
- Write generated code to files, not just the conversation.
