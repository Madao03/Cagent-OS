"""Quick registration test for manual verification."""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"
CODE = "FES6F3KM"  # First code from the batch
USERNAME = "test_user_1"
PIN = "1234"


def main():
    # 1. Register
    url = f"{BASE}/api/v1/auth/register"
    body = {"invitation_code": CODE, "username": USERNAME, "pin": PIN}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            print(f"✓ Register OK ({r.status})")
            print(f"  user_id: {data['user']['id'][:8]}")
            print(f"  username: {data['user']['username']}")
            return data["token"]
    except urllib.error.HTTPError as e:
        print(f"✗ Register FAIL ({e.code}): {e.read().decode()}")
        return None


if __name__ == "__main__":
    main()
