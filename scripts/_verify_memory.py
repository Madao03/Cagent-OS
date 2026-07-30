"""Verify Phase A memory endpoints: GET / PUT / full_state + char cap."""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def register_or_login(username):
    """Register via invitation or login if exists."""
    # Generate a code directly
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cagent_os.auth import InvitationCodeStore
    import secrets
    code = "MEM" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
    InvitationCodeStore(r"d:\Projects\cagent-os\data\invitation_codes.db").add(code=code, created_by="mem-test")

    url = f"{BASE}/api/v1/auth/register"
    body = json.dumps({"invitation_code": code, "username": username}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["token"]
    except urllib.error.HTTPError as e:
        if e.code == 409:
            # Login instead
            url = f"{BASE}/api/v1/auth/login"
            body = json.dumps({"username": username}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())["token"]
        raise


def call(method, path, token, body=None):
    url = f"{BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    import time
    username = f"mem_tester_{int(time.time()) % 10000}"
    print(f"Registering {username}...")
    token = register_or_login(username)
    print(f"OK, got token")

    print()
    print("=" * 60)
    print("1. GET /api/v1/memory/agent_notes (initial — should be empty)")
    print("=" * 60)
    st, data = call("GET", "/api/v1/memory/agent_notes", token)
    print(f"  status={st}")
    print(f"  body={data.get('body')!r}")
    print(f"  chars_used={data.get('chars_used')}/{data.get('char_limit')}")
    assert data["body"] == ""

    print()
    print("=" * 60)
    print("2. PUT /api/v1/memory/agent_notes (write some notes)")
    print("=" * 60)
    notes = "# Agent Notes\n\n- 用户偏好中文回复\n- 关注 NVDA、TSLA\n- 风险偏好: 中性"
    st, data = call("PUT", "/api/v1/memory/agent_notes", token, {"body": notes})
    print(f"  status={st}")
    print(f"  chars_used={data.get('chars_used')}/{data.get('char_limit')}")
    assert st == 200

    print()
    print("=" * 60)
    print("3. GET again (should match what we wrote)")
    print("=" * 60)
    st, data = call("GET", "/api/v1/memory/agent_notes", token)
    print(f"  body={data['body']!r}")
    assert data["body"] == notes

    print()
    print("=" * 60)
    print("4. PUT user_profile")
    print("=" * 60)
    profile = "# User Profile\n\n- 投资风格: 长期价值投资\n- 关注行业: 半导体、AI"
    st, data = call("PUT", "/api/v1/memory/user_profile", token, {"body": profile})
    print(f"  status={st}, chars={data.get('chars_used')}")
    assert st == 200

    print()
    print("=" * 60)
    print("5. GET full_state (both files in one call)")
    print("=" * 60)
    st, data = call("GET", "/api/v1/memory/full_state", token)
    print(f"  status={st}")
    print(f"  agent_notes chars: {data['agent_notes']['chars_used']}/{data['agent_notes']['char_limit']}")
    print(f"  user_profile chars: {data['user_profile']['chars_used']}/{data['user_profile']['char_limit']}")
    assert data["agent_notes"]["body"] == notes
    assert data["user_profile"]["body"] == profile

    print()
    print("=" * 60)
    print("6. PUT oversized body (should 409 with consolidate hint)")
    print("=" * 60)
    huge = "x" * 3000  # exceeds 2000 char limit
    st, data = call("PUT", "/api/v1/memory/agent_notes", token, {"body": huge})
    print(f"  status={st}")
    print(f"  error={data.get('detail', {}).get('error')}")
    print(f"  message={data.get('detail', {}).get('message', '')[:100]}")
    assert st == 409
    assert data["detail"]["error"] == "memory_overflow"
    assert "current_body" in data["detail"]  # Hermes-style: return current for consolidation

    print()
    print("✅✅✅ Phase A memory system: ALL VERIFIED")


if __name__ == "__main__":
    main()
