"""A-share financial report adapter via akshare → East Money.

Covers:
  - Balance sheet (资产负债表)
  - Income statement (利润表)
  - Cash flow statement (现金流量表)

Key design:
  - Unit normalization: 万元→×1e4, 亿元→×1e8 (fixed factor, computed ratio for validation only)
  - period_type: 一季报→quarter, 半年报→cumulative, 三季报→cumulative, 年报→fiscal_year
  - Cumulative → quarterly differencing: IS + CF items only, BS items must NOT be differenced
  - accounting_standard = "CAS"
  - source_tier = "secondary"

See: ASHARE_FINANCIALS_ADAPTER.md + ASHARE_ADAPTER_ADDENDUM.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData
from cagent_os.provenance.fact_registry import (
    PERIOD_TYPE_FISCAL_YEAR, PERIOD_TYPE_QUARTER, PERIOD_TYPE_CUMULATIVE,
)

logger = logging.getLogger(__name__)

# ── Report type → period_type mapping ──────────────────────────
# A-share reports are cumulative by default. 一季报 is the only report
# whose cumulative interval equals its single-quarter interval —
# period_start/end already disambiguate, so we map it to quarter.
# ───┬───────────────────┬───────────────────┬────────────────
# 报告 │ period_start–end  │ period_type        │ 说明
# ───┼───────────────────┼───────────────────┼────────────────
# 一季报│ 1/1–3/31          │ quarter            │ 累计=单季，单季语义更有用
# 半年报│ 1/1–6/30          │ cumulative         │ H1 累计
# 三季报│ 1/1–9/30          │ cumulative         │ 前三季累计
# 年报  │ 1/1–12/31         │ fiscal_year        │ 全年

# akshare report date suffixes
_Q1_SUFFIXES = ("0331", "03-31")   # 一季报截止日
_H1_SUFFIXES = ("0630", "06-30")   # 半年报截止日
_Q3_SUFFIXES = ("0930", "09-30")   # 三季报截止日
_FY_SUFFIXES = ("1231", "12-31")   # 年报截止日

# ── Unit normalization ──────────────────────────────────────────
# Fixed factors only. Computed ratio reserved for validation.

_UNIT_FACTORS: dict[str, float] = {
    "元": 1.0,
    "万元": 1e4,
    "亿元": 1e8,
}

# ── Pipeline blacklist ──────────────────────────────────────────
# Fields from akshare that are metadata, never financial data

_PIPELINE_BLACKLIST = frozenset({
    "序号", "index", "股票代码", "stock_code", "公司名称",
    "报告期", "report_date", "报告日期", "更新时间",
    "update_time", "公告日期", "announce_date",
    "数据来源", "source", "排名", "rank",
    "涨跌幅", "change_pct", "数据条数", "record_count",
})


@dataclass
class FinancialStatement:
    """One period's financial statement for one company."""
    ticker: str                    # 600519
    report_date: str               # "2025-12-31"
    period_start: str              # "2025-01-01"
    period_end: str                # "2025-12-31"
    period_type: str               # "fiscal_year" | "quarter" | "cumulative"
    statement_type: str            # "balance_sheet" | "income" | "cash_flow"
    items: dict[str, float | None] = field(default_factory=dict)
    unit: str = "元"               # original unit from akshare
    source: str = "akshare-sina"
    announcement_url: str = ""


def detect_period_type(report_date: str) -> str:
    """Map A-share report date to period_type.

    report_date format: "YYYY-MM-DD" or "YYYYMMDD"
    """
    d = report_date.replace("-", "")
    if any(d.endswith(s) for s in _FY_SUFFIXES):
        return PERIOD_TYPE_FISCAL_YEAR
    if any(d.endswith(s) for s in _Q1_SUFFIXES):
        return PERIOD_TYPE_QUARTER  # 一季报→quarter
    if any(d.endswith(s) for s in _H1_SUFFIXES):
        return PERIOD_TYPE_CUMULATIVE
    if any(d.endswith(s) for s in _Q3_SUFFIXES):
        return PERIOD_TYPE_CUMULATIVE
    return PERIOD_TYPE_QUARTER  # fallback


