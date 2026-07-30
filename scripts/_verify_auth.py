"""Verify auth endpoints: register → login → me → cross-user isolation."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def post_json(url, body, headers=None):
    headers = headers or {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    print("=" * 60)
    print("1. Register user1")
    print("=" * 60)
    st, data = post_json(
        f"{BASE}/api/v1/auth/register",
        {"email": "alice@test.com", "password": "secret123", "display_name": "Alice"},
    )
    print(f"  status={st}")
    print(f"  user_id={data.get('user', {}).get('id', '?')[:8]}")
    print(f"  token_len={len(data.get('token', ''))}")
    alice_token = data.get("token", "")
    alice_id = data.get("user", {}).get("id", "?")
    assert st in (200, 409), f"unexpected: {data}"

    print()
    print("=" * 60)
    print("2. Register user2")
    print("=" * 60)
    st, data = post_json(
        f"{BASE}/api/v1/auth/register",
        {"email": "bob@test.com", "password": "secret456", "display_name": "Bob"},
    )
    print(f"  status={st}")
    bob_token = data.get("token", "")
    bob_id = data.get("user", {}).get("id", "?")
    assert st in (200, 409)

    print()
    print("=" * 60)
    print("3. Login as alice")
    print("=" * 60)
    st, data = post_json(
        f"{BASE}/api/v1/auth/login",
        {"email": "alice@test.com", "password": "secret123"},
    )
    print(f"  status={st}, user={data.get('user', {}).get('display_name')}")
    alice_token = data.get("token", alice_token)

    print()
    print("=" * 60)
    print("4. Login with WRONG password (should 401)")
    print("=" * 60)
    st, data = post_json(
        f"{BASE}/api/v1/auth/login",
        {"email": "alice@test.com", "password": "wrong-password"},
    )
    print(f"  status={st}, detail={data.get('detail', '?')}")
    assert st == 401

    print()
    print("=" * 60)
    print("5. GET /me with alice's token")
    print("=" * 60)
    st, data = get_json(
        f"{BASE}/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    print(f"  status={st}")
    print(f"  user_id={data.get('user', {}).get('id', '?')[:8]}")
    print(f"  email={data.get('user', {}).get('email')}")
    assert st == 200
    assert data["user"]["id"] == alice_id

    print()
    print("=" * 60)
    print("6. GET /me without token (should 401)")
    print("=" * 60)
    st, data = get_json(f"{BASE}/api/v1/auth/me")
    print(f"  status={st}, detail={data.get('detail', '?')}")
    assert st == 401

    print()
    print("=" * 60)
    print("7. Cross-user isolation: alice's conversations list")
    print("=" * 60)
    st, data = get_json(
        f"{BASE}/api/v1/conversations?limit=10",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    print(f"  status={st}, total={data.get('total')}, principal={data.get('principal_id', '?')[:8]}")
    # The principal_id here should be alice's user_id
    assert data["principal_id"] == alice_id

    print()
    print("=" * 60)
    print("8. Bob's conversations (should show bob's principal_id, not alice's)")
    print("=" * 60)
    st, data = get_json(
        f"{BASE}/api/v1/conversations?limit=10",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    print(f"  status={st}, total={data.get('total')}, principal={data.get('principal_id', '?')[:8]}")
    assert data["principal_id"] == bob_id
    assert data["principal_id"] != alice_id, "Bob and Alice should have different principal_ids!"

    print()
    print("✅ All auth tests passed")


if __name__ == "__main__":
    main()
