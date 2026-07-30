"""Inspect events table contents."""
import json
import sqlite3
from pathlib import Path

DB = Path(r"d:\Projects\cagent-os\data\conversations.db")
CONV = "persist-test-001"


def main():
    with sqlite3.connect(str(DB)) as conn:
        rows = conn.execute(
            "SELECT event_json FROM events WHERE conversation_id = ? ORDER BY id",
            (CONV,),
        ).fetchall()
    print(f"Total events for {CONV}: {len(rows)}")
    for i, r in enumerate(rows, 1):
        evt = json.loads(r[0])
        content = evt.get("content", "")[:80] if evt.get("content") else ""
        print(f"  [{i:>3}] type={evt.get('type', '?')!r} role={evt.get('role')!r}")
        if content:
            print(f"        content: {content!r}")


if __name__ == "__main__":
    main()
