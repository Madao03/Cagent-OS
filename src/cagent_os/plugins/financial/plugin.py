from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from cagent_os.plugins.contracts import ToolRequest, ToolResult, ToolTrustLevel
from cagent_os.plugins.manifests import ToolSpec, PluginSpec
from cagent_os.config import Settings
from cagent_os.plugins.financial.toolkit import FinancialToolkit, build_financial_toolkit
from cagent_os.plugins.plugin import Plugin

logger = logging.getLogger(__name__)

KNOWN_FINANCE_ERROR_CODES = {
    "finance_data_unavailable",
    "finance_provider_error",
    "invalid_finance_request",
    "no_symbol",
    "finance_timeout",
    "finance_empty_result",
}

FINANCIAL_WEBSEARCH_CAPABILITY_ID = "financial.websearch"


class FinancialPlugin(Plugin):
    def __init__(self, settings: Settings, toolkit: FinancialToolkit | None = None, data_layer: Any = None) -> None:
        self._settings = settings
        self._toolkit = toolkit or build_financial_toolkit(settings)
        self._data_layer = data_layer

    def manifest(self) -> PluginSpec:
        capabilities = [
            self._manifest(
                FINANCIAL_WEBSEARCH_CAPABILITY_ID,
                "Search finance-aware public web sources across providers.",
                {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer", "default": 10},
                    "provider_params": {"type": "object"},
                },
                required=["query"],
            ),
            # financial.news.search_es — disabled (requires ES cluster, always stub in Phase 1)
            self._manifest(
                "financial.earnings.query",
                "Query financial report data for one or more symbols, including multi-period comparisons.",
                {
                    "question": {"type": "string"},
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "period_type": {"type": "string", "default": "quarterly"},
                    "calendar_year": {"type": "integer"},
                    "calendar_quarter": {"type": "string"},
                    "calendar_years": {"type": "array", "items": {"type": "integer"}},
                    "recent_count": {"type": "integer"},
                },
            ),
            self._manifest(
                "financial.earnings.query_full",
                "Fetch the raw full FMP financial payload for a symbol across annual, quarterly, and TTM sections.",
                {
                    "symbol": {"type": "string"},
                    "limit_annual": {"type": "integer", "default": 1},
                    "limit_quarterly": {"type": "integer", "default": 1},
                    "limit_ttm": {"type": "integer", "default": 1},
                    "limit_single": {"type": "integer", "default": 1},
                    "currency": {"type": "string"},
                },
                required=["symbol"],
            ),
            self._manifest(
                "financial.quote.query",
                "Query latest market quote data for one or more symbols.",
                {
                    "question": {"type": "string"},
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "asset_types": {"type": "array", "items": {"type": "string"}},
                },
            ),
            self._manifest(
                "financial.quote.verified",
                "Cross-validate a financial metric across multiple data sources (yfinance + fin-skill). "
                "Returns the verified value with confidence score, source-level warnings, and verification level. "
                "Use this when you need trustworthy data for valuation (PE, PB, ROE, etc.) rather than raw single-source quotes. "
                "Supported metrics: fwd_pe, ttm_pe, pb, ps, roe, roa, peg, market_cap, dividend_yield, ev_ebitda.",
                {
                    "ticker": {"type": "string", "description": "Stock ticker symbol (e.g., NVDA, AAPL)"},
                    "metric": {"type": "string", "default": "fwd_pe", "description": "Metric to cross-validate (e.g., fwd_pe, ttm_pe, pb, ps, roe)"},
                },
                required=["ticker"],
            ),
            self._manifest(
                "financial.data.health_check",
                "Check the availability of all registered financial data sources (yfinance, fin-skill MCP). "
                "Returns each source's status (available/unavailable), latency, and error messages if any. "
                "Call this BEFORE starting a multi-step analysis to know which data sources are reliable right now. "
                "If a source is down, use the available ones and note the gap in your output.",
                {},
            ),
            self._manifest(
                "financial.memory.append",
                "Append one sentence of memory text to the user's markdown document.",
                {"user_id": {"type": "string"}, "text": {"type": "string"}},
                required=["user_id", "text"],
            ),
            self._manifest(
                "financial.memory.get_document",
                "Fetch the user's markdown memory document.",
                {"user_id": {"type": "string"}},
                required=["user_id"],
            ),
        ]
        return PluginSpec(plugin_id="financial", capabilities=capabilities)

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        known_capabilities = {manifest.capability_id for manifest in self.manifest().capabilities}
        if capability_id not in known_capabilities:
            raise KeyError(capability_id)

        def _handler(request: ToolRequest) -> ToolResult:
            content = self._dispatch(capability_id, request.arguments)
            if isinstance(content, dict) and content.get("success") is False:
                error_code = self._normalize_error_code(content.get("error"))
                return ToolResult(status="error", content=content, error_code=error_code)
            return ToolResult(status="ok", content=content)

        return _handler

    def _dispatch(self, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if capability_id == FINANCIAL_WEBSEARCH_CAPABILITY_ID:
            return self._toolkit.search_multi_provider(
                query=str(arguments.get("query", "")),
                num_results=int(arguments.get("num_results", 10)),
                provider_params=arguments.get("provider_params"),
            )
        if capability_id == "financial.earnings.query":
            return self._toolkit.query_earnings(
                question=str(arguments.get("question", "")),
                symbols=list(arguments.get("symbols", [])),
                period_type=str(arguments.get("period_type", "quarterly")),
                calendar_year=int(arguments.get("calendar_year")) if arguments.get("calendar_year") is not None else None,
                calendar_quarter=str(arguments.get("calendar_quarter")) if arguments.get("calendar_quarter") is not None else None,
                calendar_years=list(arguments.get("calendar_years", [])) if arguments.get("calendar_years") is not None else None,
                recent_count=int(arguments.get("recent_count")) if arguments.get("recent_count") is not None else None,
            )
        if capability_id == "financial.earnings.query_full":
            return self._toolkit.query_earnings_full(
                symbol=str(arguments.get("symbol", "")),
                limit_annual=int(arguments.get("limit_annual", 1)),
                limit_quarterly=int(arguments.get("limit_quarterly", 1)),
                limit_ttm=int(arguments.get("limit_ttm", 1)),
                limit_single=int(arguments.get("limit_single", 1)),
                currency=str(arguments.get("currency")) if arguments.get("currency") is not None else None,
            )
        if capability_id == "financial.quote.query":
            return self._toolkit.query_quote(
                question=str(arguments.get("question", "")),
                symbols=list(arguments.get("symbols", [])),
                asset_types=list(arguments.get("asset_types", [])),
            )
        if capability_id == "financial.quote.verified":
            return self._handle_verified_quote(arguments)
        if capability_id == "financial.data.health_check":
            return self._handle_health_check()
        if capability_id == "financial.memory.append":
            return self._toolkit.append_memory(
                user_id=str(arguments.get("user_id", "")),
                text=str(arguments.get("text", "")),
            )
        if capability_id == "financial.memory.get_document":
            return self._toolkit.get_memory_document(user_id=str(arguments.get("user_id", "")))
        raise KeyError(capability_id)

    def _handle_verified_quote(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ticker = str(arguments.get("ticker", "")).strip().upper()
        metric = str(arguments.get("metric", "fwd_pe")).strip()
        if not ticker:
            return {"success": False, "error": "no_symbol", "message": "ticker is required"}
        if self._data_layer is None:
            return {
                "success": False,
                "error": "finance_data_unavailable",
                "message": "Cross-validation is not available (DataLayer not configured). Use financial.quote.query for single-source data.",
            }
        try:
            verified = asyncio.run(self._data_layer.fetch_verified(ticker, metric))
        except Exception:
            logger.exception("Cross-validation failed ticker=%s metric=%s", ticker, metric)
            return {
                "success": False,
                "error": "finance_provider_error",
                "message": f"Cross-validation failed for {ticker}/{metric}.",
            }
        warnings = list(verified.warnings)
        if verified.excluded_sources:
            warnings.append(f"Excluded sources: {', '.join(verified.excluded_sources)}")
        return {
            "success": True,
            "ticker": ticker,
            "metric": metric,
            "value": verified.value,
            "confidence": verified.confidence,
            "sources": verified.sources,
            "verification_level": verified.verification_level,
            "warnings": warnings,
            "data_source": "cross_validated",
        }

    def _handle_health_check(self) -> dict[str, Any]:
        if self._data_layer is None:
            return {
                "success": False,
                "error": "finance_data_unavailable",
                "message": "DataLayer not configured. Health check unavailable.",
            }
        try:
            health = asyncio.run(self._data_layer.health_check_all())
        except Exception:
            logger.exception("Health check failed")
            return {
                "success": False,
                "error": "finance_provider_error",
                "message": "Health check execution failed.",
            }
        sources = {}
        all_available = True
        for name, h in health.items():
            sources[name] = {
                "available": h.available,
                "latency_ms": h.latency_ms,
                "error": h.error_message,
            }
            if not h.available:
                all_available = False
        return {
            "success": True,
            "all_available": all_available,
            "sources": sources,
        }

    @staticmethod
    def _normalize_error_code(raw_error: Any) -> str:
        normalized = str(raw_error or "").strip() or "finance_provider_error"
        if normalized in KNOWN_FINANCE_ERROR_CODES:
            return normalized
        return "finance_provider_error"

    @staticmethod
    def _manifest(
        capability_id: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
    ) -> ToolSpec:
        return ToolSpec(
            capability_id=capability_id,
            trust_level=ToolTrustLevel.NETWORKED if capability_id.startswith("financial.") else ToolTrustLevel.SAFE,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        )