def detect_period_range(report_date: str, period_type: str) -> tuple[str, str]:
    """Given report date and period_type, compute period_start/end.

    All A-share reports start from 1/1 of the same year.
    """
    import re
    m = re.match(r"(\d{4})", report_date)
    if not m:
        return ("", "")
    year = int(m.group(1))
    if period_type == PERIOD_TYPE_FISCAL_YEAR:
        return (f"{year}-01-01", f"{year}-12-31")
    if period_type == PERIOD_TYPE_QUARTER:
        return (f"{year}-01-01", f"{year}-03-31")
    if period_type == PERIOD_TYPE_CUMULATIVE:
        if "0630" in report_date or "06-30" in report_date:
            return (f"{year}-01-01", f"{year}-06-30")
        elif "0930" in report_date or "09-30" in report_date:
            return (f"{year}-01-01", f"{year}-09-30")
    return (f"{year}-01-01", report_date)


def _detect_unit_from_values(items: dict[str, float | None]) -> str:
    """Detect unit from the magnitude of values.

    Heuristic: if typical revenue/asset values are in 1e6-1e8 range → 元,
    if in 1e2-1e4 range → 万元, if in 1e0-1e2 range → 亿元.
    """
    vals = [v for v in items.values() if v is not None and abs(v) > 0]
    if not vals:
        return "元"
    max_val = max(abs(v) for v in vals)
    if max_val > 1e8:
        return "元"
    if max_val > 1e4:
        return "万元"
    return "亿元"


def normalize_unit(items: dict[str, float | None], source_unit: str) -> dict[str, float | None]:
    """Normalize all values to 元 using fixed factors.

    Computed ratio (value / expected_magnitude) is ONLY used for validation,
    never for conversion. This prevents rounding error amplification
    (EDGAR dual-scale bug: -1.39e9 computed as -1389576873.99).
    """
    factor = _UNIT_FACTORS.get(source_unit)
    if factor is None:
        logger.warning("Unknown unit %r, assuming 元", source_unit)
        factor = 1.0

    if factor == 1.0:
        return dict(items)

    result: dict[str, float | None] = {}
    for k, v in items.items():
        if v is None:
            result[k] = None
        else:
            result[k] = v * factor
    return result


def validate_unit_detection(items: dict[str, float | None], source_unit: str) -> bool:
    """Validate that the detected unit is consistent with value magnitudes.

    After normalization to 元, typical financial values should be in
    reasonable ranges. If revenue is 0.05 元, the unit was wrong.

    Returns True if unit detection looks correct.
    """
    factor = _UNIT_FACTORS.get(source_unit, 1.0)
    # Check a known large item for sanity
    for key_hint in ("营业总收入", "营业收入", "资产总计", "营业总成本"):
        v = items.get(key_hint)
        if v is not None and abs(v) > 0:
            normalized = abs(v) * factor
            # Revenue/assets should be at least thousands of yuan
            if normalized < 1000:
                logger.warning(
                    "Unit detection may be wrong: %s = %s after ×%.0f = %.2f 元 "
                    "(suspiciously small)",
                    key_hint, v, factor, normalized,
                )
                return False
            return True
    return True  # can't validate, assume OK


# ── Reconciliation ──────────────────────────────────────────────

@dataclass
class ReconResult:
    """Result of triple-statement reconciliation."""
    passed: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, passed: bool, expected: Any = None,
            actual: Any = None, detail: str = "") -> None:
        self.checks.append({
            "name": name, "passed": passed,
            "expected": expected, "actual": actual, "detail": detail,
        })
        if not passed:
            self.passed = False


