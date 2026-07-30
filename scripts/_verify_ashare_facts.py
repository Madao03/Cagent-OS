"""Verify FactRegistry double caliber for A-share adapter."""
import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.fact_registry import FactRegistry
from cagent_os.data_layer.adapters.akshare_financials_adapter import AkshareFinancialsAdapter

adapter = AkshareFinancialsAdapter()
raw = asyncio.run(adapter.fetch("financials", ticker="600519"))
data = raw.value

# Strip reconciliation (mirrors plugin)
if "records" in data:
    for p in data["records"]:
        p.pop("reconciliation", None)

reg = FactRegistry(turn=0)
facts = reg.register_tool_result("financial.ashare.report", data)

print(f"Registered {len(facts)} facts ({reg.stats()})")

# Dual caliber check
for caliber_name in ("净利润", "归属于母公司所有者的净利润", "营业总收入", "营业收入"):
    matches = [f for f in facts if f.caliber and caliber_name in f.caliber]
    if matches:
        for m in matches:
            print(f"  ✓ caliber={m.caliber} value={m.value:,.0f} "
                  f"period={m.period_end} acct_std={m.accounting_standard} "
                  f"source_tier={m.source_tier}")
    else:
        print(f"  ✗ caliber containing '{caliber_name}' NOT FOUND")

# Verify no reconciliation noise
recon_facts = [f for f in facts if "reconciliation" in (f.caliber or "")]
assert not recon_facts, f"Reconciliation leaked into facts: {recon_facts}"
print("\n✓ No reconciliation noise in registry")

# Verify provenance fields on latest quarter
latest_period = sorted(set(f.period_end for f in facts if f.period_end))[-1]
latest_facts = [f for f in facts if f.period_end == latest_period]
print(f"\nLatest period ({latest_period}): {len(latest_facts)} facts")
sample = latest_facts[:5]
for f in sample:
    print(f"  caliber={f.caliber} value={f.value:,.0f} "
          f"acct_std={f.accounting_standard} source_tier={f.source_tier}")
