import sys
sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding='utf-8')
from cagent_os.provenance.fact_registry import FactRegistry

reg = FactRegistry(turn=0)
test = {
    "success": True,
    "accounting_standard": "CAS",
    "source_tier": "secondary",
    "currency": "CNY",
    "records": [{
        "period_end": "2026-03-31",
        "period_type": "quarter",
        "净利润": 28153831490.0,
        "归属于母公司所有者的净利润": 27242512886.0,
    }]
}
facts = reg.register_tool_result("financial.ashare.report", test)
print(f"facts: {len(facts)}")
for f in facts:
    period = getattr(f, 'period_end', 'N/A')
    acct = getattr(f, 'accounting_standard', 'N/A')
    st = getattr(f, 'source_tier', 'N/A')
    print(f"  {f.id} caliber={f.caliber} value={f.value} period={period} acct={acct} src_tier={st}")
