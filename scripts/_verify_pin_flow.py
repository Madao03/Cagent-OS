"""Verify PIN-based auth: register with PIN → login with PIN → wrong PIN
fails → disabled user can't login → admin endpoints work.
"""
import json
import os
import secrets
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cagent_os.auth import InvitationCodeStore

BASE = "http://127.0.0.1:8000"
ADMIN_TOKEN = "test-admin-token-123"


def post(url, body, headers=None):
    headers = headers or {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main():
    print("=" * 60)
    print("1. Generate invitation code")
    print("=" * 60)
    store = InvitationCodeStore(r"d:\Projects\cagent-os\data\invitation_codes.db")
    code = "PIN" + "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(5))
    store.add(code=code, created_by="pin-test")

    import time
    username = f"pinuser_{int(time.time()) % 10000}"
    pin = "1234"

    print()
    print("=" * 60)
    print(f"2. Register {username} with PIN")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/register", {
        "invitation_code": code, "username": username, "pin": pin,
    })
    print(f"  status={st}, user={data.get('user', {}).get('username')}")
    assert st == 200

    print()
    print("=" * 60)
    print("3. Login with correct PIN")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": username, "pin": pin})
    print(f"  status={st}, token_len={len(data.get('token', ''))}")
    assert st == 200
    user_token = data["token"]

    print()
    print("=" * 60)
    print("4. Login with WRONG PIN (should 401)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": username, "pin": "9999"})
    print(f"  status={st}, detail={data.get('detail', '')[:60]}")
    assert st == 401

    print()
    print("=" * 60)
    print("5. Login with no PIN (should 400)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": username})
    print(f"  status={st}, detail={data.get('detail', '')[:60]}")
    assert st == 400

    print()
    print("=" * 60)
    print("6. Admin: list users (with X-Admin-Token)")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/admin/users", headers={"X-Admin-Token": ADMIN_TOKEN})
    print(f"  status={st}, total_users={data.get('total')}")
    assert st == 200

    print()
    print("=" * 60)
    print("7. Admin: list users WITHOUT admin token (should 403 or 503)")
    print("=" * 60)
    st, data = get(f"{BASE}/api/v1/admin/users")
    print(f"  status={st}, detail={data.get('detail', '')[:60]}")
    assert st in (403, 503)

    print()
    print("=" * 60)
    print("8. Admin: disable user")
    print("=" * 60)
    st, data = post(
        f"{BASE}/api/v1/admin/users/{username}/disable",
        body=None,
        headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
    )
    print(f"  status={st}, response={data}")
    assert st == 200

    print()
    print("=" * 60)
    print("9. Disabled user tries to login (should 403)")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": username, "pin": pin})
    print(f"  status={st}, detail={data.get('detail', '')[:80]}")
    assert st == 403

    print()
    print("=" * 60)
    print("10. Admin: re-enable user")
    print("=" * 60)
    st, data = post(
        f"{BASE}/api/v1/admin/users/{username}/enable",
        body=None,
        headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
    )
    print(f"  status={st}, response={data}")
    assert st == 200

    print()
    print("=" * 60)
    print("11. User can login again after re-enable")
    print("=" * 60)
    st, data = post(f"{BASE}/api/v1/auth/login", {"username": username, "pin": pin})
    print(f"  status={st}")
    assert st == 200

    print()
    print("✅✅✅ PIN auth + admin endpoints: ALL VERIFIED")


if __name__ == "__main__":
    # Set ADMIN_TOKEN env var before importing anything that uses it
    os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN
    main()
