"""Cross-document consistency check.

From FY2024 earnings: Q4'24 = 13.05B, FY2024 = 40.87B
From Q1 2025 earnings: Q1'25 = 15.81B
From Q3 2025 earnings: Q3'25 = 20.38B
From Q4 2025 earnings: Q4'25 = 22.25B, FY2025 = 76.72B, Q3'25 = 20.38B (comp), Q4'24 = 16.11B (comp)

Restatement detection: same period from different documents should match.
Four-quarter sum: Q1+Q2+Q3+Q4 should ≈ FY.
"""
import json, sys
sys.path.insert(0, "src")
from pathlib import Path
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

FIXTURE_DIR = Path("tests/fixtures/edgar")
ext = EarningsReleaseExtractor()

# Extract from all fixtures
all_data = {}
for f in sorted(FIXTURE_DIR.glob("*.html")):
    meta_f = f.with_suffix(".meta.json")
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
    data = ext.extract(f.read_bytes(), meta=meta)
    all_data[f.stem] = data

# Collect all revenue values by (period_start, period_end, currency)
from collections import defaultdict
revenue_by_period = defaultdict(list)  # (start, end) → [(source, value)]

for source, data in all_data.items():
    for r in data.records:
        key = (r.period_start, r.period_end, r.currency)
        rev = r.metrics.get("revenue")
        if rev is not None:
            revenue_by_period[key].append((source, rev))

print("=" * 80)
print("RESTATEMENT DETECTION: same period from different sources")
print("=" * 80)

for (start, end, cur), values in sorted(revenue_by_period.items()):
    if len(values) > 1:
        unique_vals = set(v for _, v in values)
        status = "✅ CONSISTENT" if len(unique_vals) == 1 else "⚠ RESTATED!"
        print(f"\n  {start}→{end} [{cur}] ({len(values)} sources): {status}")
        for src, val in values:
            print(f"    {src:45s} → {val/1e9:.4f}B" if val > 1e6 else f"    {src:45s} → {val}")

print("\n" + "=" * 80)
print("FOUR-QUARTER SUM CHECK (FY2025)")
print("=" * 80)

# FY2025 quarters: Q1, Q2, Q3, Q4
fy2025_quarters = {}
fy2025_total = None

for (start, end, cur), values in revenue_by_period.items():
    if cur != "CNY":
        continue
    # Q1 2025
    if start == "2025-01-01" and end == "2025-03-31":
        fy2025_quarters["Q1"] = values[0][1]  # Take first source
    elif start == "2025-04-01" and end == "2025-06-30":
        fy2025_quarters["Q2"] = values[0][1]
    elif start == "2025-07-01" and end == "2025-09-30":
        fy2025_quarters["Q3"] = values[0][1]
    elif start == "2025-10-01" and end == "2025-12-31" and "fiscal" not in start:
        fy2025_quarters["Q4"] = values[0][1]
    elif start == "2025-01-01" and end == "2025-12-31":
        fy2025_total = values[0][1]

print(f"\n  FY2025 Total: {fy2025_total/1e9:.2f}B" if fy2025_total else "  FY2025 Total: MISSING")
for q in ["Q1", "Q2", "Q3", "Q4"]:
    v = fy2025_quarters.get(q)
    print(f"  {q} 2025: {v/1e9:.2f}B" if v else f"  {q} 2025: MISSING")

if fy2025_quarters and fy2025_total:
    sum_q = sum(v for v in fy2025_quarters.values() if v)
    diff_pct = abs(sum_q - fy2025_total) / fy2025_total * 100
    print(f"\n  Sum of quarters: {sum_q/1e9:.2f}B")
    print(f"  FY total:       {fy2025_total/1e9:.2f}B")
    print(f"  Difference:     {diff_pct:.2f}%")
    if diff_pct < 1.0:
        print(f"  ✅ PASS: quarters sum ≈ FY total (<1%)")
    else:
        missing = [q for q in ["Q1","Q2","Q3","Q4"] if q not in fy2025_quarters]
        print(f"  ⚠ CHECK: difference >1% (missing: {missing or 'none'})")
