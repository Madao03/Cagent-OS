"""Verify accounting_standard on real EDGAR data — FPI ≠ IFRS."""
import sys, asyncio
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "src")
from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter, _TAXONOMY_TO_STANDARD

async def check():
    adapter = EdgardAdapter()
    
    # XPEV — FPI but us-gaap
    facts = await adapter.get_company_facts("XPEV")
    standard = _TAXONOMY_TO_STANDARD.get(facts.taxonomy, "")
    print(f"XPEV: entity_type={facts.entity_type} taxonomy={facts.taxonomy} → {standard}")
    assert standard == "US_GAAP", f"XPEV should be US_GAAP, got {standard}"
    print("  PASSED — FPI but us-gaap → US_GAAP (not IFRS)")

    # BABA — FPI but us-gaap
    facts2 = await adapter.get_company_facts("BABA")
    standard2 = _TAXONOMY_TO_STANDARD.get(facts2.taxonomy, "")
    print(f"BABA: entity_type={facts2.entity_type} taxonomy={facts2.taxonomy} → {standard2}")
    assert standard2 == "US_GAAP", f"BABA should be US_GAAP, got {standard2}"
    print("  PASSED — FPI but us-gaap → US_GAAP (not IFRS)")

    # TSLA — domestic US
    facts3 = await adapter.get_company_facts("TSLA")
    standard3 = _TAXONOMY_TO_STANDARD.get(facts3.taxonomy, "")
    print(f"TSLA: entity_type={facts3.entity_type} taxonomy={facts3.taxonomy} → {standard3}")
    assert standard3 == "US_GAAP", f"TSLA should be US_GAAP, got {standard3}"
    print("  PASSED")

    # get_earnings_summary includes accounting_standard — verify at summary level
    summary = await adapter.get_earnings_summary("XPEV", fiscal_year=2025, fiscal_period="FY")
    as_val = summary.get("accounting_standard", "MISSING")
    print(f"get_earnings_summary accounting_standard: {as_val}")
    assert not as_val == "MISSING", "accounting_standard missing from summary"
    print("  PASSED — accounting_standard present in summary")

    print("\nALL CHECKS PASSED")

asyncio.run(check())
