"""Verify XPEV currency situation: CNY vs USD units coverage."""
import asyncio, sys, json
sys.path.insert(0, "src")
import requests
from cagent_os.data_layer.adapters.edgar_adapter import _HEADERS, _BASE_DATA, EdgardAdapter

async def main():
    adapter = EdgardAdapter()
    cik = adapter._ticker_to_cik("XPEV")
    print(f"XPEV CIK: {cik}")

    # Fetch raw companyfacts
    resp = requests.get(f"{_BASE_DATA}/api/xbrl/companyfacts/CIK{cik}.json", headers=_HEADERS, timeout=30)
    data = resp.json()
    facts = data.get("facts", {})

    # Check both taxonomies
    for tax in ["us-gaap", "ifrs-full", "dei"]:
        if tax not in facts:
            print(f"\n{tax}: NOT PRESENT")
            continue
        print(f"\n{tax}: present")
        if tax == "dei":
            # Check reporting currency
            for tag in ["EntityReportingCurrencyISOCode", "EntityFunctionalCurrency"]:
                if tag in facts["dei"]:
                    units = facts["dei"][tag].get("units", {})
                    for uk, items in units.items():
                        latest = items[-1] if items else {}
                        print(f"  {tag}: unit={uk}, latest value={latest.get('val')}")
            continue
        # Check revenue tag units
        for tag in ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "ProfitLoss", "NetIncomeLoss"]:
            if tag not in facts[tax]:
                continue
            units = facts[tax][tag].get("units", {})
            print(f"  {tag}:")
            for uk, items in sorted(units.items()):
                # Count periods and year range
                years = set()
                for item in items:
                    fy = item.get("fy")
                    if fy: years.add(fy)
                year_range = f"{min(years)}-{max(years)}" if years else "?"
                print(f"    unit={uk}: {len(items)} entries, years={year_range} ({len(years)} distinct FYs)")

asyncio.run(main())
