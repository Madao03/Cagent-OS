"""Fin-Skill MCP adapter — tier 2 data source.

Wraps fin-skill MCP tools behind the DataSourceAdapter interface.
Primary endpoint: get_stock_analysis (combo: quote + metrics + news).

Known data quality issues:
  - PE forward may differ >30% from yfinance (different data vendors)
  - pe_forward is often null — falls back to None, cross-validator handles this
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cagent_os.data_layer.adapter import DataSourceAdapter, DataSourceHealth, RawData

logger = logging.getLogger(__name__)

# -- Metric → (MCP tool, dotted response path) -------------------------
# Path "" means return full parsed response.
# Path "quote.price" means parsed["quote"]["price"].

_METRIC_TOOL: dict[str, tuple[str, str]] = {
    # Stock analysis (combo endpoint — use first when possible)
    "price":            ("get_stock_analysis", "quote.price"),
    "change_percent":   ("get_stock_analysis", "quote.change_percent"),
    "market_cap":       ("get_stock_analysis", "quote.market_cap"),
    "52w_high":         ("get_stock_analysis", "quote.high_52w"),
    "52w_low":          ("get_stock_analysis", "quote.low_52w"),
    "fwd_pe":           ("get_stock_analysis", "metrics.pe_forward"),
    "ttm_pe":           ("get_stock_analysis", "metrics.pe_ttm"),
    "pb":               ("get_stock_analysis", "metrics.pb"),
    "ps":               ("get_stock_analysis", "metrics.ps"),
    "ev_ebitda":        ("get_stock_analysis", "metrics.ev_ebitda"),
    "peg":              ("get_stock_analysis", "metrics.peg_ratio"),
    "roe":              ("get_stock_analysis", "metrics.roe"),
    "roa":              ("get_stock_analysis", "metrics.roa"),
    "dividend_yield":   ("get_stock_analysis", "metrics.dividend_yield"),
    "stock_analysis":   ("get_stock_analysis", ""),
    # Financial statements
    "financials":       ("get_financials", ""),
    "revenue":          ("get_financials", "financials.0.revenue"),
    "net_income":       ("get_financials", "financials.0.net_income"),
    "eps":              ("get_financials", "financials.0.eps"),
    "gross_margin":     ("get_financials", "financials.0.gross_margin"),
    "net_margin":       ("get_financials", "financials.0.net_margin"),
    # Individual endpoints
    "quote":            ("get_stock_quote", ""),
    "company_news":     ("get_company_news", ""),
    "market_news":      ("get_market_news", ""),
    "klines":           ("get_asset_klines", ""),
}


class FinSkillAdapter(DataSourceAdapter):
    name = "fin-skill"
    tier = 2
    server_name = "fin-skill-mcp"

    def __init__(self, session_manager: Any) -> None:
        self._sessions = session_manager

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    async def fetch(self, metric: str, **params: Any) -> RawData:
        tool_name, path = _METRIC_TOOL.get(metric, (None, ""))
        if tool_name is None:
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": f"unsupported metric: {metric}"},
            )

        ticker = params.get("ticker", params.get("symbol", ""))
        if not ticker:
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": "missing ticker parameter"},
            )

        args = self._build_args(tool_name, ticker)

        try:
            result = await self._sessions.call_tool(
                self.server_name, tool_name, args
            )
            parsed = self._parse_result(result)
        except Exception as exc:
            logger.warning("fin-skill fetch failed: %s/%s — %s", ticker, metric, exc)
            return RawData(
                source=self.name, metric=metric, value=None,
                raw_response={"error": str(exc)},
            )

        value = self._extract(parsed, path) if path else parsed
        return RawData(
            source=self.name, metric=metric, value=value,
            raw_response=parsed,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_args(tool: str, ticker: str) -> dict:
        """Build minimal MCP tool arguments."""
        base = {"symbol": ticker}
        if tool == "get_financials":
            base["fiscal_year"] = 2025
            base["limit"] = 2
            base["period_type_id"] = 1
        return base

    @staticmethod
    def _parse_result(result: Any) -> Any:
        """Parse MCP CallToolResult into a Python dict."""
        content = getattr(result, "content", [])
        if not content:
            return None
        first = content[0]
        text = getattr(first, "text", None)
        if text is None:
            return str(first)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    @staticmethod
    def _extract(data: Any, path: str) -> Any:
        """Walk a dotted path into a nested dict. "_instructions" keys are skipped."""
        if not path or data is None:
            return data
        if not isinstance(data, dict):
            return None
        for key in path.split("."):
            if isinstance(data, dict):
                # numeric key → list index
                try:
                    idx = int(key)
                    data = data[idx] if isinstance(data, list) else data.get(key)
                except ValueError:
                    data = data.get(key)
            else:
                return None
        return data

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> DataSourceHealth:
        try:
            tools = await self._sessions.list_tools(self.server_name)
            if tools:
                return DataSourceHealth(available=True)
            return DataSourceHealth(available=False, error_message="no tools listed")
        except Exception as exc:
            return DataSourceHealth(available=False, error_message=str(exc))
