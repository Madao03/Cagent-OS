"""Test: does FactRegistry._extract_from_dict properly extract records[] fields?"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")

from cagent_os.provenance.fact_registry import FactRegistry

# Simulate an edgar.release response with one record
test_data = {
    "success": True,
    "ticker": "XPEV",
    "quarter_end": "2026-03-31",
    "source": "edgar_release",
    "accession": "0001193125-26-215961",
    "document": "d100580dex991.htm",
    "filing_date": "2026-05-28",
    "form": "6-K",
    "conf": 0.75,
    "audited": False,
    "records": [
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_type": "Q1",
            "currency": "CNY",
            "fx_rate": 7.25,
            "fx_rate_date": "2026-03-31",
            "revenue": 13030000000.0,
            "cost_of_sales": 10340000000.0,
            "gross_profit": 2690000000.0,
            "operating_income": -1780000000.0,
            "net_income": -1780000000.0,
            "eps_diluted": -0.98,
            "extraction_method": "table_keyword_match",
        }
    ],
    "guidance": [
        {
            "period_label": "Q2 2026",
            "metric_name": "Total Revenue",
            "low": 19600000000.0,
            "high": 20800000000.0,
            "currency": "CNY",
            "yoy_change_low": 7.0,
            "yoy_change_high": 14.0,
            "extraction_conf": 0.85,
        }
    ],
    "record_count": 1,
    "guidance_count": 1,
    "execution_time": 0.5,
}

registry = FactRegistry(turn=1)
facts = registry._extract_from_dict("financial.edgar.release", test_data, {"ticker": "XPEV"})

print(f"Total facts extracted: {len(facts)}")
print()
for f in facts:
    print(f"  [{f.kind}] caliber={f.caliber} value={f.value} source={f.source} currency={f.currency} audited={f.audited}")

# Check: did we get revenue?
revenue_facts = [f for f in facts if f.caliber == "revenue"]
print(f"\nRevenue facts: {len(revenue_facts)}")
for f in revenue_facts:
    print(f"  value={f.value} currency={f.currency}")

# Check: did we get guidance?
guidance_facts = [f for f in facts if "low" in f.caliber or "high" in f.caliber]
print(f"\nGuidance facts: {len(guidance_facts)}")
for f in guidance_facts:
    print(f"  caliber={f.caliber} value={f.value}")

# Check pipeline noise
noise_keys = {"conf", "record_count", "guidance_count", "execution_time"}
noise_facts = [f for f in facts if f.caliber in noise_keys]
print(f"\nPipeline noise (should be 0): {len(noise_facts)}")
for f in noise_facts:
    print(f"  caliber={f.caliber} value={f.value}")
