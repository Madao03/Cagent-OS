"""Inspect reason field of triage entries."""
import json
import urllib.request

r = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/knowledge/triage", timeout=5)
data = json.loads(r.read())
print(f"Total: {data['total']}\n")
for e in data["entries"][:5]:
    print(f"Title: {e['title'][:50]}")
    print(f"  reason: {e.get('reason')!r}")
    print(f"  file_path: {e.get('file_path')!r}")
    print()
