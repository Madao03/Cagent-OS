"""Reset users.db (delete existing accounts + wal files)."""
import shutil
from pathlib import Path

DATA = Path(r"d:\Projects\cagent-os\data")

for name in ("users.db", "users.db-wal", "users.db-shm"):
    p = DATA / name
    if not p.exists():
        print(f"  skip {name} (not found)")
        continue
    if name == "users.db":
        bak = DATA / "users.db.bak"
        shutil.copy2(p, bak)
        print(f"  backed up to {bak.name}")
    p.unlink()
    print(f"  deleted {name}")

print("done")
