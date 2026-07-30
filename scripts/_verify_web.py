"""Verify the local web MVP: all endpoints + static assets respond."""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


def get(path, timeout=30):
    url = BASE + path
    with urllib.request.urlopen(url, timeout=timeout) as r:
        body = r.read()
        return r.status, body


def main():
    print("=" * 60)
    print("1. GET / (root → should 307 redirect to /static/pages/chat.html)")
    print("=" * 60)
    try:
        # Don't auto-follow redirect — use a custom opener
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        req = urllib.request.Request(BASE + "/")
        with opener.open(req, timeout=5) as r:
            print(f"  final: status={r.status}, url={r.url}, bytes={len(r.read())}")
    except Exception as e:
        print(f"  [ERR] {e}")

    print()
    print("=" * 60)
    print("2. GET /static/pages/chat.html")
    print("=" * 60)
    try:
        st, body = get("/static/pages/chat.html", timeout=5)
        print(f"  status={st}, bytes={len(body)}")
    except Exception as e:
        print(f"  [ERR] {e}")

    print()
    print("=" * 60)
    print("3. GET /static/assets/js/chat.js")
    print("=" * 60)
    try:
        st, body = get("/static/assets/js/chat.js", timeout=5)
        print(f"  status={st}, bytes={len(body)}")
    except Exception as e:
        print(f"  [ERR] {e}")

    print()
    print("=" * 60)
    print("4. GET /static/pages/knowledge.html + /static/assets/js/knowledge.js")
    print("=" * 60)
    for path in ["/static/pages/knowledge.html", "/static/assets/js/knowledge.js"]:
        try:
            st, body = get(path, timeout=5)
            print(f"  {path}: status={st}, bytes={len(body)}")
        except Exception as e:
            print(f"  {path}: [ERR] {e}")

    print()
    print("=" * 60)
    print("5. GET /api/v1/rag/search?q=NVDA 估值")
    print("=" * 60)
    try:
        q = "NVDA 估值"
        url = f"/api/v1/rag/search?q={urllib.parse.quote(q)}&top_k=3"
        st, body = get(url, timeout=60)
        data = json.loads(body)
        print(f"  status={st}, total={data['total']}, elapsed_ms={data['elapsed_ms']}")
        for i, r in enumerate(data["results"]):
            src = (r.get("source") or r.get("id") or "?")[:40]
            print(f"    #{i+1} sim={r['similarity']:.3f} stage={r['search_stage']} source={src}")
            print(f"       preview: {r['preview'][:80]}...")
    except Exception as e:
        print(f"  [ERR] {e}")


if __name__ == "__main__":
    main()
