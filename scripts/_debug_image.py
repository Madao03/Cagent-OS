"""Test image serving via /static/knowledge/* route."""
import urllib.parse
import urllib.request

raw_path = "/knowledge-static/00_Inbox/2026-06-16-万字科普美联储观察入门指南/images/img_0.png"
url = "http://127.0.0.1:8000" + urllib.parse.quote(raw_path)
print(f"GET {url}")
try:
    r = urllib.request.urlopen(url, timeout=5)
    data = r.read()
    print(f"status: {r.status}")
    print(f"content-type: {r.headers.get('content-type')}")
    print(f"size: {len(data)} bytes")
except Exception as e:
    print(f"FAIL: {e}")
