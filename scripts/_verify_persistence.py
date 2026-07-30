"""Verify conversation persistence: send msg → restart-required marker
→ send another msg → both should be in SQLite events table.

We can't restart the server from this script, so we just:
  1. Send a message tagged "first" to conv "persist-test"
  2. Send another tagged "second"
  3. Read the events table directly and confirm both are stored

The "restart survival" check is done manually after.
"""
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
DB = Path(r"d:\Projects\cagent-os\data\conversations.db")


def send_msg(conv_id, content):
    url = f"{BASE}/api/v1/conversations/{conv_id}/messages"
    body = json.dumps({"content": content, "user_id": "default", "stream": True}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "X-Principal-Id": "default"},
        method="POST",
    )
    print(f"\n→ POST {url}")
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
    print(f"  ← final_len={len(final)}, first80={final[:80]!r}")
    return final


def read_db(conv_id):
    """Query the events table for this conv_id directly."""
    print(f"\n=== SQLite events for {conv_id} ===")
    with sqlite3.connect(str(DB)) as conn:
        rows = conn.execute(
            "SELECT event_json FROM events WHERE conversation_id = ? ORDER BY id",
            (conv_id,)
        ).fetchall()
    print(f"Total events in DB: {len(rows)}")
    user_msgs = []
    for r in rows:
        evt = json.loads(r[0])
        if evt.get("type") == "user.message":
            user_msgs.append(evt.get("content", "")[:80])
    print(f"User messages in DB: {len(user_msgs)}")
    for i, m in enumerate(user_msgs, 1):
        print(f"  [{i}] {m!r}")
    return user_msgs


def main():
    conv_id = "persist-test-001"
    send_msg(conv_id, "你好,这是第一条测试消息")
    time.sleep(2)
    send_msg(conv_id, "这是第二条消息,用来验证多轮对话持久化")
    time.sleep(1)
    msgs = read_db(conv_id)
    print()
    if len(msgs) >= 2:
        print("✅ PASS: both messages persisted to SQLite")
    else:
        print(f"❌ FAIL: expected >=2 messages, got {len(msgs)}")


if __name__ == "__main__":
    main()