def reconcile_triple_statements(
    bs: dict[str, float | None],
    income: dict[str, float | None],
    cf: dict[str, float | None],
    prior_bs: dict[str, float | None] | None = None,
) -> ReconResult:
    """Run 6 reconciliation checks across three statements.

    See ASHARE_FINANCIALS_ADAPTER.md §5.

    Args:
        bs: current period balance sheet
        income: current period income statement
        cf: current period cash flow statement
        prior_bs: prior period balance sheet (required for ⑤ ΔRE check)
    """
    r = ReconResult()

    def _v(d: dict, key: str) -> float | None:
        return d.get(key)

    # ① 会计恒等式: 资产 = 负债 + 所有者权益
    assets = _v(bs, "资产总计")
    liabilities = _v(bs, "负债合计")
    # Sina column name: "所有者权益(或股东权益)合计"
    equity = (_v(bs, "股东权益合计") or _v(bs, "所有者权益(或股东权益)合计")
              or _v(bs, "所有者权益"))
    if assets is not None and liabilities is not None and equity is not None:
        rhs = liabilities + equity
        ok = abs(assets - rhs) < abs(assets) * 0.001 if assets != 0 else abs(assets - rhs) < 1
        r.add("① 资产=负债+权益", ok, assets, rhs)
    else:
        r.add("① 资产=负债+权益", False, None, None, "missing fields")

    # ② 现金流勾稽: 期末现金 = 期初现金 + 现金流量净额
    end_cash = _v(cf, "期末现金及现金等价物余额")
    begin_cash = _v(cf, "期初现金及现金等价物余额")
    net_cf = _v(cf, "现金及现金等价物净增加额")
    if end_cash is not None and begin_cash is not None and net_cf is not None:
        expected_cf = begin_cash + net_cf
        ok = abs(end_cash - expected_cf) < abs(end_cash) * 0.005 if end_cash != 0 else abs(end_cash - expected_cf) < 1
        r.add("② 期末现金=期初+净额", ok, end_cash, expected_cf)
    else:
        r.add("② 期末现金=期初+净额", False, None, None, "missing fields")

    # ③ 利润表勾稽: 营业利润 + 营业外收支 − 所得税 ≈ 净利润
    # ★ Use 营业利润 directly — not 营业总收入 − 营业总成本.
    #   营业利润 already includes all operating items below the cost line
    #   (投资收益, 其他收益, 公允价值变动, 减值损失, 资产处置).
    #   For companies with financial subsidiaries (e.g. 茅台), 营业总成本
    #   includes items not captured by simple sum of individual cost accounts.
    #   Using the reported 营业利润 avoids this complexity entirely.
    # Tolerance: 0.01% — the remaining step (营业利润 → 净利润) is just
    #   non-operating items + tax, which should be near-exact.
    op_profit = _v(income, "营业利润")
    non_op = (_v(income, "营业外收入") or 0) - (_v(income, "营业外支出") or 0)
    tax = _v(income, "所得税费用") or 0
    net_profit = _v(income, "净利润")
    if op_profit is not None and net_profit is not None:
        estimated = op_profit + non_op - tax
        denom = abs(op_profit) if abs(op_profit) > abs(net_profit) else abs(net_profit)
        ok = abs(net_profit - estimated) < denom * 0.0001 if denom != 0 else abs(net_profit - estimated) < 1
        gap = net_profit - estimated if not ok else 0
        detail = f"gap={gap:,.0f}" if gap != 0 else ""
        r.add("③ 营业利润→净利润", ok, net_profit, estimated, detail)
    else:
        r.add("③ 营业利润→净利润", False, None, None, "missing fields")

    # ④ 净利润一致: 利润表净利润 = 现金流量表间接法起点
    # Note: CF statement in akshare direct method may not include this.
    # This check is aspirational for MVP.
    _indirect_cf = _v(cf, "净利润")  # if present
    if _indirect_cf is not None and net_profit is not None:
        ok = abs(net_profit - _indirect_cf) < 0.01
        r.add("④ 净利润一致(PL vs CF)", ok, net_profit, _indirect_cf)
    # else: skip — not always available in direct-method CF

    # ⑤ 权益变动: Δ未分配利润 ≈ 归母净利润 − 分红
    # ★ Requires prior-period BS to compute ΔRE.
    # ★ 未分配利润 is a parent-company equity item → should match
    #   归母净利润 (parent-attributable), NOT 净利润 (includes minority).
    re = _v(bs, "未分配利润")
    prior_re = _v(prior_bs, "未分配利润") if prior_bs else None
    parent_np = _v(income, "归属于母公司所有者的净利润") or _v(income, "归属于母公司股东的净利润")
    if re is not None and prior_re is not None and parent_np is not None:
        delta_re = re - prior_re
        # ΔRE ≈ 归母NP (ignoring dividends + OCI for simplicity)
        denom = abs(parent_np) if abs(parent_np) > 0 else 1
        ok = abs(delta_re - parent_np) < denom * 0.02  # 2% for dividend noise
        r.add("⑤ ΔRE≈归母NP", ok,
              f"ΔRE={delta_re:,.0f}", f"归母NP={parent_np:,.0f}")
    elif re is not None and (parent_np or net_profit) is not None:
        # Prior period unavailable — skip honestly
        r.add("⑤ ΔRE≈归母NP", False, None, None,
              "skipped: prior period BS not provided (required for ΔRE)")
    else:
        r.add("⑤ ΔRE≈归母NP", False, None, None, "missing fields")

    # ⑥ Revenue monotonicity for cumulative periods — applied at caller level
    # (requires comparing multiple periods)

    return r


