"""Restart-survival test: send msg → read DB → caller stops/starts server
→ send another msg → verify LLM remembers the first.

This script does NOT restart the server itself. It:
  1. Sends a unique marker message ("RESTART-MARKER-<timestamp>")
  2. Reads DB to confirm it was persisted
  3. Prints "=== STOP & RESTART UVICORN NOW, THEN RUN THIS SCRIPT AGAIN ==="

On second run (with --phase=2):
  4. Sends a follow-up asking "what was my previous message?"
  5. Asserts the LLM's reply mentions the marker
"""
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
DB = Path(r"d:\Projects\cagent-os\data\conversations.db")
CONV_ID = "restart-survival-test"


def send_msg(content):
    url = f"{BASE}/api/v1/conversations/{CONV_ID}/messages"
    body = json.dumps({"content": content, "user_id": "default", "stream": True}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "X-Principal-Id": "default"},
        method="POST",
    )
    print(f"→ POST {url}")
    print(f"  content={content!r}")
    final = ""
    with urllib.request.urlopen(req, timeout=60) as resp:
        buf = b""
        for chunk in iter(lambda: resp.read(1024), b""):
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                for line in raw.decode("utf-8", errors="replace").split("\n"):
                    if line.startswith("data:"):
                        try:
                            payload = json.loads(line[5:].strip())
                            if payload.get("phase") == "final_answer":
                                final = payload.get("answer_chunk", "")
                        except Exception:
                            pass
    print(f"  ← reply (first 200): {final[:200]!r}")
    return final


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "1"
    marker = f"RESTART-MARKER-{int(time.time())}"

    if phase == "1":
        print("=" * 60)
        print("Phase 1: Send a marker message")
        print("=" * 60)
        send_msg(f"请记住这个标记: {marker}")
        time.sleep(1)
        # Verify persisted
        with sqlite3.connect(str(DB)) as conn:
            rows = conn.execute(
                "SELECT event_json FROM events WHERE conversation_id = ? AND event_json LIKE ?",
                (CONV_ID, f"%{marker}%"),
            ).fetchall()
        print(f"\nDB search for '{marker}': {len(rows)} match(es)")
        if rows:
            print(f"✅ Phase 1 PASS — marker persisted to SQLite")
        else:
            print(f"❌ Phase 1 FAIL — marker NOT in DB")
            return 1
        # Save marker for phase 2
        Path("_restart_marker.txt").write_text(marker, encoding="utf-8")
        print(f"\n=== STOP & RESTART UVICORN NOW ===")
        print(f"=== Then run: python {sys.argv[0]} --phase=2 ===")
        return 0

    elif phase == "--phase=2":
        print("=" * 60)
        print("Phase 2: Send follow-up asking about the previous message")
        print("=" * 60)
        marker_file = Path("_restart_marker.txt")
        if not marker_file.exists():
            print("❌ Run phase 1 first")
            return 1
        marker = marker_file.read_text(encoding="utf-8").strip()
        print(f"Expected marker: {marker}\n")

        reply = send_msg("我上一条消息里让你记住的标记是什么?")
        if marker in reply:
            print(f"\n✅ Phase 2 PASS — LLM remembered the marker across restart")
            marker_file.unlink()
            return 0
        else:
            print(f"\n❌ Phase 2 FAIL — marker '{marker}' not in reply")
            return 2


if __name__ == "__main__":
    sys.exit(main())
