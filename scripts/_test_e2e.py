"""End-to-end test: financial.edgar.release on XPEV Q4 2025."""
import sys, json
sys.path.insert(0, "src")
from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.config.settings import Settings

plugin = FinancialPlugin(settings=Settings(), toolkit=None, data_layer=None, memory_api=None, rag_service=None)

result = plugin._dispatch("financial.edgar.release", {
    "ticker": "XPEV",
    "quarter_end": "2025-12-31",
})

if result["success"]:
    print(f"Ticker: {result['ticker']}")
    print(f"Quarter: {result['quarter_end']}")
    print(f"Source: {result['source']}")
    print(f"Accession: {result['accession']}")
    print(f"Document: {result['document']}")
    print(f"Filing Date: {result['filing_date']}")
    print(f"Conf: {result['conf']}")
    print(f"Audited: {result['audited']}")
    print(f"Time: {result['execution_time']}s")
    print(f"\nRecords: {result['record_count']}")
    for r in result["records"]:
        rev = r.get("revenue")
        rev_str = f"¥{rev/1e9:.2f}B" if rev and r.get("currency") == "CNY" else f"${rev/1e9:.2f}B" if rev else "None"
        ni = r.get("net_income")
        ni_str = f"¥{ni/1e9:.2f}B" if ni else "None"
        print(f"  {r['period_type']:12s} {r['period_start']} → {r['period_end']} | {rev_str} | {r['currency']} | method={r['extraction_method']}")

    print(f"\nGuidance: {result['guidance_count']}")
    for g in result["guidance"]:
        print(f"  {g['period_label']} | {g['metric_name']} | {g['currency']} | {g['low']:,.0f}~{g['high']:,.0f} | YoY {g['yoy_change_low']}%~{g['yoy_change_high']}%")
else:
    print(f"FAILED: {result.get('error')} - {result.get('message')}")