# ── Cumulative → Quarterly Differencing ─────────────────────────

@dataclass
class DifferencedResult:
    """One quarter's differenced values."""
    period_start: str
    period_end: str
    quarter_label: str        # "Q1" | "Q2" | "Q3" | "Q4"
    items: dict[str, float | None] = field(default_factory=dict)
    negative_items: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)  # report dates
    audited: bool = False
    unit: str = "元"


def _flow_items(period: dict, include_cf: bool = True) -> dict[str, float | None]:
    """Extract flow items (IS + optionally CF) from a period dict.

    Only income statement and cash flow items can be differenced.
    Balance sheet items are period-end snapshots — NEVER differenced.
    This is determined by source table, not by item name.
    """
    items: dict[str, float | None] = {}
    # IS items — always flow
    is_items = period.get("is_items", {})
    if isinstance(is_items, dict):
        items.update(is_items)
    # CF items — flow, but optional for Q1 (no prior period to diff against)
    if include_cf:
        cf_items = period.get("cf_items", {})
        if isinstance(cf_items, dict):
            items.update(cf_items)
    return items


def difference_cumulative_periods(
    periods: list[dict[str, Any]],
    fiscal_year: int,
) -> list[DifferencedResult]:
    """Compute single-quarter values from cumulative reports.

    A-share all use cumulative reporting. To get Q2 single-quarter:
        Q2 = 半年报 (H1) − 一季报 (Q1)

    Rules (★ source-table-driven, not name-driven):
      - BS items: NEVER differenced (period-end snapshot)
        → excluded because we only pass is_items + cf_items to _do_diff
      - IS + CF items: differenced (period flow)
      - Negative diff values: flagged, not rejected
      - audited: min(parents)

    Args:
        periods: list of period dicts from _fetch_all, sorted by date.
        fiscal_year: the year to compute quarters for.
    """
    # Index periods by type (cumulative periods disambiguated by period_end)
    by_type: dict[str, dict] = {}
    h1_period = None
    q3_period = None
    for p in periods:
        pt = p.get("period_type", "")
        pe = p.get("period_end", "")
        if pt == PERIOD_TYPE_CUMULATIVE:
            if "06-30" in pe or "0630" in pe:
                h1_period = p
            elif "09-30" in pe or "0930" in pe:
                q3_period = p
        elif pt:
            by_type[pt] = p

    results: list[DifferencedResult] = []

    # ── Q1: 一季报 = quarter, no differencing needed ──
    q1 = by_type.get(PERIOD_TYPE_QUARTER)
    if q1:
        items = _flow_items(q1, include_cf=True)
        audited = q1.get("audited", False)
        results.append(DifferencedResult(
            period_start=f"{fiscal_year}-01-01",
            period_end=f"{fiscal_year}-03-31",
            quarter_label="Q1",
            items=items,
            derived_from=[q1.get("report_date", "")],
            audited=audited,
        ))

    # ── Q2: 半年报 − 一季报 ──
    if h1_period and q1:
        _do_diff(results, h1_period, q1, fiscal_year, "Q2",
                 f"{fiscal_year}-04-01", f"{fiscal_year}-06-30")

    # ── Q3: 三季报 − 半年报 ──
    if q3_period and h1_period:
        _do_diff(results, q3_period, h1_period, fiscal_year, "Q3",
                 f"{fiscal_year}-07-01", f"{fiscal_year}-09-30")

    # ── Q4: 年报 − 三季报 ──
    fy_period = by_type.get(PERIOD_TYPE_FISCAL_YEAR)
    if fy_period and q3_period:
        _do_diff(results, fy_period, q3_period, fiscal_year, "Q4",
                 f"{fiscal_year}-10-01", f"{fiscal_year}-12-31")

    return results


