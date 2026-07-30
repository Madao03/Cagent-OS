"""End-to-end: LLM autonomously uses memory tools across two conversations.

Flow:
  1. Register a fresh user
  2. Tell the LLM something memorable ("I'm a value investor, focus on semis")
     — LLM should autonomously call memory.update_profile or memory.update_notes
  3. Verify via HTTP that the memory was actually written
  4. Start a NEW conversation with same user
  5. Ask "what do you know about my investment style?"
  6. Verify LLM recalls the info (proving memory injection into system prompt works)
"""
import json
import secrets
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cagent_os.auth import InvitationCodeStore

BASE = "http://127.0.0.1:8000"


def register_user(username):
    code = "E2E" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
    InvitationCodeStore(r"d:\Projects\cagent-os\data\invitation_codes.db").add(code=code)
    body = json.dumps({"invitation_code": code, "username": username}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/register", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["token"]


def send_msg(conv_id, content, token):
    """Send a chat message, drain SSE, return final assistant text + tool calls."""
    url = f"{BASE}/api/v1/conversations/{conv_id}/messages"
    body = json.dumps({"content": content, "user_id": "ignored", "stream": True}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }, method="POST",
    )
    final_answer = ""
    tool_calls = []
    with urllib.request.urlopen(req, timeout=90) as resp:
        buf = b""
        for chunk in iter(lambda: resp.read(1024), b""):
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                for line in raw.decode("utf-8", errors="replace").split("\n"):
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    phase = payload.get("phase", "")
                    if phase == "final_answer":
                        final_answer = payload.get("answer_chunk", "")
                    elif phase == "tool_call":
                        tool_calls.append({
                            "tool": payload.get("tool_name"),
                            "status": payload.get("tool_status"),
                        })
    return final_answer, tool_calls


def http_get(path, token):
    req = urllib.request.Request(
        f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main():
    import time
    username = f"mem_llm_{int(time.time()) % 10000}"
    print(f"Registering {username}...")
    token = register_user(username)

    print()
    print("=" * 60)
    print("Step 1: Tell LLM a memorable fact")
    print("=" * 60)
    msg = (
        "你好,我是价值投资者,主要关注半导体和AI基础设施赛道。"
        "投资风格偏长期持有,时间 horizon 3-5 年。请记住这些信息。"
    )
    print(f"  user: {msg[:60]}...")
    final, tools = send_msg(f"mem-llm-{username}-1", msg, token)
    print(f"  assistant final ({len(final)} chars): {final[:120]}...")
    print(f"  tool calls: {tools}")

    # Check if memory.* was called
    memory_tools_called = [t for t in tools if t.get("tool", "").startswith("memory.")]
    if memory_tools_called:
        print(f"  ✅ LLM autonomously called memory tools: {memory_tools_called}")
    else:
        print(f"  ⚠️ LLM did NOT call memory tools (may have just answered from context)")

    print()
    print("=" * 60)
    print("Step 2: Check memory DB — was anything written?")
    print("=" * 60)
    notes = http_get("/api/v1/memory/agent_notes", token)
    profile = http_get("/api/v1/memory/user_profile", token)
    print(f"  agent_notes ({notes['chars_used']} chars): {notes['body'][:200]!r}")
    print(f"  user_profile ({profile['chars_used']} chars): {profile['body'][:200]!r}")
    if notes["body"] or profile["body"]:
        print("  ✅ memory WAS written")
    else:
        print("  ⚠️ memory NOT written — LLM may need a stronger nudge")
        print("     (this is expected behavior if LLM judges the info not worth saving)")

    print()
    print("=" * 60)
    print("Step 3: New conversation — does LLM remember?")
    print("=" * 60)
    msg2 = "你记得我的投资风格吗?简单说说我关注什么。"
    print(f"  user: {msg2}")
    final2, tools2 = send_msg(f"mem-llm-{username}-2", msg2, token)
    print(f"  assistant final: {final2[:300]}")
    # Check if the answer mentions key facts
    keywords = ["价值投资", "半导体", "AI", "长期", "3-5"]
    hits = [k for k in keywords if k in final2]
    print(f"  keyword hits: {hits}")
    if hits:
        print("  ✅ LLM recalled user info (memory injection working)")
    else:
        print("  ⚠️ LLM didn't mention stored preferences — memory may be empty")

    print()
    print("Done. Inspect results above to judge if Phase A is working end-to-end.")


if __name__ == "__main__":
    main()
