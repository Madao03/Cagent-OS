"""Inspect the triage table to understand its column structure."""
from pathlib import Path

p = Path("knowledge/00_Inbox/分诊台账.md")
lines = p.read_text(encoding="utf-8").splitlines()
rows = [l for l in lines if l.startswith("|") and "---" not in l]

print(f"Total rows: {len(rows)}")
print()
for i, row in enumerate(rows[:5]):
    fields = [f.strip() for f in row.split("|")[1:-1]]  # strip empty first/last
    print(f"Row {i}: {len(fields)} fields")
    for j, f in enumerate(fields):
        print(f"  [{j}] {f[:80]}")
    print()

# Find rows with different field counts
field_counts = {}
for row in rows:
    n = len([f for f in row.split("|")[1:-1]])
    field_counts[n] = field_counts.get(n, 0) + 1
print(f"Field count distribution: {field_counts}")