def _do_diff(
    results: list[DifferencedResult],
    later: dict, earlier: dict,
    year: int, quarter: str, start: str, end: str,
) -> None:
    """Compute diff: later.cumulative − earlier.cumulative.

    ★ Only IS and CF items are passed — the caller extracts them via
    _flow_items(). BS items never enter this function. This is fail-closed:
    even if a BS column name changes, it cannot accidentally be differenced
    because it was never in is_items or cf_items to begin with.
    """
    later_items = _flow_items(later, include_cf=True)
    earlier_items = _flow_items(earlier, include_cf=True)

    diff_items: dict[str, float | None] = {}
    negative_items: list[str] = []

    all_keys = set(later_items.keys()) | set(earlier_items.keys())
    for key in all_keys:
        lv = later_items.get(key)
        ev = earlier_items.get(key)
        if lv is not None and ev is not None:
            diff = lv - ev
            diff_items[key] = diff
            if diff < 0:
                negative_items.append(key)
        else:
            diff_items[key] = None

    # audited: min(parents)
    later_audited = later.get("audited", False)
    earlier_audited = earlier.get("audited", False)
    derived_audited = later_audited and earlier_audited

    results.append(DifferencedResult(
        period_start=start,
        period_end=end,
        quarter_label=quarter,
        items=diff_items,
        negative_items=negative_items,
        derived_from=[
            later.get("report_date", ""),
            earlier.get("report_date", ""),
        ],
        audited=derived_audited,
    ))


# ── Adapter ─────────────────────────────────────────────────────

