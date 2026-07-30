"""Test LANE 2 extractor on XPEV fixture."""
import json, sys
from pathlib import Path

sys.path.insert(0, "src")
from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

fixture = Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.html")
meta = json.loads(Path("tests/fixtures/edgar/xpev_6k_fy2025q4_earnings.meta.json").read_text())

extractor = EarningsReleaseExtractor()
data = extractor.extract(fixture.read_bytes(), meta=meta)

print(f"Records extracted: {len(data.records)}")
print("=" * 80)

for r in data.records:
    rev = r.metrics.get("revenue")
    ni = r.metrics.get("net_income")
    gp = r.metrics.get("gross_profit")
    eps = r.metrics.get("eps_diluted")
    rev_str = f"rev={rev/1e9:.2f}B" if rev else "rev=None"
    ni_str = f"ni={ni/1e9:.2f}B" if ni else "ni=None"
    print(f"\n  {r.period_type:12s} {r.period_start} → {r.period_end} [{r.currency}]")
    print(f"  {rev_str} {ni_str}")
    print(f"  fx_rate={r.fx_rate} method={r.extraction_method}")
    print(f"  metrics: {list(r.metrics.keys())}")

# ── Guidance ──
print(f"\nGuidance extracted: {len(data.guidance)}")
print("=" * 80)
for g in data.guidance:
    print(f"\n  {g.period_label} | {g.metric_name} | {g.currency}")
    low_fmt = f"{g.low/1e9:.2f}B" if g.low and g.low > 1e8 else f"{g.low:,.0f}" if g.low else "None"
    high_fmt = f"{g.high/1e9:.2f}B" if g.high and g.high > 1e8 else f"{g.high:,.0f}" if g.high else "None"
    print(f"  range: {low_fmt} ~ {high_fmt}")
    print(f"  yoy: {g.yoy_change_low}% ~ {g.yoy_change_high}%")
    print(f"  conf={g.extraction_conf} source={g.source}")
