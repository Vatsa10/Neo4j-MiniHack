# CLAUDE.md

Neo4j MiniHack workspace. Building **Save My Tokens** — persistent memory + codebase KG for coding agents.
- `save-my-tokens/PROTOCOL.md` — per-session memory loop · `save-my-tokens/DEMO.md` — judging runbook.
- `connector/ingest_repo.py` — repo→**vertical KG** into AuraDB. Model: `(:File)-[:IMPORTS]->(:File)` (resolved, traversable dep chains), `(:File)-[:DEFINES]->(:Symbol{kind,line,endline})`, `(:Symbol)-[:MEMBER_OF]->(:Symbol)` (method→class containment), `(:File)-[:EXT_IMPORT]->(:Module)`, `(:File)-[:ABOUT]->(:Concept)` (gpt-4o-mini). Exact code NOT stored — line ranges let the retriever read precise slices from disk. Batched flat passes + retries (don't use one giant tx — drops Aura connection). Flags `--llm --llm-limit N`.
- `connector/embed_kg.py` — embeds Concept nodes + `concept_vec` vector index (run after concepts exist).
- `connector/context_engine.py` — bridge with **hybrid retrieval**: NAMS vector memory + (concept-vector + symbol/keyword) graph-ranked files, each with matched symbols (line ranges), dependency neighbors, and **exact code read from disk**.
- `connector/mcp_server.py` — MCP server `save-my-tokens`: `recall_context(task)`, `index_file(path)` (deep-index one file live → AuraDB + NAMS summary), `remember_fact(...)`.
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
- `save-my-tokens` (stdio, `python connector/mcp_server.py`) — the bridge as a tool any agent calls each turn: `recall_context(task)` joins NAMS memory + Doc-Intel/code KG into compact context (call before reading files); `remember_fact(name, description, type)` persists durable facts to NAMS.

## Architecture — combining the two graphs

MCP-only build (no glue code): Claude is the agent, orchestrating two separate graphs per turn.
- **Doc Intelligence KG** lives in your AuraDB (`095a9ba9`), built by the Aura console Document Intelligence tool. Read via `neo4j` MCP (Cypher).
- **Agent memory** lives in NAMS (separate Aura DB), read/written via `nams` MCP.
- **Per turn**: recall user context from `nams` → retrieve doc facts from `neo4j` → answer → write new memory back to `nams`.
- **Bridge**: match entities by name across both graphs ("you asked about Policy X before" [memory] + current clause [docs]).

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
