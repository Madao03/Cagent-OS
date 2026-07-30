"""Test rate limiting on /login endpoint."""
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"

print("Testing rate limit on /api/v1/auth/login (5/min allowed)")
print("=" * 60)

for i in range(7):
    body = json.dumps({"username": "fake_user", "pin": "0000"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"  Attempt {i+1}: {r.status} (unexpected success)")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:120]
        print(f"  Attempt {i+1}: {e.code} — {body}")

print()
print("Expected: attempts 1-5 return 401 (invalid credentials),")
print("          attempts 6-7 return 429 (too many requests)")