class AkshareFinancialsAdapter(DataSourceAdapter):
    """A-share financial report adapter via akshare → East Money."""

    name = "akshare-financials"
    tier = 1

    # ── DataSourceAdapter interface ──────────────────────────────

    async def fetch(self, metric: str, **params: Any) -> RawData:
        ticker = str(params.get("ticker", "")).strip()
        if not ticker:
            return _missing("ticker")

        try:
            if metric == "financials":
                return await self._fetch_all(ticker)
            if metric == "balance_sheet":
                return await self._fetch_balance_sheet(ticker)
            if metric == "income":
                return await self._fetch_income(ticker)
            if metric == "cash_flow":
                return await self._fetch_cash_flow(ticker)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": f"unsupported metric: {metric}"},
            )
        except Exception as exc:
            logger.exception("akshare financials fetch failed: %s/%s", ticker, metric)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

    async def health_check(self) -> DataSourceHealth:
        try:
            import akshare as ak
            import asyncio
            await asyncio.to_thread(
                ak.stock_financial_report_sina,
                stock="sh600519", symbol="资产负债表",
            )
            return DataSourceHealth(available=True)
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))

    # ── Fetchers ─────────────────────────────────────────────────

    async def _fetch_all(self, ticker: str) -> RawData:
        """Fetch all three statements + normalize + difference + reconcile."""
        import asyncio
        import time as _time

        started = _time.perf_counter()
        symbol = _normalize_ticker(ticker)

        # Fetch three statements in parallel
        bs_raw, income_raw, cf_raw = await asyncio.gather(
            asyncio.to_thread(_fetch_statement, symbol, "balance_sheet"),
            asyncio.to_thread(_fetch_statement, symbol, "income"),
            asyncio.to_thread(_fetch_statement, symbol, "cash_flow"),
        )

        if bs_raw is None and income_raw is None and cf_raw is None:
            return RawData(
                source=self.name, metric="financials", value=None,
                raw_response={"error": "All three statements failed"},
            )

        result: dict[str, Any] = {
            "success": True,
            "ticker": ticker,
            "source": "akshare-sina",
            "source_tier": "secondary",
            "accounting_standard": "CAS",
            "currency": "CNY",
            "audited": False,  # aggregated result, individual periods tagged
            "execution_time": round(_time.perf_counter() - started, 4),
            "records": [],
        }

        # Process each period
        all_dates = set()
        for stmt in [bs_raw, income_raw, cf_raw]:
            if stmt:
                all_dates.update(stmt.keys())

        for date in sorted(all_dates):
            bs = bs_raw.get(date, {}) if bs_raw else {}
            inc = income_raw.get(date, {}) if income_raw else {}
            cf = cf_raw.get(date, {}) if cf_raw else {}

            period_type = detect_period_type(date)
            period_start, period_end = detect_period_range(date, period_type)

            period_data: dict[str, Any] = {
                "period_start": period_start,
                "period_end": period_end,
                "period_type": period_type,
                "report_date": date,
                "currency": "CNY",
                "accounting_standard": "CAS",
                "source_tier": "secondary",
                "audited": (period_type == PERIOD_TYPE_FISCAL_YEAR),
            }
            # ★ Flatten items into record (not nested) — matches EDGAR records pattern
            period_data.update(bs)
            period_data.update(inc)
            period_data.update(cf)

            # Run reconciliation (internal quality check)
            recon = reconcile_triple_statements(bs, inc, cf)
            period_data["reconciliation"] = {
                "passed": recon.passed,
                "checks": recon.checks,
            }
            if not recon.passed:
                # ★ Only warn for recent periods (last 5 years). Historical
                # periods often have missing CF data (pre-2002 Sina coverage).
                year = int(date[:4]) if date else 0
                if year >= 2020:
                    failed = [c["name"] for c in recon.checks if not c["passed"]]
                    logger.warning("Reconciliation failed for %s %s: %s", ticker, date, failed)

            result["records"].append(period_data)

        # ★ P6: Truncate to most recent N periods to avoid overflowing the
        # FactRegistry with decades of historical data. For a "latest net profit"
        # query, 10,204 facts (1998-2026) pollutes derived back-checking and
        # bloats provenance event JSON. 8 periods covers ~2 fiscal years of
        # quarterly + cumulative records — sufficient for any recent-data question.
        MAX_PERIODS = 8
        if len(result["records"]) > MAX_PERIODS:
            result["records"] = result["records"][-MAX_PERIODS:]

        result["record_count"] = len(result["records"])
        return RawData(
            source=self.name, metric="financials", value=result,
            raw_response=result,
        )

    async def _fetch_balance_sheet(self, ticker: str) -> RawData:
        symbol = _normalize_ticker(ticker)
        import asyncio
        try:
            data = await asyncio.to_thread(_fetch_statement, symbol, "balance_sheet")
            return RawData(source=self.name, metric="balance_sheet", value=data)
        except Exception as exc:
            return RawData(source=self.name, metric="balance_sheet", value=None,
                           raw_response={"error": str(exc)})

    async def _fetch_income(self, ticker: str) -> RawData:
        symbol = _normalize_ticker(ticker)
        import asyncio
        try:
            data = await asyncio.to_thread(_fetch_statement, symbol, "income")
            return RawData(source=self.name, metric="income", value=data)
        except Exception as exc:
            return RawData(source=self.name, metric="income", value=None,
                           raw_response={"error": str(exc)})

    async def _fetch_cash_flow(self, ticker: str) -> RawData:
        symbol = _normalize_ticker(ticker)
        import asyncio
        try:
            data = await asyncio.to_thread(_fetch_statement, symbol, "cash_flow")
            return RawData(source=self.name, metric="cash_flow", value=data)
        except Exception as exc:
            return RawData(source=self.name, metric="cash_flow", value=None,
                           raw_response={"error": str(exc)})


