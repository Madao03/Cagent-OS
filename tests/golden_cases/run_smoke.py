r"""Golden Cases Smoke Test — validates ALL data sources & app health.

Usage:
    python tests/golden_cases/run_smoke.py

Covers all 10 data sources shown on the "关于" page:
    EDGAR · akshare (3 entries) · FRED · Coin Metrics · Binance
    DeFiLlama · alternative.me · PANews · yfinance · 知识库 (RAG)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# -- Bootstrap -----------------------------------------------------------
_PROJECT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT / "src"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=str(_PROJECT / ".env"))

from cagent_os.data_layer import DataLayer
from cagent_os.data_layer.adapters import (
    YFinanceAdapter,
    FredAdapter,
    AkshareStockAdapter,
    AkshareFuturesAdapter,
)
from cagent_os.data_layer.adapters.akshare_financials_adapter import AkshareFinancialsAdapter
from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter
from cagent_os.data_layer.adapters.coinmetrics_adapter import CoinMetricsAdapter
from cagent_os.data_layer.adapters.binance_derivatives_adapter import BinanceDerivativesAdapter
from cagent_os.data_layer.adapters.defillama_adapter import DefiLlamaAdapter
from cagent_os.data_layer.adapters.fear_greed_adapter import FearGreedAdapter

# -- Test runner ---------------------------------------------------------

PASS = "\u2705"
FAIL = "\u274c"
SKIP = "\u23ed\ufe0f"

results: list[dict] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    icon = PASS if passed else FAIL
    print(f"  {icon} {name}: {detail}")
    results.append({"name": name, "passed": passed, "detail": detail, "time": datetime.now().isoformat()})


# ── Data Layer Health Checks ─────────────────────────────────────

async def test_data_layer() -> None:
    print("\n── Data Layer Health Checks (9 adapters) ──")
    fred_key = os.environ.get("FRED_API_KEY", "")
    dl = DataLayer()
    dl.register_source(YFinanceAdapter())
    dl.register_source(FredAdapter(api_key=fred_key))
    dl.register_source(AkshareStockAdapter())
    dl.register_source(AkshareFuturesAdapter())
    dl.register_source(AkshareFinancialsAdapter())
    dl.register_source(EdgardAdapter())
    dl.register_source(CoinMetricsAdapter())
    dl.register_source(BinanceDerivativesAdapter())
    dl.register_source(DefiLlamaAdapter())
    dl.register_source(FearGreedAdapter())

    health = await dl.health_check_all()
    for name, h in health.items():
        record(f"health:{name}", h.available, f"{'up' if h.available else h.error_message}")


# ── Critical Data Fetches ────────────────────────────────────────

async def test_critical_fetches() -> None:
    """Fetch a representative sample from each source to verify they produce data."""
    print("\n── Critical Data Fetches ──")
    fred_key = os.environ.get("FRED_API_KEY", "")
    dl = DataLayer()
    dl.register_source(YFinanceAdapter())
    dl.register_source(FredAdapter(api_key=fred_key))
    dl.register_source(AkshareStockAdapter())
    dl.register_source(AkshareFuturesAdapter())
    dl.register_source(AkshareFinancialsAdapter())
    dl.register_source(EdgardAdapter())
    dl.register_source(CoinMetricsAdapter())
    dl.register_source(BinanceDerivativesAdapter())
    dl.register_source(DefiLlamaAdapter())
    dl.register_source(FearGreedAdapter())

    # -- yfinance: AAPL forward PE --
    try:
        r = await dl.fetch("yfinance", "fwd_pe", ticker="AAPL")
        record("fetch:yfinance/AAPL_fwd_pe", r.value is not None, str(r.value))
    except Exception as e:
        record("fetch:yfinance/AAPL_fwd_pe", False, str(e))

    # -- FRED: Unemployment rate --
    try:
        r = await dl.fetch("fred", "unemployment_rate")
        ok = r.value is not None
        record("fetch:fred/unemployment_rate",
               ok, f"{r.value}%" if ok else "None")
    except Exception as e:
        record("fetch:fred/unemployment_rate", False, str(e))

    # -- akshare stock: 茅台 daily --
    try:
        r = await dl.fetch("akshare-stock", "daily", ticker="600519", market="cn")
        record("fetch:akshare-stock/600519",
               r.value is not None and "close" in (r.value or {}),
               f"¥{r.value.get('close') if r.value else '?'}")
    except Exception as e:
        record("fetch:akshare-stock/600519", False, str(e))

    # -- akshare futures: 螺纹钢 RB0 --
    try:
        r = await dl.fetch("akshare-futures", "daily", symbol="RB0")
        record("fetch:akshare-futures/RB0",
               r.value is not None and "close" in (r.value or {}),
               f"¥{r.value.get('close') if r.value else '?'}")
    except Exception as e:
        record("fetch:akshare-futures/RB0", False, str(e))

    # -- akshare financials: 茅台 balance_sheet --
    try:
        r = await dl.fetch("akshare-financials", "balance_sheet", ticker="600519")
        ok = r.value is not None and isinstance(r.value, dict) and len(r.value) > 0
        record("fetch:akshare-financials/600519_bs",
               ok, f"{len(r.value)} items" if ok else str(r.value)[:80])
    except Exception as e:
        record("fetch:akshare-financials/600519_bs", False, str(e))

    # -- EDGAR: AAPL revenue --
    try:
        r = await dl.fetch("edgar", "revenue", ticker="AAPL")
        ok = r.value is not None
        record("fetch:edgar/AAPL_revenue",
               ok, f"{r.value:,}" if ok else "None")
    except Exception as e:
        record("fetch:edgar/AAPL_revenue", False, str(e))

    # -- Coin Metrics: BTC MVRV --
    try:
        r = await dl.fetch("coinmetrics", "mvrv", asset="BTC")
        ok = r.value is not None and isinstance(r.value, dict)
        record("fetch:coinmetrics/BTC_mvrv",
               ok, str(r.value)[:100] if ok else "None")
    except Exception as e:
        record("fetch:coinmetrics/BTC_mvrv", False, str(e))

    # -- Binance: BTC funding rate --
    try:
        r = await dl.fetch("binance_derivatives", "funding", symbol="BTCUSDT")
        ok = r.value is not None and isinstance(r.value, dict)
        record("fetch:binance_derivatives/BTC_funding",
               ok, str(r.value)[:100] if ok else "None")
    except Exception as e:
        record("fetch:binance_derivatives/BTC_funding", False, str(e))

    # -- DeFiLlama: global TVL --
    try:
        r = await dl.fetch("defillama", "tvl", protocol="all")
        ok = r.value is not None and isinstance(r.value, dict)
        has_tvl = ok and "tvl" in r.value
        record("fetch:defillama/global_tvl",
               ok and has_tvl,
               f"${r.value.get('tvl'):,}" if has_tvl else str(r.value)[:80])
    except Exception as e:
        record("fetch:defillama/global_tvl", False, str(e))

    # -- Fear & Greed: current index --
    try:
        r = await dl.fetch("fear_greed", "index")
        ok = r.value is not None and isinstance(r.value, dict)
        has_value = ok and "value" in r.value
        record("fetch:fear_greed/index",
               ok and has_value,
               f"{r.value.get('value')}/{r.value.get('classification')}" if has_value else str(r.value)[:80])
    except Exception as e:
        record("fetch:fear_greed/index", False, str(e))


# ── PANews API Check ─────────────────────────────────────────────

async def test_panews() -> None:
    """Verify PANews API is reachable (public endpoint, no key)."""
    print("\n── PANews API ──")
    try:
        from cagent_os.plugins.panews.client import PanewsClient
        client = PanewsClient(timeout=10.0)
        # Lightweight call: get trending
        result = await asyncio.to_thread(client.get_rankings, take=1)
        ok = isinstance(result, dict) and result.get("success")
        has_data = ok and isinstance(result.get("articles"), list)
        record("panews:rankings",
               has_data,
               f"OK ({len(result.get('articles', []))} articles)" if has_data else str(result)[:100])
        client.close()
    except Exception as e:
        record("panews:rankings", False, str(e))


# ── RAG Status Check ─────────────────────────────────────────────

def test_rag() -> None:
    """Verify RAG (knowledge base) is loaded and available."""
    print("\n── RAG / Knowledge Base ──")
    try:
        from cagent_os.rag.rag_service import RAGService
        rag = RAGService(knowledge_dir="knowledge", chroma_path="data/vectors")
        status = rag.status
        ok = status.get("available", False)
        record("rag:status",
               ok,
               f"chunks={status.get('chunks')}, model={status.get('embedding_model')}")
    except Exception as e:
        record("rag:status", False, str(e))


# ── Case Definitions ─────────────────────────────────────────────

def test_case_definitions() -> None:
    """Verify golden case JSON is well-formed and complete."""
    print("\n── Case Definitions ──")
    cases_path = _PROJECT / "tests" / "golden_cases" / "cases.json"

    try:
        with open(cases_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        record("cases:load_json", False, str(e))
        return

    cases = data.get("cases", [])
    record("cases:total", len(cases) >= 13, f"{len(cases)} cases")

    scenarios_seen: set[str] = set()
    priorities_ok = True
    for c in cases:
        cid = c.get("id", "?")
        if not c.get("query"):
            record(f"cases:{cid}:query", False, "missing query")
        if not c.get("pass_criteria"):
            record(f"cases:{cid}:criteria", False, "missing criteria")
        scenarios_seen.add(c.get("scenario", ""))
        if c.get("priority") not in ("P0", "P1"):
            priorities_ok = False

    record("cases:scenarios", len(scenarios_seen) >= 7, f"{len(scenarios_seen)} scenarios")
    record("cases:priorities", priorities_ok, "all P0 or P1")

    print("\n  案例清单:")
    for c in cases:
        new_tag = " [新]" if c.get("new") else ""
        print(f"    {c['id']} [{c['priority']}] {c['name']}{new_tag}")


# ── Main ─────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("  CagentOS Golden Cases — Smoke Test")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Phase 1: Data layer
    await test_data_layer()
    await test_critical_fetches()

    # Phase 2: PANews & RAG (non-DataLayer sources)
    try:
        await test_panews()
    except Exception as e:
        record("panews:general", False, str(e))

    try:
        test_rag()
    except Exception as e:
        record("rag:general", False, str(e))

    # Phase 3: Case definitions
    test_case_definitions()

    # ── Summary ──
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} passed")
    if passed == total:
        print(f"  {PASS} ALL CHECKS PASSED")
    else:
        print(f"\n  Failed checks:")
        for r in results:
            if not r["passed"]:
                print(f"  {FAIL} {r['name']}: {r['detail']}")
    print("=" * 60)

    # Write results
    out_path = _PROJECT / "tests" / "golden_cases" / "smoke_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": total, "passed": passed,
            "results": results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {out_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
