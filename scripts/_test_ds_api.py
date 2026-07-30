import time, urllib.request, json
t0 = time.time()
resp = urllib.request.urlopen("http://127.0.0.1:8800/api/v1/data-sources", timeout=60)
d = json.loads(resp.read())
print(f"First call: {time.time()-t0:.1f}s, {d['total']} sources, {d['available']} available")
t0 = time.time()
resp = urllib.request.urlopen("http://127.0.0.1:8800/api/v1/data-sources", timeout=5)
d = json.loads(resp.read())
print(f"Cached call: {time.time()-t0:.1f}s, {d['total']} sources")
for s in d["sources"]:
    status = "online" if s["available"] else "OFFLINE"
    print(f"  {s['name']:25s} {status}")