# ── Core fetch logic ────────────────────────────────────────────

def _normalize_ticker(ticker: str) -> str:
    """Normalize ticker to Sina format (sh600519 / sz000001)."""
    t = ticker.strip().upper()
    # Remove existing exchange suffix
    for suffix in (".SH", ".SZ", ".BJ"):
        if t.endswith(suffix):
            t = t[:-len(suffix)]
            break
    # Determine exchange prefix
    if t.startswith(("600", "601", "603", "605", "688")):
        return f"sh{t}"
    elif t.startswith(("000", "001", "002", "003", "300")):
        return f"sz{t}"
    elif t.startswith(("4", "8")):
        return f"bj{t}"
    return f"sh{t}"  # default


_STMT_SINA_MAP = {
    "balance_sheet": "资产负债表",
    "income": "利润表",
    "cash_flow": "现金流量表",
}

# Sina-specific metadata columns
_SINA_META_COLS = frozenset({
    "报告日", "数据源", "是否审计", "公告日期", "币种", "类型", "更新日期",
})


def _fetch_statement(symbol: str, stmt_type: str) -> dict[str, dict] | None:
    """Fetch one statement from akshare → Sina Finance.

    Sina returns pivoted DataFrames: rows = report dates, cols = item names.
    Values are in 元 (yuan). No unit normalization needed.

    Returns: {report_date_str: {item_name: value, ...}, ...}
    """
    import akshare as ak
    import pandas as pd

    stmt_name = _STMT_SINA_MAP.get(stmt_type)
    if stmt_name is None:
        return None

    # Use Sina prefix format
    sina_symbol = _normalize_ticker(symbol)

    try:
        df: pd.DataFrame = ak.stock_financial_report_sina(
            stock=sina_symbol, symbol=stmt_name,
        )
    except Exception as exc:
        logger.warning("akshare Sina %s fetch failed for %s: %s", stmt_type, symbol, exc)
        return None

    if df is None or df.empty:
        return None

    result: dict[str, dict] = {}

    for _, row in df.iterrows():
        date_str = _format_date(str(row.get("报告日", "")))
        if not date_str:
            continue

        items: dict[str, float | None] = {}
        for col in df.columns:
            if col in _SINA_META_COLS:
                continue
            val = row.get(col)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and not pd.isna(val):
                items[str(col)] = float(val)

        if items:
            result[date_str] = items

    # Sina returns data in 元 — verify with sanity check
    for date_str, items in result.items():
        unit = _detect_unit_from_values(items)
        if unit != "元":
            logger.warning(
                "Unexpected unit for %s %s: detected %s, values may need normalization",
                symbol, date_str, unit,
            )
            # Still normalize — fixed factor, not computed
            result[date_str] = normalize_unit(items, unit)

    return result


def _looks_like_date(s: str) -> bool:
    """Check if a string looks like a date."""
    import re
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return True
    if re.match(r'^\d{8}$', s):
        return True
    if re.match(r'^\d{4}\.\d{2}\.\d{2}$', s):
        return True
    return False


def _format_date(s: str) -> str:
    """Normalize date string to YYYY-MM-DD."""
    import re
    s = s.strip()
    # YYYY-MM-DD
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    # YYYYMMDD
    if re.match(r'^\d{8}$', s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # YYYY.MM.DD
    if re.match(r'^\d{4}\.\d{2}\.\d{2}$', s):
        return s.replace(".", "-")
    return s


def _missing(reason: str) -> RawData:
    return RawData(source="akshare-financials", metric="financials",
                   value=None, raw_response={"error": f"missing {reason}"})
