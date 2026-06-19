#!/usr/bin/env python3
"""Save My Tokens — ingest a repo into a codebase KG in AuraDB.

Hybrid:
  - Deterministic walk: File / Module / Symbol nodes, IMPORTS / DEFINES edges (regex, free).
  - LLM layer (gpt-4o-mini, optional --llm): per-file Concept entities + ABOUT edges.

Graph:
  (:File {path,name,lang,loc}) -[:IMPORTS]->  (:Module {name})
  (:File) -[:DEFINES]-> (:Symbol {key,name})
  (:File) -[:ABOUT]->   (:Concept {name})         # only with --llm

Creds from .env (NEO4J_*). LLM uses OPENAI_API_KEY.
Usage:
  python3 connector/ingest_repo.py target-repo/src --llm --limit 40
  python3 connector/ingest_repo.py target-repo/src --dry-run      # parse only, no DB
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Lightweight language map + extractors. ponytail: regex, not a full parser —
# upgrade to tree-sitter if cross-language symbol accuracy ever matters.
LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".java": "java"}
IMPORT_RE = {
    "python": re.compile(r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))", re.M),
    "javascript": re.compile(r"""^\s*(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""", re.M),
}
IMPORT_RE["typescript"] = IMPORT_RE["javascript"]
DEFINE_RE = {
    "python": re.compile(r"^\s*(?:def|class)\s+(\w+)", re.M),
    "javascript": re.compile(r"^\s*(?:function\s+(\w+)|(?:export\s+)?(?:const|class)\s+(\w+))", re.M),
}
DEFINE_RE["typescript"] = DEFINE_RE["javascript"]


def parse_file(path: Path, root: Path):
    lang = LANGS.get(path.suffix)
    if not lang:
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    rel = str(path.relative_to(root)).replace("\\", "/")
    imports, defines = set(), set()
    if lang in IMPORT_RE:
        for a, b in IMPORT_RE[lang].findall(text):
            mod = (a or b).strip()
            if mod:
                imports.add(mod)
    if lang in DEFINE_RE:
        for groups in DEFINE_RE[lang].findall(text):
            name = next((g for g in (groups if isinstance(groups, tuple) else (groups,)) if g), None)
            if name:
                defines.add(name)
    return {
        "path": rel, "name": path.name, "lang": lang,
        "loc": text.count("\n") + 1,
        "imports": sorted(imports), "defines": sorted(defines),
        "head": text[:1500],  # for the LLM layer
    }


def walk(root: Path):
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    for p in root.rglob("*"):
        if p.is_file() and not (skip & set(p.parts)):
            rec = parse_file(p, root)
            if rec:
                yield rec


def llm_concepts(rec, client):
    """gpt-4o-mini → up to 3 concept tags for a file. Cheap, capped."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                "Return up to 3 short concept tags (comma-separated, lowercase, no prose) "
                f"for what this code file is about.\nFile: {rec['path']}\n\n{rec['head']}"}],
            max_tokens=40, temperature=0,
        )
        raw = resp.choices[0].message.content or ""
        return [c.strip().lower() for c in raw.split(",") if c.strip()][:3]
    except Exception as e:  # ponytail: one flaky file shouldn't kill the run
        print(f"  (llm skip {rec['path']}: {e})")
        return []


def write_graph(records, driver, database):
    cypher = """
    UNWIND $rows AS row
    MERGE (f:File {path: row.path})
      SET f.name = row.name, f.lang = row.lang, f.loc = row.loc
    WITH f, row
    UNWIND (CASE row.imports WHEN [] THEN [null] ELSE row.imports END) AS imp
      FOREACH (_ IN CASE WHEN imp IS NULL THEN [] ELSE [1] END |
        MERGE (m:Module {name: imp}) MERGE (f)-[:IMPORTS]->(m))
    WITH f, row
    UNWIND (CASE row.defines WHEN [] THEN [null] ELSE row.defines END) AS sym
      FOREACH (_ IN CASE WHEN sym IS NULL THEN [] ELSE [1] END |
        MERGE (s:Symbol {key: row.path + '::' + sym}) SET s.name = sym
        MERGE (f)-[:DEFINES]->(s))
    WITH f, row
    UNWIND (CASE row.concepts WHEN [] THEN [null] ELSE row.concepts END) AS con
      FOREACH (_ IN CASE WHEN con IS NULL THEN [] ELSE [1] END |
        MERGE (c:Concept {name: con}) MERGE (f)-[:ABOUT]->(c))
    """
    with driver.session(database=database) as s:
        s.run(cypher, rows=records)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="repo path to ingest, e.g. target-repo/src")
    ap.add_argument("--llm", action="store_true", help="add gpt-4o-mini concept tags")
    ap.add_argument("--limit", type=int, default=0, help="cap files (0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="parse only, no DB write")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.exit(f"no such path: {root}")

    records = list(walk(root))
    if args.limit:
        records = records[: args.limit]
    print(f"parsed {len(records)} files "
          f"({sum(len(r['defines']) for r in records)} symbols, "
          f"{sum(len(r['imports']) for r in records)} imports)")

    if args.llm and records:
        from openai import OpenAI
        client = OpenAI()
        for r in records:
            r["concepts"] = llm_concepts(r, client)
        print(f"llm tagged {sum(1 for r in records if r.get('concepts'))} files")
    else:
        for r in records:
            r["concepts"] = []

    # drop the heavy head field before sending to Neo4j
    for r in records:
        r.pop("head", None)

    if args.dry_run:
        for r in records[:5]:
            print(" ", r["path"], "| defines:", r["defines"][:5], "| concepts:", r.get("concepts"))
        print("dry-run: nothing written")
        return

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    with driver:
        write_graph(records, driver, os.environ.get("NEO4J_DATABASE", "neo4j"))
    print(f"wrote {len(records)} File nodes to AuraDB")


if __name__ == "__main__":
    main()
