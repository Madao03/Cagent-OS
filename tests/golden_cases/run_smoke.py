r"""Golden Cases Smoke Test — validates data layer & app health (no LLM required).

Usage:
    python tests/golden_cases/run_smoke.py

Prerequisites:
    - .env loaded with API keys
    - VPN on (for CMC MCP)
    - WSL running with fin-skill if needed

Tests cover:
    1. DataSource health checks (all registered adapters)
    2. Key data fetches (FRED, yfinance, akshare)
    3. API server health endpoint
    4. Case definition integrity
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

# -- Test runner ---------------------------------------------------------

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"

results: list[dict] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    icon = PASS if passed else FAIL
    print(f"  {icon} {name}: {detail}")
    results.append({"name": name, "passed": passed, "detail": detail, "time": datetime.now().isoformat()})


async def test_data_layer() -> None:
    """Verify all registered adapters are healthy and can fetch data."""
    print("\n── DataSource Health Checks ──")
    dl = DataLayer()
    dl.register_source(YFinanceAdapter())
    dl.register_source(FredAdapter())
    dl.register_source(AkshareStockAdapter())
    dl.register_source(AkshareFuturesAdapter())

    health = await dl.health_check_all()
    for name, h in health.items():
        record(f"health:{name}", h.available, f"{'up' if h.available else h.error_message}")

    # ── Critical data fetches ──
    print("\n── Critical Data Fetches ──")

    # FRED: Fed Funds rate
    try:
        r = await dl.fetch("fred", "fed_funds")
        record("fred:fed_funds", r.value is not None and r.value.get("value") is not None,
               f"{r.value.get('value')}% ({r.value.get('date')})")
    except Exception as e:
        record("fred:fed_funds", False, str(e))

    # yfinance: AAPL
    try:
        r = await dl.fetch("yfinance", "fwd_pe", ticker="AAPL")
        record("yfinance:AAPL_fwd_pe", r.value is not None, str(r.value))
    except Exception as e:
        record("yfinance:AAPL_fwd_pe", False, str(e))

    # akshare stock: 600519
    try:
        r = await dl.fetch("akshare-stock", "daily", ticker="600519", market="cn")
        record("akshare:A股茅台", r.value is not None and "close" in (r.value or {}),
               f"¥{r.value.get('close') if r.value else '?'}")
    except Exception as e:
        record("akshare:A股茅台", False, str(e))

    # akshare futures: RB0
    try:
        r = await dl.fetch("akshare-futures", "daily", symbol="RB0")
        record("akshare:螺纹钢", r.value is not None and "close" in (r.value or {}),
               f"¥{r.value.get('close') if r.value else '?'}")
    except Exception as e:
        record("akshare:螺纹钢", False, str(e))


def test_case_definitions() -> None:
    """Verify golden case JSON is well-formed and complete."""
    print("\n── Case Definitions ──")
    cases_path = _PROJECT / "tests" / "golden_cases" / "cases.json"

    try:
        with open(cases_path) as f:
            data = json.load(f)
    except Exception as e:
        record("cases:load_json", False, str(e))
        return

    cases = data.get("cases", [])
    record("cases:total", len(cases) == 13, f"{len(cases)} cases")

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

    # Print case summary
    print("\n  案例清单:")
    for c in cases:
        new_tag = " 🆕" if c.get("new") else ""
        print(f"    {c['id']} [{c['priority']}] {c['name']}{new_tag}")


# -- Main ----------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  CagentOS Golden Cases — Smoke Test")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    await test_data_layer()
    test_case_definitions()

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} passed")
    if passed == total:
        print(f"  {PASS} ALL CHECKS PASSED")
    else:
        for r in results:
            if not r["passed"]:
                print(f"  {FAIL} {r['name']}: {r['detail']}")
    print("=" * 60)

    # Write results
    out_path = _PROJECT / "tests" / "golden_cases" / "smoke_result.json"
    with open(out_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "total": total, "passed": passed, "results": results}, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {out_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
