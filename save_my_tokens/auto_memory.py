#!/usr/bin/env python3
"""Stop hook — autostores every user/assistant exchange to NAMS so the Memory
Browser grows without the agent manually calling memory_add_messages each turn.

Called by Claude Code's Stop hook in .claude/settings.json (fires after every response).

Reads the last exchange from stdin (JSON with {role,content} fields, one per line).
Stores as messages in the NAMS conversation created by the SessionStart hook.

Environment: NAMS_API_KEY, NAMS_WORKSPACE_ID, NAMS_CONVERSATION_ID (set by SessionStart hook).
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

NAMS = "https://memory.neo4jlabs.com/v1"
CONV_FILE = Path(__file__).resolve().parent / ".nams_conv_id"


def get_or_create_conv():
    """Reuse the conversation created at session start, or create one if missing."""
    if CONV_FILE.exists():
        cid = CONV_FILE.read_text().strip()
        if cid:
            return cid
    key = os.environ.get("NAMS_API_KEY")
    ws = os.environ.get("NAMS_WORKSPACE_ID")
    if not key or not ws:
        return None
    try:
        r = requests.post(f"{NAMS}/conversations",
                          headers={"Authorization": f"Bearer {key}", "X-Workspace-Id": ws},
                          json={"metadata": {"source": "claude-code-stop-hook"}}, timeout=15)
        r.raise_for_status()
        cid = r.json().get("id", "")
        CONV_FILE.write_text(cid)
        return cid
    except Exception:
        return None


def store(messages):
    conv_id = get_or_create_conv()
    if not conv_id:
        return
    key = os.environ.get("NAMS_API_KEY")
    ws = os.environ.get("NAMS_WORKSPACE_ID")
    if not key or not ws:
        return
    try:
        for msg in messages:
            requests.post(f"{NAMS}/conversations/{conv_id}/messages",
                          headers={"Authorization": f"Bearer {key}", "X-Workspace-Id": ws},
                          json={"role": msg["role"], "content": msg["content"]}, timeout=15)
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        # Stop hook delivers the last exchange as JSON lines
        messages = []
        for line in raw.strip().splitlines():
            try:
                msg = json.loads(line)
                role = msg.get("role", "")
                content = msg.get("content", "")
                # ponytail: only store user+assistant, skip system/tool
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})
            except json.JSONDecodeError:
                pass
        if messages:
            store(messages)
    except Exception:
        pass


if __name__ == "__main__":
    main()
