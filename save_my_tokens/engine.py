#!/usr/bin/env python3
"""Save My Tokens — real-time NAMS <-> AuraDB bridge.

Given a task, build a compact context by joining the two graphs:
  - NAMS memory  (REST /v1, nams_ bearer) -> durable facts the agent already learned
  - Codebase KG  (AuraDB, neo4j driver)   -> just the relevant File/Symbol slice

Then compare against the "cold" cost of reading those files in full.

Creds from .env: NEO4J_*, NAMS_API_KEY.
Usage:
  python3 save-my-tokens/engine.py "how does flask handle app config?"
  python3 save-my-tokens/engine.py "..." --repo-root target-repo/src   # for cold-cost sizing
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


def embed_query(task: str):
    """Embed the task for semantic recall. Returns None if no OpenAI key (falls back to keyword)."""
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
        v = OpenAI().embeddings.create(model="text-embedding-3-small", input=task)
        return v.data[0].embedding
    except Exception:
        return None


def nams_memory_kg(kw, session):
    rows = session.run(MEM_QUERY, kw=kw).data()
    return [f"- {r['name']} ({r['type']}): {r['detail'] or ''}".rstrip() for r in rows] or ["(no memory hits)"]


def nams_memory_rest(task: str):
    """Accurate memory recall via NAMS vector search (semantic, scored)."""
    key, ws = os.environ.get("NAMS_API_KEY"), os.environ.get("NAMS_WORKSPACE_ID")
    if not key:
        return None
    try:
        headers = {"Authorization": f"Bearer {key}"}
        if ws:
            headers["X-Workspace-Id"] = ws
        r = requests.post(f"{NAMS}/entities/search", headers=headers,
                          json={"query": task, "limit": 5}, timeout=20)
        r.raise_for_status()
        hits = [e for e in r.json().get("entities", []) if (e.get("score") or 0) >= 0.45]
        return [f"- {e.get('name','')} ({e.get('type','')}): {e.get('description','')}".rstrip()
                for e in hits] or ["(no memory hits)"]
    except Exception:  # ponytail: NAMS REST down -> caller falls back to same-DB Cypher
        return None


# ---- Hybrid KG retrieval: vector(concept) + symbol/keyword, graph-ranked -----
VEC_QUERY = """
CALL db.index.vector.queryNodes('concept_vec', 8, $qvec) YIELD node AS c, score
MATCH (c)<-[:ABOUT]-(f:File)
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
RETURN f.path AS path, f.loc AS loc, collect(DISTINCT s.name)[..8] AS syms,
       collect(DISTINCT c.name) AS reasons, max(score) AS vscore
ORDER BY vscore DESC LIMIT 12
"""
KW_QUERY = """
UNWIND $kw AS kw
MATCH (f:File)
WHERE toLower(f.name) CONTAINS kw
   OR EXISTS { MATCH (f)-[:DEFINES]->(s:Symbol) WHERE toLower(s.name) CONTAINS kw }
   OR EXISTS { MATCH (f)-[:ABOUT]->(c:Concept)  WHERE c.name CONTAINS kw }
OPTIONAL MATCH (f)-[:DEFINES]->(s2:Symbol)
WITH f, collect(DISTINCT s2.name)[..8] AS syms, collect(DISTINCT kw) AS reasons
RETURN f.path AS path, f.loc AS loc, syms, reasons
ORDER BY size(reasons) DESC, f.loc DESC LIMIT 30
"""


def kg_retrieve(kw, qvec, session):
    """Hybrid: semantic concept-vector hits + symbol/keyword hits, merged and
    ranked. Score = semantic similarity + a bonus per independent signal (the
    graph-aware part: a file reachable by both meaning and structure ranks higher)."""
    merged = {}  # path -> record
    if qvec:
        for r in session.run(VEC_QUERY, qvec=qvec):
            d = r.data()
            merged[d["path"]] = {**d, "score": d["vscore"], "signals": 1}
    for r in session.run(KW_QUERY, kw=kw):
        d = r.data()
        m = merged.get(d["path"])
        if m:
            m["signals"] += 1
            m["reasons"] = list(dict.fromkeys(m["reasons"] + d["reasons"]))
        else:
            merged[d["path"]] = {**d, "score": 0.5, "signals": 1}
    ranked = sorted(merged.values(), key=lambda x: x["score"] + 0.15 * x["signals"], reverse=True)
    return ranked[:6]


# Per-file vertical detail: matched symbols with exact line ranges + dependency neighbors.
DETAIL_QUERY = """
UNWIND $paths AS p
MATCH (f:File {path: p})
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
  WHERE any(k IN $kw WHERE toLower(s.name) CONTAINS k)
