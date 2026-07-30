"""Show unmatched triage entries vs available directories to debug mismatches."""
import json
import urllib.request
from pathlib import Path
import re

# Get triage data
r = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/knowledge/triage", timeout=10)
data = json.loads(r.read())

# Get available directories
inbox = Path("knowledge/00_Inbox")
dirs = [d.name for d in inbox.iterdir() if d.is_dir()]

# Show unmatched entries
print("=" * 80)
print("UNMATCHED entries with potential candidates:")
print("=" * 80)
for e in data["entries"]:
    if e["file_path"]:
        continue
    title = e["title"]
    print(f"\nTitle: {title}")
    # Find closest dir by simple char overlap
    def clean(s):
        return re.sub(r"[\s\-—–:：,,。.!！?？()（）【】\[\]\"'`#0-9]+", "", s.lower())
    ct = clean(title)
    scored = []
    for d in dirs:
        cd = clean(d)
        # Count common chars
        common = sum(1 for c in ct if c in cd)
        scored.append((d, common, len(ct), len(cd)))
    scored.sort(key=lambda x: x[1] / max(1, min(x[2], x[3])), reverse=True)
    for d, common, lt, ld in scored[:3]:
        ratio = common / max(1, min(lt, ld))
        print(f"  → {d}  (overlap: {common}/{min(lt,ld)} = {ratio:.0%})")
