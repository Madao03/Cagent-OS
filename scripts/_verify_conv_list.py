"""Verify conversation list + event replay endpoints."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def main():
    print("=" * 60)
    print("GET /api/v1/conversations?limit=10")
    print("=" * 60)
    req = urllib.request.Request(
        f"{BASE}/api/v1/conversations?limit=10",
        headers={"X-Principal-Id": "default"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    print(f"total: {data['total']}, principal: {data['principal_id']}")
    for c in data["conversations"]:
        cid = c["conversation_id"]
        print(f"  {cid:<40} events={c['event_count']:>3} last={c['last_user_message'][:60]!r}")

    if not data["conversations"]:
        print("[skip] no conversations to replay")
        return

    # Pick first conv to test event replay
    target = data["conversations"][0]["conversation_id"]
    print()
    print("=" * 60)
    print(f"GET /api/v1/conversations/{target}/events")
    print("=" * 60)
    req = urllib.request.Request(
        f"{BASE}/api/v1/conversations/{target}/events",
        headers={"X-Principal-Id": "default"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
    print(f"total events: {data['total']}")
    for i, evt in enumerate(data["events"][:5], 1):
        content = (evt.get("content") or "")[:80]
        print(f"  [{i:>2}] type={evt['type']!r} role={evt.get('role')!r}")
        if content:
            print(f"       content: {content!r}")
    if data["total"] > 5:
        print(f"  ... ({data['total'] - 5} more)")


if __name__ == "__main__":
    main()
