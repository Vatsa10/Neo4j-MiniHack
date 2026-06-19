#!/usr/bin/env python3
"""Save My Tokens — MCP server. The bridge any coding agent calls each turn.

Tools:
  recall_context(task)  -> compact context joining NAMS memory + Doc-Intel/code KG
                           (same AuraDB), instead of re-reading files. Saves tokens.
  remember_fact(...)    -> persist a durable fact to NAMS agent memory for next session.

Both required services are exercised: recall reads agent memory + the knowledge graph;
remember writes agent memory.

Run (stdio): python connector/mcp_server.py
Register in .mcp.json as the `save-my-tokens` server.
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

import ingest_repo as ir
from context_engine import build_context, NAMS

load_dotenv()
mcp = FastMCP("save-my-tokens")

_driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
)
_DB = os.environ.get("NEO4J_DATABASE", "neo4j")
_REPO = os.environ.get("REPO_ROOT", os.getcwd())


# --- auto-memory: persists exchanges to NAMS without the agent asking ---
_CONV_FILE = Path(__file__).resolve().parent / ".nams_conv_id"


def _get_conv_id():
    if _CONV_FILE.exists():
        return _CONV_FILE.read_text().strip() or None
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not key or not ws:
        return None
    try:
        r = requests.post(f"{NAMS}/conversations",
                          headers={"Authorization": f"Bearer {key}", "X-Workspace-Id": ws},
                          json={"metadata": {"source": "save-my-tokens-mcp"}}, timeout=15)
        r.raise_for_status()
        cid = r.json().get("id", "")
        _CONV_FILE.write_text(cid)
        return cid
    except Exception:
        return None


def _auto_store(task: str, context: str):
    """Store the task+response in NAMS so entities get extracted — fire-and-forget."""
    cid = _get_conv_id()
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not cid or not key or not ws:
        return
    try:
        # API takes one message per call with direct fields, not a "messages" array.
        for role, content in [("user", task), ("assistant", context[:2000])]:
            requests.post(f"{NAMS}/conversations/{cid}/messages",
                          headers={"Authorization": f"Bearer {key}", "X-Workspace-Id": ws},
                          json={"role": role, "content": content}, timeout=10)
    except Exception:
        pass


@mcp.tool()
def recall_context(task: str) -> str:
    """Recall compact, relevant context for a coding task by joining agent memory
    (NAMS) with the codebase/document knowledge graph (Aura) — call this BEFORE
    reading files or grepping, to avoid re-discovering the project and burning tokens.
    Also auto-stores this exchange to NAMS so memory grows without manual steps."""
    with _driver.session(database=_DB) as s:
        warm, st = build_context(task, s)
    footer = (f"\n\n<!-- save-my-tokens: {st.get('files')} KG files, "
              f"~{st.get('warm')} tokens vs ~{st.get('cold')} cold "
              f"({st.get('saved_pct')}% saved) -->")
    # Fire-and-forget: persist this exchange so entity extraction runs
    _auto_store(task, warm)
    return warm + footer


@mcp.tool()
def ingest_folder(path: str, llm: bool = False) -> str:
    """Add an entire folder into the codebase knowledge graph on demand: parse all
    source files, resolve imports to real files (vertical depth), write to AuraDB,
    and optionally tag with concept tags (gpt-4o-mini). Call this when you need to
    make a new codebase available for recall_context. path is absolute or relative
    to cwd (e.g. '~/my-project/src')."""
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"no such folder: {root}"
    from ingest_repo import walk, resolve_imports, write_graph
    records = list(walk(root))
    resolve_imports(records)
    nsym = sum(len(r["defs"]) for r in records)
    nint = sum(len(r["internal_imports"]) for r in records)
    if llm:
        from openai import OpenAI
        from ingest_repo import llm_concepts
        client = OpenAI()
        for r in records:
            r["concepts"] = llm_concepts(r, client)
    write_graph(records, _driver, _DB)
    return (f"ingested {root.name}: {len(records)} files, {nsym} symbols, "
            f"{nint} internal imports" + (f", {sum(1 for r in records if r.get('concepts'))} concepts" if llm else ""))


@mcp.tool()
def index_file(path: str) -> str:
    """Deep-index ONE source file into the knowledge graph on demand: parse its
    classes/functions/methods + resolve its imports to real files (vertical depth),
    write them to AuraDB, and persist a one-line summary to NAMS agent memory.
    Call this when you open/understand a file so the system learns it for next time.
    path is relative to the repo root (e.g. 'vs/base/common/event.ts')."""
    root = Path(_REPO).resolve()
    fp = root / path
    if not fp.exists():
        return f"no such file under {_REPO}: {path}"
    rec = ir.parse_file(fp, root)
    if not rec:
        return f"unsupported file type: {path}"
    with _driver.session(database=_DB) as s:
        known = {r["path"] for r in s.run("MATCH (f:File) RETURN f.path AS path")}
        ir.resolve_imports([rec], known_paths=known)
        ir.write_graph([rec], _driver, _DB)
    # Inject a summary into NAMS so memory recalls this file's role next session.
    classes = [d["name"] for d in rec["defs"] if d["kind"] == "class"][:5]
    summary = (f"{rec['path']}: {len(rec['defs'])} symbols"
               + (f", classes {', '.join(classes)}" if classes else "")
               + f", imports {len(rec['internal_imports'])} files")
    _nams_add(rec["name"], summary, "concept")
    return ("indexed " + rec["path"] + f" — {len(rec['defs'])} symbols, "
            f"{len(rec['internal_imports'])} internal imports; summary written to NAMS")


def _nams_add(name, description, type):
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not key:
        return
    headers = {"Authorization": f"Bearer {key}"}
    if ws:
        headers["X-Workspace-Id"] = ws
    try:
        requests.post(f"{NAMS}/entities", headers=headers,
                      json={"name": name, "type": type, "description": description}, timeout=20)
    except Exception:
        pass


@mcp.tool()
def remember_fact(name: str, description: str, type: str = "concept") -> str:
    """Persist a durable project fact to NAMS agent memory so the next session
    recalls it instead of re-deriving it. type: concept|tool|person|organization|location|custom."""
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not key:
        return "no NAMS_API_KEY set"
    headers = {"Authorization": f"Bearer {key}"}
    if ws:
        headers["X-Workspace-Id"] = ws
    try:
        r = requests.post(f"{NAMS}/entities",
                          headers=headers,
                          json={"name": name, "type": type, "description": description},
                          timeout=20)
        r.raise_for_status()
        return f"remembered: {name} ({r.json().get('resolution', 'ok')})"
    except Exception as e:
        return f"NAMS write failed: {e}"


def main():
    """Entry point for `save-my-tokens` CLI / `uvx save-my-tokens`."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="serve")
    ap.add_argument("--transport", default="stdio")
    args = ap.parse_args()
    if args.cmd == "serve":
        mcp.run(transport=args.transport)
    else:
        print(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
