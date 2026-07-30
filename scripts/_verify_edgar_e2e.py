"""End-to-end test: simulate agent calling financial.edgar.facts for XPEV.

NOTE: This runs synchronously (no asyncio.run wrapper) to match how the
plugin handler is actually called in production.
"""
import sys
sys.path.insert(0, "src")

from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.config import get_settings

def main():
    settings = get_settings()
    plugin = FinancialPlugin(settings=settings)

    # Simulate what the agent would do: call financial.edgar.facts
    print("=" * 60)
    print("E2E Test: agent asks '小鹏最新年度营收多少'")
    print("→ should call financial.edgar.facts(ticker='XPEV')")
    print("=" * 60)

    result = plugin._handle_edgar_facts({"ticker": "XPEV"})
    print(f"\nsource: {result.get('source')}")
    print(f"name: {result.get('name')}")
    print(f"entity_type: {result.get('entity_type')}")
    print(f"currency: {result.get('currency')}")
    print(f"degraded_from: {result.get('degraded_from', 'none')}")

    metrics = result.get("metrics", {})
    if "revenue" in metrics:
        rev = metrics["revenue"]
        cur = result.get("currency", "USD")
        symbol = "¥" if cur in ("CNY", "RMB") else "$"
        print(f"\nrevenue: {symbol}{rev['value']/1e6:.0f}M {cur}")
        print(f"  period: {rev.get('start_date')} → {rev.get('end_date')}")
        print(f"  form: {rev['form']}, audited: {rev['audited']}")
        print(f"  tag_used: {rev.get('tag_used')}")
        print(f"  accession: {rev.get('accession')}")

    # Verification checklist #10
    print("\n" + "=" * 60)
    print("Verification #10: XPEV period correctness")
    print("=" * 60)
    if "revenue" in metrics:
        rev = metrics["revenue"]
        end = rev.get("end_date", "")
        val = rev["value"]
        if end[:4] == "2025" and val > 70e9 and val < 90e9:
            print(f"PASS: end_date={end}, value=¥{val/1e6:.0f}M — correct FY2025 range")
        else:
            print(f"FAIL: end_date={end}, value=¥{val/1e6:.0f}M — expected FY2025, ¥70-90B range")

    # Verification #11: AAPL tag fallback
    print("\n" + "=" * 60)
    print("Verification #11: AAPL tag fallback")
    print("=" * 60)
    aapl = plugin._handle_edgar_facts({"ticker": "AAPL"})
    if "revenue" in aapl.get("metrics", {}):
        rev = aapl["metrics"]["revenue"]
        val = rev["value"]
        tag = rev.get("tag_used", "")
        end = rev.get("end_date", "")
        if val > 390e9 and end[:4] == "2025":
            print(f"PASS: value=${val/1e9:.1f}B, tag={tag}, end={end} — correct FY2025")
        else:
            print(f"FAIL: value=${val/1e9:.1f}B, tag={tag}, end={end} — expected ~$391B+ FY2025")

main()
