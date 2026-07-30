"""Compare cagentos-frontend/ vs static/pages/ — find which files are newer."""
from pathlib import Path
from datetime import datetime

SRC = Path(r"d:\Projects\cagent-os\cagentos-frontend")
DST = Path(r"d:\Projects\cagent-os\src\cagent_os\interfaces\http\static")

print(f"{'name':<30} {'src_mtime':<22} {'dst_mtime':<22} needs_sync")
print("-" * 80)
for src_file in (SRC / "pages").glob("*.html"):
    dst_file = DST / "pages" / src_file.name
    if not dst_file.exists():
        print(f"{src_file.name:<30} {datetime.fromtimestamp(src_file.stat().st_mtime)}  MISSING                YES")
        continue
    src_t = src_file.stat().st_mtime
    dst_t = dst_file.stat().st_mtime
    needs = src_t > dst_t + 1  # 1s tolerance
    src_str = datetime.fromtimestamp(src_t).strftime("%Y-%m-%d %H:%M:%S")
    dst_str = datetime.fromtimestamp(dst_t).strftime("%Y-%m-%d %H:%M:%S")
    mark = "🔄 SYNC" if needs else "✓ ok"
    print(f"{src_file.name:<30} {src_str:<22} {dst_str:<22} {mark}")
