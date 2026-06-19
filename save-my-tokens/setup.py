#!/usr/bin/env python3
"""Save My Tokens — interactive setup wizard.

Walks the user through connecting their three services (Aura, NAMS, OpenAI),
tests connectivity, and writes .env. No console-hopping needed.

Usage:  python connector/setup.py
"""
import os
import sys
from pathlib import Path


def ask(prompt, default="", secret=False):
    val = ""
    while not val.strip():
        if secret and sys.platform == "win32":
            import msvcrt
            sys.stdout.write(prompt)
            sys.stdout.flush()
            val = ""
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    print()
                    break
                elif ch == "\x08":
                    val = val[:-1]
                else:
                    val += ch
        else:
            val = input(prompt).strip()
        if not val and default:
            val = default
    return val


def test_aura(uri, user, pw, db):
    from neo4j import GraphDatabase
    d = GraphDatabase.driver(uri, auth=(user, pw))
    with d, d.session(database=db) as s:
        r = s.run("RETURN 1 AS ok").single()
        return r and r["ok"] == 1


def test_openai(key):
    from openai import OpenAI
    c = OpenAI(api_key=key)
    c.models.list(limit=1)
    return True


def test_nams(key, ws):
    import requests
    r = requests.get(f"https://memory.neo4jlabs.com/v1/workspaces/{ws}",
                     headers={"Authorization": f"Bearer {key}"}, timeout=15)
    return r.status_code == 200


def main():
    env_file = Path(__file__).resolve().parents[1] / ".env"

    print("Save My Tokens — setup")
    print("=" * 50)
    print()
    print("This wizard connects your three services and writes .env\n")

    # ── Aura ──
    print("── Neo4j Aura ──")
    print("  Create a free instance at https://console.neo4j.io")
    print("  Download the credentials text file or copy from the console.\n")
    uri = ask("  NEO4J_URI: ")
    user = ask("  NEO4J_USERNAME [neo4j]: ", "neo4j")
    pw = ask("  NEO4J_PASSWORD: ", secret=True)
    db = ask("  NEO4J_DATABASE [neo4j]: ", "neo4j")
    print("  Testing Aura connection...", end=" ")
    try:
        test_aura(uri, user, pw, db)
        print("connected ✓\n")
    except Exception as e:
        print(f"FAILED: {e}")
        if "y" not in input("  Continue anyway? [y/N]: ").lower():
            return

    # ── NAMS ──
    print("── NAMS Agent Memory ──")
    print("  Go to https://memory.neo4jlabs.com")
    print("  Create workspace → Settings → choose 'External' database mode")
    print("  Enter your Aura credentials there so NAMS shares your AuraDB.")
    print("  Then Settings → API Keys → create key.\n")
    key = ask("  NAMS_API_KEY [nams_...]: ")
    ws = ask("  NAMS_WORKSPACE_ID: ")
    print("  Testing NAMS connection...", end=" ")
    try:
        test_nams(key, ws)
        print("connected ✓\n")
    except Exception as e:
        print(f"FAILED: {e}")
        if "y" not in input("  Continue anyway? [y/N]: ").lower():
            return

    # ── OpenAI ──
    print("── OpenAI ──")
    print("  Create a key at https://platform.openai.com/api-keys")
    print("  Used for: text-embedding-3-small (semantic recall) + gpt-4o-mini (concept tags)\n")
    oai = ask("  OPENAI_API_KEY [sk-...]: ")
    print("  Testing OpenAI connection...", end=" ")
    try:
        test_openai(oai)
        print("connected ✓\n")
    except Exception as e:
        print(f"FAILED: {e}")
        print("  (embeddings + concept tagging will be unavailable)\n")

    # ── Write ──
    env_file.write_text(
        f"NEO4J_URI={uri}\n"
        f"NEO4J_USERNAME={user}\n"
        f"NEO4J_PASSWORD={pw}\n"
        f"NEO4J_DATABASE={db}\n"
        f"NAMS_API_KEY={key}\n"
        f"NAMS_WORKSPACE_ID={ws}\n"
        f"OPENAI_API_KEY={oai}\n"
    )
    print(f"✓ .env written ({env_file})")
    print()
    print("Next steps:")
    print("  1. pip install -e .")
    print("  2. Launch Claude Code with .env exported")
    print("  3. /add-folder src/")
    print("  4. Ask: 'how does X work in this codebase?'")


if __name__ == "__main__":
    main()
