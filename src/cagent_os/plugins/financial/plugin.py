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
    def __init__(self, settings: Settings, toolkit: FinancialToolkit | None = None, data_layer: Any = None, trace_db_path: str = "data/trace.db", memory_api: Any = None) -> None:
        self._settings = settings
        self._toolkit = toolkit or build_financial_toolkit(settings)
        self._data_layer = data_layer
        self._trace_db_path = trace_db_path
        self._memory_api = memory_api

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
                "financial.trace.query",
                "Query the agent's own run history from the trace database. "
                "Returns conversation summaries with query text, outcome, tool counts, "
                "and final output previews. Use this to review past analyses, debug "
                "failed runs, or find patterns across conversations. "
                "Supports: list (recent N), summary (one conv_id), count (stats).",
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Query action: 'list' (recent conversations), 'summary' (one conversation by id), 'count' (total runs)",
                            "default": "list",
                        },
                        "conversation_id": {
                            "type": "string",
                            "description": "Conversation ID for 'summary' action",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 10,
                            "description": "Max results for 'list' action",
                        },
                    },
                    "required": ["action"],
                },
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
                "financial.fred",
                "Query FRED (Federal Reserve Economic Data) for macro indicators. "
                "Provides 21 key US economic series: ONRRP, TGA, bank reserves, Fed balance sheet, "
                "Treasury yields (3M/6M/1Y/2Y/10Y), nonfarm payrolls, unemployment, JOLTS, "
                "labor participation, avg hourly earnings, CPI, PPI, core PCE, GDP, M1, M2. "
                "Fills critical gaps in short-term liquidity analysis. "
                "Use named metrics like 'onrrp', 'cpi', 'unemployment_rate' or 'custom' with a FRED series_id.",
                {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "description": "Named metric (onrrp, tga, bank_reserves, fed_balance_sheet, treasury_3m, treasury_6m, treasury_1y, treasury_2y, treasury_10y, yield_spread_10y2y, nonfarm_payrolls, unemployment_rate, jolts_openings, participation_rate, avg_hourly_earnings, cpi, ppi, core_pce, gdp, m1, m2) or 'custom' with series_id. Also accepts raw FRED series_id directly.",
                        },
                        "series_id": {
                            "type": "string",
                            "description": "FRED series ID (only needed if metric='custom' or using a raw series_id)",
                        },
                        "limit": {
                            "type": "integer",
                            "default": 1,
                            "description": "Number of observations to return (default 1 = latest)",
                        },
                    },
                    "required": ["metric"],
                },
            ),
            self._manifest(
                "financial.memory.save_thesis",
                "Save an investment thesis to memory for future contradiction detection. "
                "After completing a stock/crypto/macro analysis, save key conclusions "
                "with ticker and thesis_type (bullish/bearish/neutral). These are later "
                "checked for contradictions when new analyses are run on the same ticker.",
                {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "Ticker symbol (NVDA, BTC, etc.)"},
                        "thesis_type": {"type": "string", "description": "bullish | bearish | neutral"},
                        "content": {"type": "string", "description": "The core thesis statement (1-3 sentences)"},
                    },
                    "required": ["ticker", "thesis_type", "content"],
                },
            ),
            self._manifest(
                "financial.memory.query_theses",
                "Query stored investment theses for a ticker. Returns all historical "
                "theses saved for that ticker, ordered by most recent first. "
                "Use this before writing a new analysis to check what you previously believed.",
                {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "Ticker symbol to query"},
                    },
                    "required": ["ticker"],
                },
            ),
            self._manifest(
                "financial.memory.check_contradictions",
                "Check if a new analysis conclusion contradicts any stored theses. "
                "Returns a list of detected contradictions (old thesis vs new claim). "
                "Call this AFTER completing an analysis to catch belief drift. "
                "If contradictions are found, surface them to the user for resolution.",
                {
                    "type": "object",
                    "properties": {
                        "analysis_output": {"type": "string", "description": "The full analysis text to check"},
                        "tickers": {"type": "array", "items": {"type": "string"}, "description": "Tickers mentioned in the analysis"},
                    },
                    "required": ["analysis_output", "tickers"],
                },
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
        if capability_id == "financial.trace.query":
            return self._handle_trace_query(arguments)
        if capability_id == "financial.fred":
            return self._handle_fred(arguments)
        if capability_id == "financial.memory.save_thesis":
            return self._handle_save_thesis(arguments)
        if capability_id == "financial.memory.query_theses":
            return self._handle_query_theses(arguments)
        if capability_id == "financial.memory.check_contradictions":
            return self._handle_check_contradictions(arguments)
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

    def _handle_fred(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._data_layer is None:
            return {"success": False, "error": "fred_unavailable", "message": "DataLayer not configured"}
        if "fred" not in self._data_layer.adapter_names:
            return {
                "success": False,
                "error": "fred_unavailable",
                "message": "FRED adapter not registered. Set FRED_API_KEY in .env to enable.",
            }
        fred = self._data_layer.get_adapter("fred")
        metric = str(arguments.get("metric", ""))
        series_id = str(arguments.get("series_id", "")) if arguments.get("series_id") else None
        limit = int(arguments.get("limit", 1))

        async def _fetch():
            kwargs = {"limit": limit}
            if series_id:
                kwargs["series_id"] = series_id
            return await fred.fetch(metric, **kwargs)

        raw = asyncio.run(_fetch())
        if raw.value is None:
            return {
                "success": False,
                "error": "fred_no_data",
                "message": f"No data for metric '{metric}'. Check metric name or use series_id.",
                "raw_response": raw.raw_response,
            }
        return {
            "success": True,
            "metric": metric,
            "series_id": raw.raw_response.get("series_id", ""),
            "value": raw.value,
            "unit": raw.raw_response.get("unit", ""),
            "description": raw.raw_response.get("description", ""),
            "frequency": raw.raw_response.get("frequency", ""),
            "latest_date": raw.raw_response.get("latest_date", ""),
            "fetched_at": raw.fetched_at,
        }

    def _handle_save_thesis(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Save an investment thesis to the memory store."""
        if self._memory_api is None:
            return {"success": False, "error": "memory_unavailable", "message": "Memory API not configured"}
        import asyncio
        from cagent_os.memory.api import InvestmentThesis

        ticker = str(arguments.get("ticker", "")).upper()
        thesis_type = str(arguments.get("thesis_type", ""))
        content = str(arguments.get("content", ""))

        if not ticker or not content:
            return {"success": False, "error": "invalid_input", "message": "ticker and content are required"}

        async def _save():
            thesis = InvestmentThesis(
                user_id="default", ticker=ticker, thesis_type=thesis_type, content=content,
            )
            await self._memory_api.save_thesis(thesis)
            return {"success": True, "ticker": ticker, "message": "Thesis saved to memory"}

        return asyncio.run(_save())

    def _handle_query_theses(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Query stored theses for a ticker."""
        if self._memory_api is None:
            return {"success": False, "error": "memory_unavailable", "message": "Memory API not configured"}
        import asyncio

        ticker = str(arguments.get("ticker", "")).upper()
        if not ticker:
            return {"success": False, "error": "invalid_input", "message": "ticker is required"}

        async def _query():
            theses = await self._memory_api.query_by_ticker("default", ticker)
            return {
                "success": True,
                "ticker": ticker,
                "count": len(theses),
                "theses": [
                    {
                        "ticker": t.ticker,
                        "type": t.thesis_type,
                        "content": t.content,
                        "version": t.version,
                        "created_at": t.created_at.isoformat() if hasattr(t.created_at, 'isoformat') else str(t.created_at),
                    }
                    for t in theses
                ],
            }

        return asyncio.run(_query())

    def _handle_check_contradictions(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Check an analysis for contradictions against stored theses."""
        if self._memory_api is None:
            return {"success": False, "error": "memory_unavailable", "message": "Memory API not configured"}
        import asyncio

        analysis = str(arguments.get("analysis_output", ""))
        tickers = list(arguments.get("tickers", []))

        if not analysis or not tickers:
            return {"success": False, "error": "invalid_input", "message": "analysis_output and tickers are required"}

        async def _check():
            try:
                from cagent_os.memory.contradiction import check_analysis_against_memory
                results = await check_analysis_against_memory(
                    memory=self._memory_api,
                    llm_backend=None,  # LLM check requires backend; without it, skip
                    user_id="default",
                    analysis_output=analysis,
                    tickers=[str(t).upper() for t in tickers],
                )
                return {
                    "success": True,
                    "contradictions_found": len(results),
                    "contradictions": [
                        {
                            "ticker": r.ticker,
                            "old_fact": r.old_fact,
                            "new_fact": r.new_fact,
                            "detected_at": r.detected_at.isoformat() if hasattr(r.detected_at, 'isoformat') else str(r.detected_at),
                            "resolved": r.resolved,
                        }
                        for r in results
                    ],
                }
            except Exception as exc:
                logger.warning("Contradiction check failed: %s", exc)
                return {"success": False, "error": "check_failed", "message": str(exc)}

        return asyncio.run(_check())

    def _handle_trace_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Query trace database for conversation history."""
        import asyncio
        from cagent_os.observability.reader import TraceReader

        action = str(arguments.get("action", "list"))
        conv_id = str(arguments.get("conversation_id", ""))
        limit = int(arguments.get("limit", 10))

        async def _query():
            reader = TraceReader(self._trace_db_path)
            try:
                await reader.open()
                if action == "count":
                    cnt = await reader.count_runs()
                    return {"success": True, "action": "count", "total_runs": cnt}
                elif action == "summary" and conv_id:
                    s = await reader.get_summary(conv_id)
                    if s is None:
                        return {"success": False, "error": "not_found", "message": f"No trace for {conv_id}"}
                    return {
                        "success": True, "action": "summary",
                        "conversation_id": s.conversation_id,
                        "started_at": s.started_at,
                        "ended_at": s.ended_at,
                        "user_query": s.user_query,
                        "final_output_preview": s.final_output_preview,
                        "event_count": s.event_count,
                        "tool_call_count": s.tool_call_count,
                        "tool_failure_count": s.tool_failure_count,
                        "skill_loaded": s.skill_loaded,
                        "outcome": s.outcome,
                    }
                else:  # list
                    items = await reader.list_conversations(limit=limit)
                    return {
                        "success": True,
                        "action": "list",
                        "count": len(items),
                        "conversations": [
                            {
                                "conversation_id": s.conversation_id,
                                "started_at": s.started_at,
                                "user_query": s.user_query[:200] if s.user_query else "",
                                "final_output_preview": s.final_output_preview[:200],
                                "tool_call_count": s.tool_call_count,
                                "outcome": s.outcome,
                            }
                            for s in items
                        ],
                    }
            finally:
                await reader.close()

        return asyncio.run(_query())

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
