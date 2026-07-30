"""Find all chat/brief/knowledge.html files in the project, newest first."""
from pathlib import Path
from datetime import datetime

ROOT = Path(r"d:\Projects\cagent-os")
files = []
for name in ("chat.html", "brief.html", "knowledge.html"):
    for f in ROOT.rglob(name):
        if "node_modules" in str(f) or ".egg-info" in str(f):
            continue
        files.append(f)

files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
print(f"{'mtime':<22} {'size':>10}  path")
print("-" * 100)
for f in files[:20]:
    t = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    size = f.stat().st_size
    rel = f.relative_to(ROOT)
    print(f"{t:<22} {size:>10}  {rel}")
