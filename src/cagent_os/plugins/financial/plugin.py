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

# ★ Out-of-coverage institutional explanation template.
# These are CONSTANTS — institutional facts do not change, and the LLM
# should not generate them from scratch (it will fabricate plausible-sounding
# but incorrect explanations). The tool returns this text; the agent relays it.
#
# Correct facts per HK_FINANCIALS_ADAPTER.md:
#   - HKEX Main Board: annual report + interim (semi-annual) report required
#   - HKEX does NOT require standalone Q1/Q3 quarterly reports
#   - Unsponsored ADRs (e.g. TCEHY) are exempt from SEC registration
#   - No CIK = no SEC filings at all (no 20-F, no 6-K, nothing)
_NOT_SEC_REGISTERED_TEMPLATE = """{ticker} is not registered with the SEC — no CIK found in SEC company_tickers.json.

Companies listed only on HKEX follow HKEX disclosure rules, not SEC:
- HKEX Main Board requires: annual reports + interim (semi-annual) reports
- HKEX does NOT require standalone quarterly reports (Q1, Q3)
- Quarterly financial data is structurally unavailable through any SEC-based source

Important — do NOT claim or imply the following (they are false):
- "This company files 20-F with the SEC" — it does not (no CIK = no filings at all)
- "EDGAR only covers annual 20-F for this company" — EDGAR covers nothing for it
- "I can retrieve the latest fiscal year data via EDGAR" — no data exists to retrieve

Acceptable response format:
1. State that the data is structurally unavailable
2. Quote the institutional reason above (HKEX rules, not SEC-registered)
3. Offer alternative: annual data may be available from HKEX news platform or company IR page (non-EDGAR source, lower reliability)
4. Do NOT fabricate numbers, use estimates, or promise EDGAR data that does not exist""".strip()

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
    def __init__(self, settings: Settings, toolkit: FinancialToolkit | None = None, data_layer: Any = None, trace_db_path: str = "data/trace.db", memory_api: Any = None, rag_service: Any = None) -> None:
        self._settings = settings
        self._toolkit = toolkit or build_financial_toolkit(settings)
        self._data_layer = data_layer
        self._trace_db_path = trace_db_path
        self._memory_api = memory_api
        self._rag_service = rag_service
        self._rag_status_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}  # (user_id, session_id) → (cached_at, status)
        self._RAG_STATUS_CACHE_TTL = 600  # 10 minutes

    def manifest(self) -> PluginSpec:
        capabilities = [
            self._manifest(
                FINANCIAL_WEBSEARCH_CAPABILITY_ID,
                "Search finance-aware public web sources across providers.",
                {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer", "default": 10},
                    "provider_params": {"type": "object", "additionalProperties": True},
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
                required=["action"],
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
                required=["metric"],
            ),
            self._manifest(
                "financial.rag.search",
                "Search the local RAG knowledge base for relevant content. "
                "Returns top-ranked text chunks from ingested articles, research reports, "
                "and assetized facts/opinions/frameworks. "
                "Use this BEFORE external web search to retrieve previously-read analysis. "
                f"Currently indexed: {self._rag_service.chunk_count if self._rag_service else 0} chunks.",
                {
                    "query": {"type": "string", "description": "Natural language query"},
                    "top_k": {"type": "integer", "default": 5, "description": "Number of results (default 5, max 20)"},
                    "chunk_type_filter": {"type": "string", "description": "Optional filter by chunk type"},
                },
                required=["query"],
            ),
            self._manifest(
                "financial.rag.status",
                "Check the RAG knowledge base status: number of indexed chunks, "
                "embedding model, and whether search is available. "
                "Call this at the start of a session to know what knowledge is available.",
                {},
            ),
            self._manifest(
                "financial.memory.save_thesis",
                "Save an investment thesis to memory for future contradiction detection. "
                "After completing a stock/crypto/macro analysis, save key conclusions "
                "with ticker and thesis_type (bullish/bearish/neutral). These are later "
                "checked for contradictions when new analyses are run on the same ticker.",
                {
                        "ticker": {"type": "string", "description": "Ticker symbol (NVDA, BTC, etc.)"},
                        "thesis_type": {"type": "string", "description": "bullish | bearish | neutral"},
                        "content": {"type": "string", "description": "The core thesis statement (1-3 sentences)"},
                },
                required=["ticker", "thesis_type", "content"],
            ),
            self._manifest(
                "financial.memory.query_theses",
                "Query stored investment theses for a ticker. Returns all historical "
                "theses saved for that ticker, ordered by most recent first. "
                "Use this before writing a new analysis to check what you previously believed.",
                {
                        "ticker": {"type": "string", "description": "Ticker symbol to query"},
                },
                required=["ticker"],
            ),
            self._manifest(
                "financial.memory.check_contradictions",
                "Check if a new analysis conclusion contradicts any stored theses. "
                "Returns a list of detected contradictions (old thesis vs new claim). "
                "Call this AFTER completing an analysis to catch belief drift. "
                "If contradictions are found, surface them to the user for resolution.",
                {
                        "analysis_output": {"type": "string", "description": "The full analysis text to check"},
                        "tickers": {"type": "array", "items": {"type": "string"}, "description": "Tickers mentioned in the analysis"},
                },
                required=["analysis_output", "tickers"],
            ),
            self._manifest(
                "financial.memory.append",
                "Append one sentence of memory text to the user's markdown document.",
                {"text": {"type": "string"}},
                required=["text"],
            ),
            self._manifest(
                "financial.memory.get_document",
                "Fetch the user's markdown memory document.",
                {},
            ),
            self._manifest(
                "financial.edgar.facts",
                "Get authoritative financial statements from SEC EDGAR (free, no API key). "
                "Returns audited revenue, net_income, EPS, assets, equity, cash_flow, etc. "
                "Each metric includes: value, currency (USD/CNY), start/end dates, form (10-K/20-F), "
                "audited flag, accession number (for traceability), and tag_used (XBRL tag). "
                "This is the PRIMARY source for financial report data — use before fin-skill or websearch. "
                "Supports both US domestic (10-K, us-gaap) and foreign private issuers (20-F, ifrs-full).",
                {
                    "ticker": {"type": "string", "description": "Stock symbol, e.g. AAPL, NVDA, XPEV, BABA"},
                    "fiscal_year": {"type": "integer", "description": "Target fiscal year (e.g. 2025). Optional — defaults to latest."},
                    "fiscal_period": {"type": "string", "description": "FY (annual, default), Q1, Q2, Q3"},
                },
                required=["ticker"],
            ),
            self._manifest(
                "financial.edgar.release",
                "Get earnings press release data from SEC EDGAR 6-K/8-K filings. "
                "Extracts quarterly revenue, net income, gross profit, operating income, cost of sales, "
                "EPS, and company guidance from the Business Outlook section. "
                "Data is unaudited (press release) with full traceability to accession + document. "
                "This is the PRIMARY source for quarterly breakdown data — use before fin-skill or websearch. "
                "Currency: native reporting currency (CNY for XPEV/BABA, USD for AAPL). "
                "FX rate captured from footnote when USD convenience translation is present.",
                {
                    "ticker": {"type": "string", "description": "Stock symbol, e.g. XPEV, AAPL, BABA"},
                    "quarter_end": {"type": "string", "description": "Quarter end date in YYYY-MM-DD format. Q1=03-31, Q2=06-30, Q3=09-30, Q4=12-31."},
                },
                required=["ticker", "quarter_end"],
            ),
            self._manifest(
                "financial.ashare.report",
                "Get A-share (China) financial report data via akshare → Sina Finance. "
                "Returns balance sheet, income statement, and cash flow statement data "
                "for a Chinese-listed stock. All reports are cumulative by default — "
                "single-quarter values are computed via differencing. "
                "Metrics include: 营业总收入, 营业收入, 净利润, 归属于母公司所有者的净利润, "
                "营业利润, 资产总计, 负债合计, 经营活动现金流量净额, etc. "
                "accounting_standard=CAS, source_tier=secondary (akshare is aggregator, "
                "not primary source).",
                {
                    "ticker": {"type": "string", "description": "A-share stock code, e.g. 600519, 000001"},
                },
                required=["ticker"],
            ),
        ]
        return PluginSpec(plugin_id="financial", capabilities=capabilities)

    def handler(self, capability_id: str) -> Callable[[ToolRequest], ToolResult]:
        known_capabilities = {manifest.capability_id for manifest in self.manifest().capabilities}
        if capability_id not in known_capabilities:
            raise KeyError(capability_id)

        def _handler(request: ToolRequest) -> ToolResult:
            content = self._dispatch(capability_id, request.arguments, request_context=request.context)
            if isinstance(content, dict) and content.get("success") is False:
                error_code = self._normalize_error_code(content.get("error"))
                return ToolResult(status="error", content=content, error_code=error_code)
            return ToolResult(status="ok", content=content)

        return _handler

    def _dispatch(self, capability_id: str, arguments: dict[str, Any], request_context: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if capability_id == "financial.rag.search":
            return self._handle_rag_search(arguments)
        if capability_id == "financial.rag.status":
            return self._handle_rag_status(request_context)
        if capability_id == "financial.fred":
            return self._handle_fred(arguments)
        if capability_id == "financial.memory.save_thesis":
            return self._handle_save_thesis(arguments, request_context)
        if capability_id == "financial.memory.query_theses":
            return self._handle_query_theses(arguments, request_context)
        if capability_id == "financial.memory.check_contradictions":
            return self._handle_check_contradictions(arguments, request_context)
        if capability_id == "financial.memory.append":
            return self._handle_memory_append(arguments, request_context)
        if capability_id == "financial.memory.get_document":
            return self._handle_get_document(arguments, request_context)

        if capability_id == "financial.edgar.facts":
            return self._handle_edgar_facts(arguments)
        if capability_id == "financial.edgar.release":
            return self._handle_edgar_release(arguments)
        if capability_id == "financial.ashare.report":
            return self._handle_ashare_report(arguments)
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

    # ★ Similarity floor: top-1 < 0.5 → treat as miss, discard all results.
    # This is a hard code-level filter, not just a prompt suggestion.
    # Low-similarity chunks injected into context cause the model to fabricate
    # false depth (e.g. XPEV revenue question → "AI supercycle value chain").
    _RAG_SIMILARITY_FLOOR = 0.5

    def _handle_rag_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Search the RAG knowledge base."""
        if self._rag_service is None:
            return {"success": False, "error": "rag_unavailable", "message": "RAG service not configured"}
        query = str(arguments.get("query", ""))
        top_k = int(arguments.get("top_k", 5))
        chunk_filter = arguments.get("chunk_type_filter")
        if not query:
            return {"success": False, "error": "invalid_input", "message": "query is required"}
        where = {"chunk_type": chunk_filter} if chunk_filter else None
        results = self._rag_service.search(query, top_k=min(top_k, 20), where=where)

        # ★ Hard similarity floor: top-1 < 0.5 → no relevant match, discard all
        top_similarity = results[0]["similarity"] if results else 0.0
        if top_similarity < self._RAG_SIMILARITY_FLOOR:
            return {
                "success": True, "query": query,
                "results_count": 0, "results": [],
                "formatted_context": "",
                "reason": "no_relevant_match",
                "top_similarity": round(top_similarity, 4),
                "threshold": self._RAG_SIMILARITY_FLOOR,
            }

        formatted = self._rag_service.format_context(results, max_results=top_k)
        return {
            "success": True, "query": query, "results_count": len(results),
            "results": [
                {
                    "rank": i + 1, "title": r["metadata"].get("title", "?"),
                    "source": r["metadata"].get("source", ""),
                    "chunk_type": r["metadata"].get("chunk_type", ""),
                    "section": r["metadata"].get("section", ""),
                    "date": r["metadata"].get("date", ""),
                    "similarity": round(r["similarity"], 4),
                    "text_preview": r["text"][:300],
                }
                for i, r in enumerate(results)
            ],
            "formatted_context": formatted,
        }

    def _handle_rag_status(self, request_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return RAG system status, cached per (user, session) with TTL.

        rag.status is expensive (reads chunk_count) yet its result is nearly 
        invariant within a session. Cache by (user_id, session_id) for isolation;
        TTL ensures stale cache after index rebuild or service restart.
        """
        if self._rag_service is None:
            return {"success": True, "available": False, "message": "RAG not configured"}

        import time
        user_id = str(request_context.get("user_id", "")) if request_context else ""
        session_id = str(request_context.get("session_id", "")) if request_context else ""
        cache_key = (user_id, session_id)

        if cache_key[0] and cache_key[1] and cache_key in self._rag_status_cache:
            cached_at, cached = self._rag_status_cache[cache_key]
            if time.time() - cached_at < self._RAG_STATUS_CACHE_TTL:
                if cached.get("available") and cached.get("chunks", 0) > 0:
                    return {"success": True, **cached}

        status = dict(self._rag_service.status)
        if cache_key[0] and cache_key[1]:
            self._rag_status_cache[cache_key] = (time.time(), status)
        return {"success": True, **status}

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

    def _handle_edgar_facts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle financial.edgar.facts — EDGAR authoritative financial data.

        Degradation: EDGAR → fin-skill MCP (with source labeling).
        """
        import time as _time
        started = _time.perf_counter()

        ticker = str(arguments.get("ticker", "")).strip().upper()
        if not ticker:
            return {"success": False, "error": "no_symbol", "message": "ticker is required"}

        fy = int(arguments["fiscal_year"]) if arguments.get("fiscal_year") else None
        fp = str(arguments.get("fiscal_period", "FY"))

        # ★ Code-level SEC registration check (replaces prompt-based routing).
        # If the ticker has no CIK in SEC's company_tickers.json, it is NOT
        # registered with the SEC — EDGAR data is structurally unavailable.
        # This blocks the 5+ doomed tool calls that prompt-based routing
        # could not prevent, because prompt rules are advisory, not enforced.
        from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter
        adapter = EdgardAdapter()
        if not adapter.has_sec_cik(ticker):
            return {
                "success": False,
                "error": "not_sec_registered",
                "unavailable": True,
                "reason": "institutional",
                "message": _NOT_SEC_REGISTERED_TEMPLATE.format(ticker=ticker),
                "execution_time": round(_time.perf_counter() - started, 4),
            }

        # Try EDGAR first (authoritative, free)
        try:
            result = asyncio.run(adapter.get_earnings_summary(ticker, fiscal_year=fy, fiscal_period=fp))
            if "error" not in result and result.get("metrics"):
                result["execution_time"] = round(_time.perf_counter() - started, 4)
                return result
            # EDGAR returned no data — fall through to fin-skill
            logger.info("EDGAR no data for %s, falling back to fin-skill", ticker)
        except Exception as exc:
            logger.warning("EDGAR failed for %s: %s — falling back to fin-skill", ticker, exc)

        # Degradation: fin-skill MCP (must label source degradation)
        fin_result = self._toolkit.query_earnings(
            question=f"EDGAR fallback for {ticker}",
            symbols=[ticker],
            calendar_year=fy,
        )
        if fin_result.get("success"):
            fin_result["source"] = "fin_skill_mcp"
            fin_result["degraded_from"] = "edgar"
            fin_result["degradation_reason"] = "EDGAR unavailable or no data"
        fin_result["execution_time"] = round(_time.perf_counter() - started, 4)
        return fin_result

    # ── Memory handlers (user-scoped) ────────────────────────────

    @staticmethod
    def _extract_user_id(request_context: dict[str, Any] | None) -> str:
        """Extract user_id from request context. Hard-reject if absent.

        Mirrors the safe pattern in plugins/memory/plugin.py.
        LLM arguments are NEVER trusted for user identity.
        """
        if not request_context:
            return ""
        return str(request_context.get("user_id", "")).strip()

    def _handle_save_thesis(self, arguments: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
        """Save an investment thesis to the memory store."""
        user_id = self._extract_user_id(request_context)
        if not user_id:
            return {"success": False, "error": "missing_user_id",
                    "message": "User identity is required for memory operations"}

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
                user_id=user_id, ticker=ticker, thesis_type=thesis_type, content=content,
            )
            await self._memory_api.save_thesis(thesis)
            return {"success": True, "ticker": ticker, "message": "Thesis saved to memory"}

        return asyncio.run(_save())

    def _handle_query_theses(self, arguments: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
        """Query stored theses for a ticker."""
        user_id = self._extract_user_id(request_context)
        if not user_id:
            return {"success": False, "error": "missing_user_id",
                    "message": "User identity is required for memory operations"}

        if self._memory_api is None:
            return {"success": False, "error": "memory_unavailable", "message": "Memory API not configured"}
        import asyncio

        ticker = str(arguments.get("ticker", "")).upper()
        if not ticker:
            return {"success": False, "error": "invalid_input", "message": "ticker is required"}

        async def _query():
            theses = await self._memory_api.query_by_ticker(user_id, ticker)
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

    def _handle_check_contradictions(self, arguments: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
        """Check an analysis for contradictions against stored theses."""
        user_id = self._extract_user_id(request_context)
        if not user_id:
            return {"success": False, "error": "missing_user_id",
                    "message": "User identity is required for memory operations"}

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
                    llm_backend=None,
                    user_id=user_id,
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

    def _handle_memory_append(self, arguments: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
        """Append memory text — user-scoped from context, NOT from LLM args."""
        user_id = self._extract_user_id(request_context)
        if not user_id:
            return {"success": False, "error": "missing_user_id",
                    "message": "User identity is required for memory operations"}
        return self._toolkit.append_memory(
            user_id=user_id,
            text=str(arguments.get("text", "")),
        )

    def _handle_get_document(self, arguments: dict[str, Any], request_context: dict[str, Any] | None) -> dict[str, Any]:
        """Get memory document — user-scoped from context, NOT from LLM args."""
        user_id = self._extract_user_id(request_context)
        if not user_id:
            return {"success": False, "error": "missing_user_id",
                    "message": "User identity is required for memory operations"}
        return self._toolkit.get_memory_document(user_id=user_id)

    def _handle_edgar_release(self, arguments: dict[str, Any], request_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Handle financial.edgar.release — earnings press release data.

        Pipeline: S3 (find) → download → extract (S4-S8 + G4).
        """
        import time as _time
        started = _time.perf_counter()

        ticker = str(arguments.get("ticker", "")).strip().upper()
        quarter_end = str(arguments.get("quarter_end", "")).strip()

        if not ticker:
            return {"success": False, "error": "no_ticker", "message": "ticker is required"}
        if not quarter_end:
            return {"success": False, "error": "no_quarter", "message": "quarter_end is required (YYYY-MM-DD)"}

        # ★ Code-level SEC registration check — same gate as edgar.facts.
        from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter
        adapter = EdgardAdapter()
        if not adapter.has_sec_cik(ticker):
            return {
                "success": False,
                "error": "not_sec_registered",
                "unavailable": True,
                "reason": "institutional",
                "message": _NOT_SEC_REGISTERED_TEMPLATE.format(ticker=ticker),
                "execution_time": round(_time.perf_counter() - started, 4),
            }

        # Check offline cache first (F4: materialized extraction results).
        # SEC documents are immutable by accession — cached results are always valid.
        from cagent_os.data_layer.lane2.materializer import EdgarReleaseStore
        store = EdgarReleaseStore()
        cached = store.get(ticker, quarter_end)
        if cached:
            cached["execution_time"] = round(_time.perf_counter() - started, 4)
            return cached

        try:
            # Step 1: Find the earnings release document (S3 Phase 1)
            from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder
            finder = EarningsReleaseFinder()
            release = asyncio.run(finder.find(ticker, quarter_end))
            if not release or not release.get("found"):
                entity_type = (release or {}).get("entity_type", "")
                if entity_type == "foreign_private_issuer":
                    # FPI quarterly data from fin-skill may be extrapolated.
                    # Refuse degradation — missing data is visible; wrong data is silent.
                    return {
                        "success": False,
                        "error": "no_release_found_fpi",
                        "message": (
                            f"No earnings release found for {ticker} Q ending {quarter_end}. "
                            "FPI (foreign private issuer) quarterly data is NOT degraded "
                            "to fin-skill to avoid extrapolated/estimated values from "
                            "third-party aggregators. Use financial.edgar.facts for "
                            "audited annual data from 20-F filings."
                        ),
                        "entity_type": entity_type,
                        "degradation_blocked": True,
                        "degradation_reason": "FPI quarterly data may be extrapolated",
                    }
                return {
                    "success": False,
                    "error": "no_release_found",
                    "message": f"No earnings release found for {ticker} Q ending {quarter_end}",
                    "entity_type": entity_type,
                }

            # Step 2: Download the EX-99.1 document
            import requests
            resp = requests.get(
                release["url"],
                headers={"User-Agent": "CagentOS madaocage@gmail.com"},
                timeout=30,
            )
            if resp.status_code != 200:
                return {
                    "success": False,
                    "error": "download_failed",
                    "message": f"Failed to download {release['url']}: HTTP {resp.status_code}",
                }

            # Step 3: Extract financial data from HTML
            from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
            extractor = EarningsReleaseExtractor()
            meta = {
                "accession": release["accession"],
                "document": release["document"],
                "form": release["form"],
                "filing_date": release["filing_date"],
                "ticker": ticker,
            }
            extracted = extractor.extract(resp.content, meta=meta)

            # Build response
            # ★ accounting_standard is issuer-level, not document-level.
            # Look up by CIK (same company uses same standard across all filings).
            from cagent_os.data_layer.adapters.edgar_adapter import get_issuer_accounting_standard
            issuer_std = asyncio.run(get_issuer_accounting_standard(ticker))

            records_out = []
            # ★ Field-level merge: the extractor produces records from
            # different tables in the same filing. Raw CNY tables have
            # revenue + gross_profit but no net_income. Billion-scale
            # "Key Financial Results" tables have revenue + net_income
            # but no gross_profit. Merging by (period_end, period_type)
            # at field level preserves all available data.
            _FINANCIAL_FIELDS = (
                "revenue", "cost_of_sales", "gross_profit",
                "operating_income", "net_income", "eps_diluted",
                "fx_rate",
            )
            from collections import defaultdict as _dd
            period_groups: dict[tuple[str, str], list[dict]] = _dd(list)
            for r in extracted.records:
                period_groups[(r.period_end or "", r.period_type or "")].append({
                    "period_start": r.period_start,
                    "period_end": r.period_end,
                    "period_type": r.period_type,
                    "currency": r.currency,
                    "fx_rate": r.fx_rate,
                    "fx_rate_date": r.fx_rate_date,
                    "revenue": r.metrics.get("revenue"),
                    "cost_of_sales": r.metrics.get("cost_of_sales"),
                    "gross_profit": r.metrics.get("gross_profit"),
                    "operating_income": r.metrics.get("operating_income"),
                    "net_income": r.metrics.get("net_income"),
                    "eps_diluted": r.metrics.get("eps_diluted"),
                    "extraction_method": r.extraction_method,
                    # ★ Issuer-level attributes (same for all records from this CIK)
                    "accounting_standard": issuer_std,
                    "audited": False,  # Press releases are never audited
                })

            for per_key, recs in period_groups.items():
                if len(recs) == 1:
                    records_out.append(recs[0])
                    continue

                # Multiple records for same period: field-level merge.
                # Identify the "primary" record (has raw-scale revenue, > 1e6).
                primary = None
                secondary = None
                for rec in recs:
                    rev = rec.get("revenue")
                    if rev is not None and isinstance(rev, (int, float)) and rev > 1e6:
                        primary = rec
                    elif rev is not None and isinstance(rev, (int, float)):
                        secondary = rec

                if primary is None:
                    primary = recs[0]  # fallback

                merged = dict(primary)  # start with primary
                if secondary is not None:
                    # ★ Validate scale: revenue ratio should be ~1e9 (billion → raw CNY).
                    # Use FIXED 1e9 for conversion — a computed ratio embeds
                    # rounding error from the source's 2-significant-digit precision
                    # and creates false precision (510086161.35 instead of 510000000).
                    # The ratio is ONLY used as a validation check.
                    p_rev = primary.get("revenue")
                    s_rev = secondary.get("revenue")
                    if p_rev and s_rev and s_rev != 0:
                        ratio = p_rev / s_rev
                        if not (0.99e9 <= ratio <= 1.01e9):
                            logger.warning(
                                "Scale ratio out of range for %s %s: %.0f (expected ~1e9). "
                                "Falling back to computed ratio.",
                                ticker, quarter_end, ratio,
                            )
                            scale = ratio
                        else:
                            scale = 1e9  # fixed, not computed
                    else:
                        scale = 1e9  # no revenue anchor, assume billion
                    # Import fields from secondary that primary is missing
                    for field in _FINANCIAL_FIELDS:
                        if merged.get(field) is None and secondary.get(field) is not None:
                            merged[field] = secondary[field] * scale
                            # ★ Tag precision: billion-scale source has only
                            # 2 significant digits. The ×1e9 conversion makes
                            # this explicit rather than hidden in the last 7 digits.
                            if merged.get("_precision") is None:
                                merged["_precision"] = {}
                            merged["_precision"][field] = "2_sig_digits_from_billion"

                records_out.append(merged)

            # ★ Regression guard: quarterly records should carry net_income.
            # A previous bug (record-level dedup) silently dropped the
            # billion-scale records that were the only source of quarterly
            # net_income. This is a runtime WARNING — missing net_income is
            # possible (early filings, ex992 boundaries). The HARD assertion
            # lives in tests, where a known fixture (XPEV Q4 2025) should
            # always have quarterly net_income.
            quarter_recs = [r for r in records_out if r.get("period_type") == "quarter"]
            if quarter_recs and all(r.get("net_income") is None for r in quarter_recs):
                logger.warning(
                    "All %d quarterly records have net_income=None for %s QE %s. "
                    "This may indicate a field-level merge failure or sparse filing.",
                    len(quarter_recs), ticker, quarter_end,
                )

            guidance_out = []
            for g in extracted.guidance:
                guidance_out.append({
                    "period_label": g.period_label,
                    "metric_name": g.metric_name,
                    "low": g.low,
                    "high": g.high,
                    "currency": g.currency,
                    "yoy_change_low": g.yoy_change_low,
                    "yoy_change_high": g.yoy_change_high,
                    "extraction_conf": g.extraction_conf,
                })

            result = {
                "success": True,
                "ticker": ticker,
                "quarter_end": quarter_end,
                "source": "edgar_release",
                "source_tier": "primary",
                "accession": release["accession"],
                "document": release["document"],
                "filing_date": release["filing_date"],
                "form": release["form"],
                "conf": release["conf"],
                "audited": False,
                "accounting_standard": issuer_std,
                "records": records_out,
                "guidance": guidance_out,
                "record_count": len(records_out),
                "guidance_count": len(guidance_out),
                "execution_time": round(_time.perf_counter() - started, 4),
            }

            # Cache result for future queries (F4: offline materialization)
            store.put(ticker, quarter_end, result)

            return result
        except Exception as exc:
            logger.exception("EDGAR release extraction failed for %s Q ending %s",
                             ticker, quarter_end)
            return {
                "success": False,
                "error": "extraction_failed",
                "message": str(exc),
            }

    def _handle_ashare_report(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle financial.ashare.report — A-share financial statements."""
        import asyncio as _asyncio
        import time as _time

        started = _time.perf_counter()
        ticker = str(arguments.get("ticker", "")).strip()
        if not ticker:
            return {"success": False, "error": "no_ticker", "message": "ticker is required"}

        try:
            from cagent_os.data_layer.adapters.akshare_financials_adapter import (
                AkshareFinancialsAdapter,
            )
            adapter = AkshareFinancialsAdapter()
            raw = _asyncio.run(adapter.fetch("financials", ticker=ticker))
        except Exception as exc:
            logger.exception("A-share report fetch failed for %s", ticker)
            return {
                "success": False,
                "error": "ashare_fetch_failed",
                "message": str(exc),
            }

        if raw.value is None:
            return {
                "success": False,
                "error": "ashare_no_data",
                "message": str(raw.raw_response.get("error", "Unknown error")),
            }

        data = raw.value
        # ★ Strip internal reconciliation data — not agent-consumable.
        # FactRegistry would register reconciliation check values as
        # spurious facts (e.g., "expected=319918844905.58" as a fact).
        if "records" in data:
            for p in data["records"]:
                p.pop("reconciliation", None)
        data["execution_time"] = round(_time.perf_counter() - started, 4)
        return data

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
                **({"required": required} if required else {}),
            },
        )
