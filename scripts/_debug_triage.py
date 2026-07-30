"""Debug script — test /api/v1/knowledge/triage endpoint."""
import json
import urllib.request

url = "http://127.0.0.1:8000/api/v1/knowledge/triage"
print(f"GET {url}")
r = urllib.request.urlopen(url, timeout=10)
data = json.loads(r.read())
print(f"total: {data['total']}, matched_articles: {data.get('matched_articles')}, source: {data.get('source_file')}")
print()
for e in data["entries"][:15]:
    level = e["level"]
    date = e["date"]
    title = e["title"]
    file_path = e["file_path"]
    status = "✓" if file_path else "✗"
    print(f"  [{level}] {date} | {title[:50]}")
    print(f"        {status} {file_path or '(unmatched)'}")
