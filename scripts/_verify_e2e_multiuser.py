"""End-to-end multi-user test: register 2 users, each sends a message,
verify they can only see their own conversations.

Simulates the full frontend flow:
  1. POST /register → alice, bob (different conv IDs)
  2. Each sends a message → creates 2 conversations in DB
  3. GET /conversations with alice's token → should see only alice's conv
  4. GET /conversations with bob's token → should see only bob's conv
  5. GET /conversations/{other_user_conv}/events → should 403 or 404
"""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def post(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(url, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def send_msg(conv_id, content, token):
    """Send a chat message (non-streaming variant via oneshot is simpler)."""
    # We use the streaming endpoint but just read until done
    url = f"{BASE}/api/v1/conversations/{conv_id}/messages"
    body = {"content": content, "user_id": "ignored-with-auth", "stream": True}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        # Drain the stream
        for _ in iter(lambda: resp.read(1024), b""):
            pass
    return resp.status


def register_or_login(email, password, display_name):
    """Try register first; if 409 (already exists), fall back to login."""
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "email": email, "password": password, "display_name": display_name,
    })
    if st == 409:
        # Already exists — login instead
        st, data = post(f"{BASE}/api/v1/auth/login", {
            "email": email, "password": password,
        })
    return st, data


def main():
    print("=" * 60)
    print("Step 1: Register/Login Alice")
    print("=" * 60)
    st, data = register_or_login("alice@e2e.com", "alice123", "Alice")
    print(f"  status={st}, user={data.get('user', {}).get('display_name')}")
    alice_token = data["token"]
    alice_id = data["user"]["id"]

    print()
    print("=" * 60)
    print("Step 2: Register/Login Bob")
    print("=" * 60)
    st, data = register_or_login("bob@e2e.com", "bob123", "Bob")
    print(f"  status={st}, user={data.get('user', {}).get('display_name')}")
    bob_token = data["token"]
    bob_id = data["user"]["id"]

    print()
    print("=" * 60)
    print("Step 3: Alice sends a message to her own conversation")
    print("=" * 60)
    alice_conv = "e2e-alice-conv-001"
    st = send_msg(alice_conv, "你好,这是 Alice 的私有消息", alice_token)
    print(f"  alice sent msg → status={st}")

    print()
    print("=" * 60)
    print("Step 4: Bob sends a message to his own conversation")
    print("=" * 60)
    bob_conv = "e2e-bob-conv-001"
    st = send_msg(bob_conv, "Bob's private question", bob_token)
    print(f"  bob sent msg → status={st}")

    print()
    print("=" * 60)
    print("Step 5: Alice lists conversations — should see ONLY hers")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/conversations?limit=20", token=alice_token)
    print(f"  status={st}, total={data.get('total')}, principal={data.get('principal_id')[:8]}")
    conv_ids = [c["conversation_id"] for c in data.get("conversations", [])]
    print(f"  alice sees: {conv_ids}")
    assert alice_conv in conv_ids, "Alice should see her own conv"
    assert bob_conv not in conv_ids, "Alice must NOT see Bob's conv"

    print()
    print("=" * 60)
    print("Step 6: Bob lists conversations — should see ONLY his")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/conversations?limit=20", token=bob_token)
    print(f"  status={st}, total={data.get('total')}, principal={data.get('principal_id')[:8]}")
    conv_ids = [c["conversation_id"] for c in data.get("conversations", [])]
    print(f"  bob sees: {conv_ids}")
    assert bob_conv in conv_ids, "Bob should see his own conv"
    assert alice_conv not in conv_ids, "Bob must NOT see Alice's conv"

    print()
    print("=" * 60)
    print("Step 7: Alice tries to read Bob's conversation events (should 403)")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/conversations/{bob_conv}/events", token=alice_token)
    print(f"  status={st}, detail={data.get('detail', '')[:80]}")
    assert st in (403, 404), f"Alice must NOT access Bob's conv, got {st}"

    print()
    print("✅✅✅ Multi-user isolation VERIFIED — Alice and Bob cannot see each other")


if __name__ == "__main__":
    main()