WITH f, [x IN collect(DISTINCT {name:s.name, kind:s.kind, line:s.line, endline:s.endline})
         WHERE x.name IS NOT NULL][..4] AS matched
OPTIONAL MATCH (f)-[:IMPORTS]->(dep:File)
RETURN f.path AS path, f.loc AS loc, matched, collect(DISTINCT dep.path)[..6] AS deps
"""


def read_code(repo_root, path, line, endline, max_lines=45):
    """Read the exact source for a symbol from disk (KG stores only line ranges)."""
    fp = Path(repo_root) / path
    if not fp.exists():
        return ""
    lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
    end = min(endline or line, line + max_lines)
    return "\n".join(lines[line - 1:end])


def build_context(task: str, session, repo_root="target-vscode/src", rest=True, with_code=True):
    """Join NAMS memory + hybrid KG slice (vertical: matched symbols, exact code,
    dependency neighbors) into one compact context. Returns (warm_text, stats)."""
    kw = keywords(task)
    if not kw:
        return "(no usable keywords in task)", {}
    qvec = embed_query(task)
    mem = nams_memory_rest(task) if rest else None
    if mem is None:
        mem = nams_memory_kg(kw, session)
    files = kg_retrieve(kw, qvec, session)
    paths = [f["path"] for f in files]
    detail = {d["path"]: d for d in (r.data() for r in session.run(DETAIL_QUERY, paths=paths, kw=kw))}
    reasons = {f["path"]: f.get("reasons", []) for f in files}

    lines_out, code_blocks, cold_text, code_budget = [], [], "", 6
    for p in paths:
        d = detail.get(p, {"loc": 0, "matched": [], "deps": []})
        why = "+".join(str(r) for r in reasons.get(p, [])[:3])
        syms = ", ".join(f"{m['name']}:{m['kind']}@{m['line']}" for m in d["matched"]) or "(semantic match)"
        deps = ", ".join(Path(x).name for x in d["deps"][:5])
        lines_out.append(f"- {p} ({d['loc']} loc) [{why}]\n    symbols: {syms}\n    imports: {deps}")
        # exact code for the top matched symbols (vertical depth, read from disk)
        if with_code:
            for m in d["matched"]:
                if code_budget <= 0:
                    break
                code = read_code(repo_root, p, m["line"], m["endline"])
                if code:
                    code_blocks.append(f"### {p} :: {m['name']} ({m['kind']}, L{m['line']})\n```\n{code}\n```")
                    code_budget -= 1
        cand = Path(repo_root) / p
        if cand.exists():
            cold_text += cand.read_text(encoding="utf-8", errors="ignore")

    warm = ("## Recalled memory\n" + "\n".join(mem) +
            "\n\n## Relevant code (graph-ranked, with dependencies)\n" + "\n".join(lines_out))
    if code_blocks:
        warm += "\n\n## Exact code (read from disk via KG line ranges)\n" + "\n\n".join(code_blocks)

    cold, hot = count_tokens(cold_text), count_tokens(warm)
    stats = {"keywords": kw, "files": len(files), "cold": cold, "warm": hot,
             "saved_pct": round(100 * (cold - hot) / cold, 1) if cold else None}
    return warm, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--repo-root", default="target-vscode/src", help="repo on disk for exact-code reads + cold sizing")
    ap.add_argument("--local-mem", action="store_true",
                    help="memory via same-DB substring instead of NAMS vector search")
    args = ap.parse_args()

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    try:
        with driver, driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
            warm, st = build_context(args.task, s, args.repo_root, rest=not args.local_mem)
    except Exception as e:
        sys.exit(f"AuraDB query failed (ingest first?): {e}")

    print(warm)
    print("\n" + "-" * 60)
    print(f"keywords        : {st.get('keywords')}")
    print(f"KG files matched: {st.get('files')}")
    if st.get("cold"):
        print(f"Cold (read files): {st['cold']:>6} tokens")
    print(f"Warm (this ctx)  : {st.get('warm'):>6} tokens")
    if st.get("saved_pct") is not None:
        print(f"Saved           : {st['cold'] - st['warm']:>6} tokens ({st['saved_pct']}%)")


if __name__ == "__main__":
    main()
