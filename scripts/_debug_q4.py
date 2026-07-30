"""Debug Q4 value mismatch."""
import sys, json
sys.path.insert(0, "src")
from pathlib import Path
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

fixture = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html").read_bytes()
meta = json.loads(Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.meta.json").read_text())
ext = EarningsReleaseExtractor()

# Extract WITHOUT dedup to see all raw records
data = ext.extract(fixture, meta=meta)

print(f"Total records (after dedup): {len(data.records)}")
print()

# Check all quarter records before dedup
# We need to look at raw extraction before dedup
# Let's re-run extract but capture pre-dedup
import cagent_os.data_layer.lane2.extractor as mod

# Monkey-patch to capture pre-dedup records
original_extract = ext.extract
all_raw = []

def patched_extract(html_bytes, meta=None):
    result = original_extract(html_bytes, meta)
    return result

# Instead, let's just print what we have
for r in data.records:
    if r.period_type == "quarter":
        rev = r.metrics.get("revenue")
        rev_str = f"{rev/1e9:.2f}B" if rev and rev > 1e6 else f"{rev}"
        mc = len([v for v in r.metrics.values() if v is not None])
        print(f"  {r.period_start} -> {r.period_end} [{r.currency}]")
        print(f"    revenue = {rev_str}, metrics = {mc}")
        print(f"    keys = {list(r.metrics.keys())}")
