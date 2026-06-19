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

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from neo4j import GraphDatabase

from context_engine import build_context, NAMS

load_dotenv()
mcp = FastMCP("save-my-tokens")

_driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
)
_DB = os.environ.get("NEO4J_DATABASE", "neo4j")


@mcp.tool()
def recall_context(task: str) -> str:
    """Recall compact, relevant context for a coding task by joining agent memory
    (NAMS) with the codebase/document knowledge graph (Aura) — call this BEFORE
    reading files or grepping, to avoid re-discovering the project and burning tokens."""
    with _driver.session(database=_DB) as s:
        warm, st = build_context(task, s)
    footer = (f"\n\n<!-- save-my-tokens: {st.get('files')} KG files, "
              f"~{st.get('warm')} tokens vs ~{st.get('cold')} cold "
              f"({st.get('saved_pct')}% saved) -->")
    return warm + footer


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


if __name__ == "__main__":
    mcp.run()
