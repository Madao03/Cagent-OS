"""Simulate the frontend: POST a chat message, stream SSE, count events."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
CONV_ID = "test-web-verify-001"
USER_QUERY = "你好,简单介绍一下你自己(一句话就行)"


def main():
    url = f"{BASE}/api/v1/conversations/{CONV_ID}/messages"
    body = json.dumps({"content": USER_QUERY, "user_id": "default", "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Principal-Id": "default",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    print(f"POST {url}")
    print(f"Body: {USER_QUERY!r}")
    print("-" * 60)

    events = []
    current_phase = None
    answer_chars = 0

    with urllib.request.urlopen(req, timeout=120) as resp:
        print(f"HTTP {resp.status}, Content-Type: {resp.headers.get('content-type')}")
        buf = b""
        for chunk in iter(lambda: resp.read(1024), b""):
            buf += chunk
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                for line in raw.decode("utf-8", errors="replace").split("\n"):
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[5:].strip()
                    if not payload_str:
                        continue
                    try:
                        payload = json.loads(payload_str)
                    except Exception as e:
                        print(f"  [parse fail] {e}: {payload_str[:100]}")
                        continue
                    events.append(payload)
                    phase = payload.get("phase", "?")
                    if phase != current_phase:
                        print(f"  [{len(events):>3}] phase={phase} type={payload.get('type','?')}")
                        current_phase = phase
                    if phase == "answer_delta":
                        answer_chars += len(payload.get("answer_chunk", ""))
                    elif phase == "tool_call":
                        print(f"       tool={payload.get('tool_name')} status={payload.get('tool_status')}")
                    elif phase == "final_answer":
                        final = payload.get("answer_chunk", "")
                        print(f"       FINAL answer_len={len(final)}")
                    elif phase == "error":
                        print(f"       ERROR: {payload.get('summary')}")

    print("-" * 60)
    print(f"Total events: {len(events)}")
    print(f"Delta chars accumulated: {answer_chars}")
    phases = {}
    for e in events:
        p = e.get("phase", "?")
        phases[p] = phases.get(p, 0) + 1
    print(f"Phase distribution: {phases}")


if __name__ == "__main__":
    main()
