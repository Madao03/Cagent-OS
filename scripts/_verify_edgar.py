"""Verify EDGAR adapter — key tests from EDGAR_ADAPTER.md §8."""
import asyncio
import sys

sys.path.insert(0, "src")

from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter

async def main():
    adapter = EdgardAdapter()

    # ── Test 1: Health check ──
    print("=" * 60)
    print("Test 1: Health check")
    health = await adapter.health_check()
    print(f"  available: {health.available}")
    print(f"  latency_ms: {health.latency_ms}")
    print(f"  error: {health.error_message}")
    assert health.available, "EDGAR not reachable!"

    # ── Test 2: ticker → CIK ──
    print("\n" + "=" * 60)
    print("Test 2: Ticker → CIK mapping")
    cik = adapter._ticker_to_cik("AAPL")
    print(f"  AAPL → CIK: {cik}")
    assert cik == "0000320193", f"Expected 0000320193, got {cik}"

    cik_nvda = adapter._ticker_to_cik("NVDA")
    print(f"  NVDA → CIK: {cik_nvda}")

    # ── Test 3: companyfacts (Happy path — AAPL revenue) ──
    print("\n" + "=" * 60)
    print("Test 3: AAPL companyfacts — revenue")
    summary = await adapter.get_earnings_summary("AAPL")
    print(f"  name: {summary.get('name')}")
    print(f"  entity_type: {summary.get('entity_type')}")
    print(f"  taxonomy: {summary.get('taxonomy')}")
    metrics = summary.get("metrics", {})
    print(f"  metrics found: {list(metrics.keys())}")

    if "revenue" in metrics:
        rev = metrics["revenue"]
        print(f"  revenue: ${rev['value']/1e9:.1f}B (FY{rev['fiscal_year']} {rev['fiscal_period']})")
        print(f"    form: {rev['form']}, audited: {rev['audited']}")
        print(f"    filed: {rev['filed_date']}")
        print(f"    accession: {rev['accession']}")

    if "eps_diluted" in metrics:
        eps = metrics["eps_diluted"]
        print(f"  eps_diluted: ${eps['value']:.2f} (FY{eps['fiscal_year']})")

    if "net_income" in metrics:
        ni = metrics["net_income"]
        print(f"  net_income: ${ni['value']/1e9:.1f}B (FY{ni['fiscal_year']})")

    # ── Test 4: NVDA (different company) ──
    print("\n" + "=" * 60)
    print("Test 4: NVDA companyfacts")
    nvda = await adapter.get_earnings_summary("NVDA")
    print(f"  name: {nvda.get('name')}")
    nvda_metrics = nvda.get("metrics", {})
    print(f"  metrics found: {list(nvda_metrics.keys())}")
    if "revenue" in nvda_metrics:
        rev = nvda_metrics["revenue"]
        print(f"  revenue: ${rev['value']/1e9:.1f}B (FY{rev['fiscal_year']} {rev['fiscal_period']})")

    # ── Test 5: BABA (large FPI) ──
    print("\n" + "=" * 60)
    print("Test 5: BABA (foreign issuer — should be 20-F)")
    try:
        baba = await adapter.get_earnings_summary("BABA")
        print(f"  name: {baba.get('name')}")
        print(f"  entity_type: {baba.get('entity_type')}")
        print(f"  taxonomy: {baba.get('taxonomy')}")
        print(f"  currency: {baba.get('currency')}")
        baba_metrics = baba.get("metrics", {})
        if "revenue" in baba_metrics:
            rev = baba_metrics["revenue"]
            cur = baba.get("currency", "USD")
            val = rev["value"]
            if cur in ("CNY", "RMB", "CNH"):
                print(f"  revenue: ¥{val/1e9:.1f}B {cur} (FY{rev['fiscal_year']})")
            else:
                print(f"  revenue: ${val/1e9:.1f}B {cur} (FY{rev['fiscal_year']})")
    except Exception as e:
        print(f"  BABA test error: {e}")

    # ── Test 6: XPEV (FPI with RMB reporting) ──
    print("\n" + "=" * 60)
    print("Test 6: XPEV (中概股 — 20-F, likely RMB)")
    try:
        xpev = await adapter.get_earnings_summary("XPEV")
        print(f"  name: {xpev.get('name')}")
        print(f"  entity_type: {xpev.get('entity_type')}")
        print(f"  taxonomy: {xpev.get('taxonomy')}")
        print(f"  currency: {xpev.get('currency')}")
        xpev_metrics = xpev.get("metrics", {})
        print(f"  metrics found: {list(xpev_metrics.keys())}")
        if "revenue" in xpev_metrics:
            rev = xpev_metrics["revenue"]
            cur = xpev.get("currency", "USD")
            val = rev["value"]
            if cur in ("CNY", "RMB", "CNH"):
                print(f"  revenue: ¥{val/1e6:.0f}M {cur} (FY{rev['fiscal_year']} {rev['fiscal_period']})")
            else:
                print(f"  revenue: ${val/1e6:.0f}M {cur} (FY{rev['fiscal_year']} {rev['fiscal_period']})")
            print(f"    form: {rev['form']}, audited: {rev['audited']}")
    except Exception as e:
        print(f"  XPEV test error: {e}")

    print("\n" + "=" * 60)
    print("All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
