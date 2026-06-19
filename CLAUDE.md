# CLAUDE.md

Neo4j MiniHack workspace. Building **Save My Tokens** — persistent memory for coding agents (see `save-my-tokens/PROTOCOL.md` for the per-session memory loop, `save-my-tokens/DEMO.md` for the judging runbook).

## Goal

Build a small AI / GraphRAG experiment on Neo4j Aura (cloud). Two required integrations:
- **Document intelligence** — ingest docs into a knowledge graph (chunk → extract entities → Document→Chunk→Entity), then GraphRAG retrieval. Use `neo4j-document-import-skill` + `neo4j-graphrag-skill`.
- **Agent memory** — graph-native agent memory via neo4j-agent-memory (POLE+O model, MemoryClient / NAMS). Use `neo4j-agent-memory-skill`.

Move fast: lean on the MCP servers and `neo4j-*` skills rather than writing from scratch.

## MCP servers (`.mcp.json`)

- `neo4j` (stdio, `uvx mcp-neo4j-cypher`) — query Aura DB. Reads `NEO4J_*` from env; export `.env` before launching Claude Code (no envFile support).
- `neo4j-graphacademy` (http) — GraphAcademy tutor + builder tools (graph_modeler, import_advisor, mock_data_generator, project_builder, query_builder).
- `nams` (http) — hosted Agent Memory Service (memory.neo4jlabs.com). Auth via `Bearer ${NAMS_API_KEY}` (add `NAMS_API_KEY=nams_...` to env before launch). Short-term + long-term (POLE+O) + reasoning memory.

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
