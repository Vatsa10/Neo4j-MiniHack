#!/usr/bin/env python3
"""Save My Tokens — cold vs warm token comparison.

Cold  = the files a fresh coding-agent session reads to relearn this repo.
Warm  = what NAMS memory_get_context returns for the same task (a few facts).

The delta is the product. This is the *repeatable approximation*; the real
per-session number is Claude Code's /cost on a cold vs warm run.

# ponytail: tiktoken approximation; exact per-model count comes from /cost.
Run: python3 save-my-tokens/measure/token_compare.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Files a cold agent reads to relearn the repo (the rediscovery tax).
COLD_FILES = [
    "CLAUDE.md",
    ".mcp.json",
    "skills-lock.json",
    "Neo4j-095a9ba9-Created-2026-06-19.txt",
    "save-my-tokens/PROTOCOL.md",
    "save-my-tokens/seed_memory.md",
]

# Warm payload: what memory_get_context returns instead — the durable facts only.
# Paste real get_context output here to measure the true warm number.
WARM_CONTEXT = """\
Project: Neo4j MiniHack — GraphRAG + agent-memory demo on Aura.
Tool: Neo4j MCP runs via `uvx mcp-neo4j-cypher@latest --transport stdio` (no neo4j-mcp binary).
Tool: agent memory = NAMS, `nams` MCP, http, Bearer ${NAMS_API_KEY}.
Convention: Cypher comments use //; never hardcode creds — read .env.
Decision: no envFile in .mcp.json → creds via ${VAR} expansion; .env has no spaces around =.
Files: .mcp.json (neo4j, nams, neo4j-graphacademy); CLAUDE.md (goal + architecture).
"""


def count(text: str) -> int:
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except ImportError:
        # ponytail: no tiktoken → ~4 chars/token heuristic, good enough for the delta.
        return len(text) // 4


def main() -> None:
    cold_text = ""
    for rel in COLD_FILES:
        p = REPO / rel
        if p.exists():
            cold_text += p.read_text(encoding="utf-8", errors="ignore")
        else:
            print(f"  (skip missing: {rel})")

    cold = count(cold_text)
    warm = count(WARM_CONTEXT)
    saved = cold - warm
    pct = 100 * saved / cold if cold else 0

    print(f"\nCold (re-read repo) : {cold:>6} tokens")
    print(f"Warm (memory recall): {warm:>6} tokens")
    print(f"Saved               : {saved:>6} tokens ({pct:.1f}%)\n")

    assert warm < cold, "warm payload should be smaller than cold — premise broken"


if __name__ == "__main__":
    main()
