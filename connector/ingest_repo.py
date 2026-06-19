#!/usr/bin/env python3
"""Save My Tokens — ingest a repo into a VERTICAL codebase KG in AuraDB.

Vertical depth (not flat name lists):
  (:File)-[:IMPORTS]->(:File)          imports resolved to real files -> traverse dep chains
  (:File)-[:EXT_IMPORT]->(:Module)     external / unresolved imports
  (:File)-[:DEFINES]->(:Symbol)        Symbol{key,name,kind,line,endline}
  (:Symbol)-[:MEMBER_OF]->(:Symbol)    method -> its class (containment)
  (:File)-[:ABOUT]->(:Concept)         gpt-4o-mini tags (with --llm)

Exact code is NOT stored — Symbol.line/endline let the retriever read the precise
slice from disk. Lean DB, exact code.

Creds from .env (NEO4J_*). LLM uses OPENAI_API_KEY.
Usage:
  python3 connector/ingest_repo.py target-vscode/src
  python3 connector/ingest_repo.py target-vscode/src --llm --llm-limit 300
  python3 connector/ingest_repo.py target-vscode/src --dry-run
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LANGS = {".py": "python", ".js": "javascript", ".ts": "typescript",
         ".jsx": "javascript", ".tsx": "typescript"}
IMPORT_RE = {
    "python": re.compile(r"^\s*(?:from\s+([.\w]+)\s+import|import\s+([.\w]+))", re.M),
    "ecma": re.compile(r"""(?:from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\)|import\(['"]([^'"]+)['"]\))"""),
}
PY_DEF = re.compile(r"^(\s*)(class|def)\s+(\w+)")
TS_DEF = re.compile(
    r"^(\s*)(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?"
    r"(class|function|interface|enum|namespace|const|type)\s+(\w+)")
TS_METHOD = re.compile(
    r"^\s*(?:public|private|protected|static|async|readonly|get|set|\s)*"
    r"([A-Za-z_]\w*)\s*[(<]")
TS_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function",
               "constructor", "super", "this", "new", "await", "typeof", "case"}


def _py_defs(lines):
    out, cstack = [], []  # cstack: [(indent, name)]
    for i, line in enumerate(lines, 1):
        m = PY_DEF.match(line)
        if not m:
            continue
        indent, kw, name = len(m.group(1)), m.group(2), m.group(3)
        while cstack and cstack[-1][0] >= indent:
            cstack.pop()
        parent = cstack[-1][1] if (kw == "def" and cstack) else None
        kind = "class" if kw == "class" else ("method" if parent else "function")
        out.append({"name": name, "kind": kind, "line": i, "parent": parent})
        if kw == "class":
            cstack.append((indent, name))
    return out


def _ts_defs(lines):
    out, depth, cstack = [], 0, []  # cstack: [(brace_depth, name)]
    for i, line in enumerate(lines, 1):
        md = TS_DEF.match(line)
        if md:
            indent, kw, name = md.group(1), md.group(2), md.group(3)
            # drop indented local consts (noise); keep module-level const (services/arrow fns)
            if kw == "const" and indent:
                pass
            else:
                kind = {"function": "function", "const": "const"}.get(kw, kw)
                parent = cstack[-1][1] if cstack else None
                out.append({"name": name, "kind": kind, "line": i,
                            "parent": parent if kw not in ("class", "interface", "namespace") else None})
            if kw in ("class", "interface", "namespace") and "{" in line:
                cstack.append((depth, name))
        elif cstack and depth == cstack[-1][0] + 1:
            mm = TS_METHOD.match(line)
            if mm and mm.group(1) not in TS_KEYWORDS and "(" in line:
                out.append({"name": mm.group(1), "kind": "method", "line": i, "parent": cstack[-1][1]})
        nd = depth + line.count("{") - line.count("}")
        while cstack and nd <= cstack[-1][0]:
            cstack.pop()
        depth = max(nd, 0)
    return out


def parse_file(path: Path, root: Path):
    lang = LANGS.get(path.suffix)
    if not lang:
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    rel = str(path.relative_to(root)).replace("\\", "/")
    if lang == "python":
        imports = [a or b for a, b in IMPORT_RE["python"].findall(text) if (a or b)]
        defs = _py_defs(lines)
    else:
        imports = [a or b or c for a, b, c in IMPORT_RE["ecma"].findall(text) if (a or b or c)]
        defs = _ts_defs(lines)
    # end lines: next def at same-or-shallower position, capped.
    for j, d in enumerate(defs):
        nxt = defs[j + 1]["line"] - 1 if j + 1 < len(defs) else len(lines)
        d["endline"] = min(nxt, d["line"] + 200)
    return {"path": rel, "name": path.name, "lang": lang, "loc": len(lines),
            "imports": sorted(set(imports)), "defs": defs, "head": text[:1500], "concepts": []}


def resolve_imports(records, known_paths=None):
    """Map raw import strings to real File paths (vertical File->File edges).
    Tries: relative to the importing file, and relative to the source root.
    known_paths: extra File paths already in the graph (for single-file indexing)."""
    paths = {r["path"] for r in records} | (known_paths or set())
    exts = ["", ".ts", ".tsx", ".js", ".jsx", ".py", "/index.ts", "/index.js", "/__init__.py"]
    SRC_EXT = re.compile(r"\.(?:js|jsx|ts|tsx)$")  # vscode imports .js but files are .ts

    def try_paths(cands):
        for c in cands:
            c = c.replace("\\", "/")
            for base in (c, SRC_EXT.sub("", c)):  # try as-is, then ext-stripped
                for e in exts:
                    if base + e in paths:
                        return base + e
        return None

    for r in records:
        here = Path(r["path"]).parent
        internal, external = [], []
        for imp in r["imports"]:
            target = None
            if imp.startswith("."):
                # relative (ecma ./ ../) — resolve against the file dir
                target = try_paths([str((here / imp).as_posix())])
            else:
                # bare specifier: vscode uses src-root-absolute paths (vs/base/...);
                # python uses dotted module paths.
                dotted = imp.replace(".", "/")
                target = try_paths([imp, dotted, str((here / imp).as_posix())])
            (internal if target else external).append(target or imp)
        r["internal_imports"] = sorted(set(x for x in internal if x))
        r["external_imports"] = sorted(set(external))


def llm_concepts(rec, client):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content":
                "Return up to 3 short concept tags (comma-separated, lowercase, no prose) "
                f"for what this code file is about.\nFile: {rec['path']}\n\n{rec['head']}"}],
            max_tokens=40, temperature=0)
        return [c.strip().lower() for c in (resp.choices[0].message.content or "").split(",") if c.strip()][:3]
    except Exception as e:
        print(f"  (llm skip {rec['path']}: {e})")
        return []


def walk(root: Path):
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "out", "build"}
    for p in root.rglob("*"):
        if p.is_file() and not (skip & set(p.parts)):
            rec = parse_file(p, root)
            if rec:
                yield rec


# Flat passes — one simple UNWIND each, run in managed (auto-retried) transactions.
# Avoids the giant nested-CALL tx that drops the Aura connection mid-write.
Q_FILES = """UNWIND $rows AS r
  MERGE (f:File {path: r.path}) SET f.name=r.name, f.lang=r.lang, f.loc=r.loc"""
Q_SYMS = """UNWIND $rows AS r
  MATCH (f:File {path: r.path})
  MERGE (s:Symbol {key: r.path+'::'+r.name+'::'+toString(r.line)})
    SET s.name=r.name, s.kind=r.kind, s.line=r.line, s.endline=r.endline
  MERGE (f)-[:DEFINES]->(s)
  FOREACH (_ IN CASE WHEN r.parent IS NULL THEN [] ELSE [1] END |
    MERGE (p:Symbol {key: r.path+'::CLASS::'+r.parent}) ON CREATE SET p.name=r.parent, p.kind='class'
    MERGE (s)-[:MEMBER_OF]->(p))"""
Q_IMP = """UNWIND $rows AS r
  MATCH (f:File {path: r.src}) MERGE (t:File {path: r.dst}) MERGE (f)-[:IMPORTS]->(t)"""
Q_EXT = """UNWIND $rows AS r
  MATCH (f:File {path: r.src}) MERGE (m:Module {name: r.dst}) MERGE (f)-[:EXT_IMPORT]->(m)"""
Q_CON = """UNWIND $rows AS r
  MATCH (f:File {path: r.src}) MERGE (c:Concept {name: r.dst}) MERGE (f)-[:ABOUT]->(c)"""


def _run_batched(session, query, rows, size, label):
    for i in range(0, len(rows), size):
        session.execute_write(lambda tx, b=rows[i:i + size]: tx.run(query, rows=b).consume())
        print(f"  {label}: {min(i + size, len(rows))}/{len(rows)}")


def write_graph(records, driver, database):
    files = [{k: r[k] for k in ("path", "name", "lang", "loc")} for r in records]
    syms = [{"path": r["path"], **d} for r in records for d in r["defs"]]
    imp = [{"src": r["path"], "dst": t} for r in records for t in r["internal_imports"]]
    ext = [{"src": r["path"], "dst": t} for r in records for t in r["external_imports"]]
    con = [{"src": r["path"], "dst": c} for r in records for c in r["concepts"]]
    with driver.session(database=database) as s:
        _run_batched(s, Q_FILES, files, 500, "files")
        _run_batched(s, Q_SYMS, syms, 500, "symbols")
        _run_batched(s, Q_IMP, imp, 1000, "imports")
        _run_batched(s, Q_EXT, ext, 1000, "ext-imports")
        _run_batched(s, Q_CON, con, 1000, "concepts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--llm", action="store_true", help="add gpt-4o-mini concept tags")
    ap.add_argument("--limit", type=int, default=0, help="cap total files (0 = all)")
    ap.add_argument("--llm-limit", type=int, default=0, help="tag only N largest files (0 = all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        sys.exit(f"no such path: {root}")

    records = list(walk(root))
    if args.limit:
        records = records[: args.limit]
    resolve_imports(records)
    nsym = sum(len(r["defs"]) for r in records)
    nint = sum(len(r["internal_imports"]) for r in records)
    print(f"parsed {len(records)} files, {nsym} symbols, "
          f"{nint} internal import edges, "
          f"{sum(len(r['external_imports']) for r in records)} external")

    if args.llm and records:
        from openai import OpenAI
        client = OpenAI()
        targets = sorted(records, key=lambda r: r["loc"], reverse=True)
        targets = targets[: args.llm_limit] if args.llm_limit else targets
        for r in targets:
            r["concepts"] = llm_concepts(r, client)
        print(f"llm tagged {sum(1 for r in records if r['concepts'])} of {len(records)} files")

    if args.dry_run:
        for r in records[:6]:
            kinds = {}
            for d in r["defs"]:
                kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
            print(f"  {r['path']} | {kinds} | imports->{len(r['internal_imports'])} files")
        print("dry-run: nothing written")
        return

    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
    with driver:
        write_graph(records, driver, os.environ.get("NEO4J_DATABASE", "neo4j"))
    print(f"wrote {len(records)} files to AuraDB")


if __name__ == "__main__":
    main()
