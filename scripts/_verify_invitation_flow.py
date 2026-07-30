"""End-to-end test for invitation-code registration flow.

Flow:
  1. Generate 2 invitation codes (directly into store)
  2. Register Alice with code1
  3. Try to register Bob with code1 again → should fail (code already used)
  4. Register Bob with code2 → success
  5. Try register Charlie with invalid code → should fail
  6. Login as Alice (username only, no password)
  7. Alice & Bob conversations should be isolated
  8. Verify Alice's conversation is tied to her user_id (memory isolation)
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cagent_os.auth import InvitationCodeStore

BASE = "http://127.0.0.1:8000"
INVITATION_DB = Path(r"d:\Projects\cagent-os\data\invitation_codes.db")


def post(url, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(url, token):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def send_msg(conv_id, content, token):
    url = f"{BASE}/api/v1/conversations/{conv_id}/messages"
    body = {"content": content, "user_id": "ignored", "stream": True}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        for _ in iter(lambda: resp.read(1024), b""):
            pass
    return resp.status


def main():
    print("=" * 60)
    print("Step 0: Generate 2 fresh invitation codes")
    print("=" * 60)
    store = InvitationCodeStore(str(INVITATION_DB))
    # Use random codes to avoid conflicts with prior test runs
    import secrets
    code1 = "FRESH" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
    code2 = "FRESH" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(4))
    store.add(code=code1, created_by="e2e-test")
    store.add(code=code2, created_by="e2e-test")
    print(f"  code1={code1}  code2={code2}")

    print()
    print("=" * 60)
    print("Step 1: Register Alice with code1")
    print("=" * 60)
    # Use unique username per run to avoid 409 conflicts
    import time as _t
    suffix = str(int(_t.time()))[-4:]
    alice_username = f"alice_inv_{suffix}"
    bob_username = f"bob_inv_{suffix}"
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "invitation_code": code1, "username": alice_username,
    })
    print(f"  status={st}, user={data.get('user', {}).get('username')}")
    assert st == 200
    alice_token = data["token"]
    alice_id = data["user"]["id"]
    print(f"  alice_id={alice_id[:8]}, created_via={data['user'].get('created_via')}")

    print()
    print("=" * 60)
    print("Step 2: Try register Bob with code1 again (should 403)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "invitation_code": code1, "username": bob_username,
    })
    print(f"  status={st}, detail={data.get('detail', '')[:80]}")
    assert st == 403

    print()
    print("=" * 60)
    print("Step 3: Register Bob with code2 (should succeed)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "invitation_code": code2, "username": bob_username,
    })
    print(f"  status={st}, user={data.get('user', {}).get('username')}")
    assert st == 200
    bob_token = data["token"]
    bob_id = data["user"]["id"]

    print()
    print("=" * 60)
    print("Step 4: Try register Charlie with INVALID code (should 403)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "invitation_code": "FAKE99ZZ", "username": "charlie_inv",
    })
    print(f"  status={st}, detail={data.get('detail', '')[:80]}")
    assert st == 403

    print()
    print("=" * 60)
    print("Step 5: Login as Alice (username only, no password)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": alice_username})
    print(f"  status={st}, user={data.get('user', {}).get('username')}")
    assert st == 200

    print()
    print("=" * 60)
    print("Step 6: Alice sends message; verify conversation.user_id == alice_id")
    print("=" * 60)
    alice_conv = "inv-alice-conv-001"
    send_msg(alice_conv, "Alice 私有消息", alice_token)
    print(f"  alice sent msg to {alice_conv}")

    # Verify conversation record has user_id = alice_id (memory isolation fix)
    import sqlite3
    conv_db = r"d:\Projects\cagent-os\data\conversations.db"
    with sqlite3.connect(conv_db) as conn:
        row = conn.execute(
            "SELECT principal_id, user_id FROM conversations WHERE conversation_id = ?",
            (alice_conv,),
        ).fetchone()
    print(f"  conv record: principal_id={row[0][:8]}, user_id={row[1][:8]}")
    assert row[0] == alice_id, f"principal_id should be alice_id, got {row[0]}"
    assert row[1] == alice_id, f"user_id should ALSO be alice_id (memory fix), got {row[1]}"
    print(f"  ✅ memory isolation fix verified: user_id tied to alice_id")

    print()
    print("=" * 60)
    print("Step 7: Bob can't see Alice's conversation")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/conversations?limit=10", bob_token)
    bob_convs = [c["conversation_id"] for c in data.get("conversations", [])]
    print(f"  bob sees: {bob_convs}")
    assert alice_conv not in bob_convs, "Bob must not see Alice's conv"

    print()
    print("✅✅✅ Invitation-code flow + memory isolation: ALL VERIFIED")


if __name__ == "__main__":
    main()
