#!/usr/bin/env python3
"""Save My Tokens — real-time NAMS <-> AuraDB bridge.

Given a task, build a compact context by joining the two graphs:
  - NAMS memory  (REST /v1, nams_ bearer) -> durable facts the agent already learned
  - Codebase KG  (AuraDB, neo4j driver)   -> just the relevant File/Symbol slice

Then compare against the "cold" cost of reading those files in full.

Creds from .env: NEO4J_*, NAMS_API_KEY.
Usage:
  python3 connector/context_engine.py "how does flask handle app config?"
  python3 connector/context_engine.py "..." --repo-root target-repo/src   # for cold-cost sizing
"""
import argparse
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

NAMS = "https://memory.neo4jlabs.com/v1"
STOP = {"how", "does", "the", "is", "a", "an", "to", "of", "in", "and", "for", "what", "where", "do", "i"}


def keywords(task: str):
    return [w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task.lower()) if w not in STOP]


def count_tokens(text: str) -> int:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except ImportError:
        return len(text) // 4  # ponytail: heuristic fallback


# ---- NAMS memory side -------------------------------------------------------
# NAMS workspace dbMode=external points at the SAME AuraDB, so memory (:Entity)
# and the code KG share one graph — query memory over Bolt, no REST round-trip.
# ponytail: REST fallback kept for hosted-internal-DB workspaces (--rest).
MEM_QUERY = """
UNWIND $kw AS kw
MATCH (e:Entity)
WHERE toLower(e.canonicalName) CONTAINS kw OR toLower(e.name) CONTAINS kw
RETURN DISTINCT e.name AS name, e.type AS type, e.description AS detail
LIMIT 6
"""


def nams_memory_kg(kw, session):
    rows = session.run(MEM_QUERY, kw=kw).data()
    return [f"- {r['name']} ({r['type']}): {r['detail'] or ''}".rstrip() for r in rows] or ["(no memory hits)"]


def nams_memory_rest(task: str):
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not key:
        return ["(no NAMS_API_KEY set)"]
    try:
        headers = {"Authorization": f"Bearer {key}"}
        if ws:
            headers["X-Workspace-Id"] = ws
        r = requests.post(f"{NAMS}/entities/search", headers=headers,
                          json={"query": task, "limit": 6}, timeout=20)
        r.raise_for_status()
        return [f"- {e.get('name','')} ({e.get('type','')})" for e in r.json().get("entities", [])] or ["(no memory hits)"]
    except Exception as e:  # ponytail: NAMS down shouldn't break retrieval
        return [f"(NAMS error: {e})"]


# ---- Codebase KG side -------------------------------------------------------
KG_QUERY = """
UNWIND $kw AS kw
MATCH (f:File)
WHERE toLower(f.name) CONTAINS kw
   OR EXISTS { (f)-[:DEFINES]->(:Symbol) WHERE toLower(last(split(f.path,'/'))) CONTAINS kw }
   OR EXISTS { (f)-[:ABOUT]->(c:Concept) WHERE c.name CONTAINS kw }
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
WITH f, collect(DISTINCT s.name)[..8] AS syms
RETURN DISTINCT f.path AS path, f.loc AS loc, syms
ORDER BY loc DESC LIMIT 6
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--repo-root", default="target-repo/src", help="for cold-cost sizing")
    ap.add_argument("--rest", action="store_true", help="fetch memory via NAMS REST instead of same-DB Cypher")
    args = ap.parse_args()

    kw = keywords(args.task)
    if not kw:
        sys.exit("no usable keywords in task")

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver, driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
            mem = nams_memory_rest(args.task) if args.rest else nams_memory_kg(kw, s)
            files = [r.data() for r in s.run(KG_QUERY, kw=kw)]
    except Exception as e:
        sys.exit(f"AuraDB query failed (ingest first?): {e}")

    # Warm context = memory facts + KG slice (names only, no file bodies).
    warm = "## Recalled memory\n" + "\n".join(mem) + "\n\n## Relevant code (from KG)\n" + \
        "\n".join(f"- {f['path']} ({f['loc']} loc) :: {', '.join(f['syms'])}" for f in files)

    # Cold cost = reading those same files in full.
    root = Path(args.repo_root)
    cold_text = ""
    for f in files:
        p = root.parent / f["path"] if not (root / Path(f["path"]).name).exists() else None
        fp = Path(args.repo_root).joinpath(*f["path"].split("/")[-1:])
        # best-effort locate the file under repo-root
        cand = list(Path(args.repo_root).rglob(Path(f["path"]).name))
        if cand:
            cold_text += cand[0].read_text(encoding="utf-8", errors="ignore")

    print(warm)
    print("\n" + "-" * 60)
    cold, hot = count_tokens(cold_text), count_tokens(warm)
    print(f"keywords        : {kw}")
    print(f"KG files matched: {len(files)}")
    if cold:
        print(f"Cold (read files): {cold:>6} tokens")
    print(f"Warm (this ctx)  : {hot:>6} tokens")
    if cold:
        print(f"Saved           : {cold - hot:>6} tokens ({100*(cold-hot)/cold:.1f}%)")


if __name__ == "__main__":
    main()
