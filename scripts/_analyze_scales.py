"""Check all fields across both scales for XPEV Q4 2025 cache."""
import sqlite3, json, sys
sys.stdout.reconfigure(encoding='utf-8')
db = sqlite3.connect('data/edgar_release.db')
# Use the pre-dedup cache. Let me check if we still have both versions.
# Actually the cache was rebuilt with dedup. Let me re-extract without dedup.
# Or just check what the extractor returns.
# For now, let me look at the known data:
records_both = [
    # Raw CNY scale
    {"period_end": "2024-12-31", "period_type": "quarter", "revenue": 16105096000.0, "cost_of_sales": None, "gross_profit": 2324777000.0, "operating_income": None, "net_income": None, "eps_diluted": None},
    {"period_end": "2025-09-30", "period_type": "quarter", "revenue": 20380950000.0, "cost_of_sales": None, "gross_profit": 4104253000.0, "operating_income": None, "net_income": None, "eps_diluted": None},
    {"period_end": "2025-12-31", "period_type": "quarter", "revenue": 22253759000.0, "cost_of_sales": None, "gross_profit": 4741806000.0, "operating_income": None, "net_income": None, "eps_diluted": None},
    # Billion scale (from Key Financial Results table)
    {"period_end": "2024-12-31", "period_type": "quarter", "revenue": 16.11, "cost_of_sales": None, "gross_profit": None, "operating_income": None, "net_income": -1.39, "eps_diluted": None},
    {"period_end": "2025-09-30", "period_type": "quarter", "revenue": 20.38, "cost_of_sales": None, "gross_profit": None, "operating_income": None, "net_income": -0.15, "eps_diluted": None},
    {"period_end": "2025-12-31", "period_type": "quarter", "revenue": 22.25, "cost_of_sales": None, "gross_profit": None, "operating_income": None, "net_income": 0.51, "eps_diluted": None},
]

# Group by period
from collections import defaultdict
groups = defaultdict(list)
for r in records_both:
    key = (r["period_end"], r["period_type"])
    groups[key].append(r)

print("Field coverage per group:")
for (end, pt), recs in sorted(groups.items()):
    print(f"\n  {pt} end={end} ({len(recs)} records):")
    all_fields = set()
    for r in recs:
        all_fields.update(k for k, v in r.items() if v is not None)
    for field in sorted(all_fields):
        vals = [(i, r.get(field)) for i, r in enumerate(recs) if r.get(field) is not None]
        print(f"    {field}: {vals}")

# Verify scale: raw_revenue / billion_revenue should be ~1e9
print("\n\nScale verification (raw / billion):")
for (end, pt), recs in sorted(groups.items()):
    raw_recs = [r for r in recs if r["revenue"] and r["revenue"] > 1e6]
    bil_recs = [r for r in recs if r["revenue"] and r["revenue"] < 1000]
    if raw_recs and bil_recs:
        ratio = raw_recs[0]["revenue"] / bil_recs[0]["revenue"]
        print(f"  {pt} {end}: {raw_recs[0]['revenue']} / {bil_recs[0]['revenue']} = {ratio:.0f}")
db.close()
