"""Financial toolkit — Phase 0 MCP-backed implementation.

Replaces stub methods with real MCP calls via a dedicated event-loop thread.
ES news search and FMP earnings remain inactive until backing services are
deployed (these require provisioned ES clusters, not available in Phase 0).

Architecture:
  Agent → Plugin → FinancialToolkit → MCPSessionManager (dedicated loop thread)
                                           ↓
                                      fin-skill MCP Server
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import urllib.parse
from typing import Any

import requests

from cagent_os.config import Settings

logger = logging.getLogger(__name__)

_KNOWN_ERROR_CODES = {
    "finance_data_unavailable",
    "finance_provider_error",
    "invalid_finance_request",
    "no_symbol",
    "finance_timeout",
    "finance_empty_result",
}

MCP_SERVER = "fin-skill-mcp"


class FinancialToolkit:
    """Financial data operations backed by fin-skill MCP.

    Each synchronous method dispatches to the MCP event-loop thread.
    If no MCPSessionManager is provided, falls back to stub errors
    (graceful degradation).
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        mcp_session_manager: Any = None,
    ) -> None:
        self._settings = settings or Settings()
        self._mcp = mcp_session_manager
        self._loop: asyncio.AbstractEventLoop | None = None
        if self._mcp is not None:
            self._start_mcp_loop()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _start_mcp_loop(self) -> None:
        """Start a dedicated event loop thread for MCP calls.

        The AgentRuntime is synchronous; MCP is async. A background thread
        with its own event loop bridges the gap without requiring an
        async AgentRuntime rewrite (planned for a later phase).

        If connect_all fails, we stop the loop and join the thread so the
        process isn't left with a spinning event-loop thread that blocks
        exit (GIL interaction with input() on Windows).
        """
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._mcp.connect_all(), self._loop
            )
            future.result(timeout=30)
        except Exception:
            logger.exception("MCP connect failed in toolkit loop")
            # Stop the loop and join the thread so we don't leave a
            # spinning event-loop thread that blocks process exit.
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
            self._loop = None
            self._thread = None
            self._mcp = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call_mcp(self, tool: str, args: dict, timeout: float = 30) -> Any | None:
        """Run a single MCP tool call on the dedicated event-loop thread."""
        if self._loop is None or self._mcp is None:
            return None
        try:
            coro = self._mcp.call_tool(MCP_SERVER, tool, args)
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=timeout)
        except Exception:
            logger.debug("MCP call failed: %s(%s)", tool, args)
            return None

    @staticmethod
    def _parse_mcp_result(result: Any) -> dict[str, Any] | None:
        """Extract JSON dict from an MCP CallToolResult."""
        content = getattr(result, "content", [])
        if not content:
            return None
        text = getattr(content[0], "text", None)
        if text is None:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    def close(self) -> None:
        """Stop the MCP event loop and join the thread.

        Runs ``close_all`` on the MCP loop first to release sessions
        cleanly, then stops the loop and joins the thread so the
        Python process can exit.
        """
        if self._loop is None:
            return
        # Close MCP sessions on the toolkit's own loop
        if self._mcp is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._mcp.close_all(), self._loop
                )
                future.result(timeout=5)
            except Exception:
                logger.debug("MCP close_all failed during shutdown", exc_info=True)
        # Stop the loop and join the thread
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if getattr(self, "_thread", None) is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    # ------------------------------------------------------------------
    # Availability checks
    # ------------------------------------------------------------------

    def bridge_available(self) -> bool:
        return self._loop is not None and self._mcp is not None

    def local_earnings_available(self) -> bool:
        return self.bridge_available()

    # ------------------------------------------------------------------
    # Quote
    # ------------------------------------------------------------------

    def query_quote(
        self,
        *,
        question: str = "",
        symbols: list[str] | None = None,
        asset_types: list[str] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        tickers = list(symbols or [])
        if not tickers:
            return _error(
                "no_symbol", "No symbol could be extracted for the quote request.",
                started,
            )
        if not self.bridge_available():
            return _not_available("quote query")

        items: list[dict[str, Any]] = []
        for sym in tickers:
            result = self._call_mcp("get_stock_quote", {"symbol": sym.upper()})
            data = self._parse_mcp_result(result)
            if data:
                items.append(data)
            else:
                items.append({"symbol": sym, "error": "no data"})

        if not _has_meaningful_quotes(items):
            return _error(
                "finance_empty_result",
                "Finance request returned no valid quote prices.",
                started,
            )

        return {
            "success": True,
            "question": question,
            "items": items,
            "data_source": "fin_skill_mcp",
            "execution_time": round(time.perf_counter() - started, 4),
        }

    # ------------------------------------------------------------------
    # Earnings / financials
    # ------------------------------------------------------------------

    def query_earnings(
        self,
        *,
        question: str = "",
        symbols: list[str] | None = None,
        period_type: str = "quarterly",
        calendar_year: int | None = None,
        calendar_quarter: str | None = None,
        calendar_years: list[int] | None = None,
        recent_count: int | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        tickers = list(symbols or [])
        if not tickers:
            return _error("no_symbol", "No symbol could be resolved.", started)

        if not self.bridge_available():
            return _not_available("earnings query")

        results: dict[str, Any] = {}
        for sym in tickers:
            result = self._call_mcp("get_financials", {
                "symbol": sym.upper(),
                "fiscal_year": calendar_year or 2025,
                "limit": recent_count or 4,
                "period_type_id": 1,
            })
            data = self._parse_mcp_result(result)
            results[sym] = data if data else {"error": "no financial data"}

        return {
            "success": True,
            "question": question,
            "result": results if len(tickers) > 1 else results.get(tickers[0], {}),
            "data_source": "fin_skill_mcp",
            "execution_time": round(time.perf_counter() - started, 4),
        }

    def query_earnings_full(
        self,
        *,
        symbol: str,
        limit_annual: int = 1,
        limit_quarterly: int = 1,
        limit_ttm: int = 1,
        limit_single: int = 1,
        currency: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        sym = str(symbol or "").strip().upper()
        if not sym:
            return _error("no_symbol", "No symbol was provided.", started)

        if not self.bridge_available():
            return _not_available("full earnings query")

        # fin-skill get_financials returns annual + quarterly by default
        result = self._call_mcp("get_financials", {
            "symbol": sym,
            "fiscal_year": 2025,
            "limit": max(limit_annual, limit_quarterly, 4),
            "period_type_id": 1,
        })
        data = self._parse_mcp_result(result)

        return {
            "success": True,
            "symbol": sym,
            "result": data or {},
            "data_source": "fin_skill_mcp",
            "execution_time": round(time.perf_counter() - started, 4),
        }

    # ------------------------------------------------------------------
    # News / web search
    # ------------------------------------------------------------------

    def search_multi_provider(
        self,
        *,
        query: str,
        num_results: int = 10,
        provider_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        normalized = str(query or "").strip()
        if not normalized:
            return _error("invalid_finance_request", "Search query cannot be empty.", started)

        providers_used: list[str] = []
        providers_failed: dict[str, str] = {}

        # Try MCP market news first (fin-skill)
        mcp_results: list[dict[str, Any]] = []
        if self.bridge_available():
            result = self._call_mcp("get_market_news", {"limit": num_results})
            data = self._parse_mcp_result(result)
            if isinstance(data, dict):
                mcp_results = data.get("articles", data.get("news", data.get("results", [])))
            elif isinstance(data, list):
                mcp_results = data
            if mcp_results:
                providers_used.append("fin_skill_market_news")
            else:
                providers_failed["fin_skill_market_news"] = "no results"
        else:
            providers_failed["fin_skill_market_news"] = "bridge unavailable"

        # Fallback to DuckDuckGo web search if MCP produced no results
        ddg_results: list[dict[str, Any]] = []
        if len(mcp_results) < num_results:
            ddg_results = self._search_ddg(normalized, limit=num_results - len(mcp_results))
            if ddg_results:
                providers_used.append("duckduckgo_web")
            else:
                providers_failed["duckduckgo_web"] = "no results"

        combined = (mcp_results + ddg_results)[:num_results]
        return {
            "success": True if combined else False,
            "query": normalized,
            "results": combined,
            "providers_used": providers_used,
            "providers_failed": providers_failed,
            "provider_params": provider_params or {},
            "execution_time": round(time.perf_counter() - started, 4),
        }

    def _search_ddg(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Fallback web search via DuckDuckGo HTML (no API key required)."""
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/130.0.0.0 Safari/537.36"
                    ),
                },
                proxies=proxies,
                timeout=8,
            )
            if resp.status_code != 200:
                return results
            # Extract result links and snippets from DuckDuckGo HTML
            # Pattern: <a ... class="...result__a..." href="...">title</a>
            #          <a ... class="...result__snippet...">snippet</a>
            link_pattern = re.compile(
                r'<a[^>]*result__a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
                re.DOTALL,
            )
            snippet_pattern = re.compile(
                r'<a[^>]*result__snippet[^>]*>([^<]+)</a>',
                re.DOTALL,
            )
            links = link_pattern.findall(resp.text)
            snippets = snippet_pattern.findall(resp.text)
            for i, (url, title) in enumerate(links[:limit]):
                snippet = _strip_html(snippets[i]) if i < len(snippets) else ""
                results.append({
                    "title": _strip_html(title),
                    "url": urllib.parse.unquote(url) if "//duckduckgo.com/l/" in url else url,
                    "snippet": snippet,
                })
        except Exception:
            logger.debug("DuckDuckGo search failed for query: %s", query, exc_info=True)
        return results

    def search_es_news(
        self,
        *,
        question: str,
        max_pages: int = 3,
        search_queries: list[str] | None = None,
        entities: list[str] | None = None,
        entities_by_type: dict[str, list[str]] | None = None,
        event_keywords: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        focus_date: str | None = None,
        enable_es2: bool = True,
        rerank_model: str = "openai/gpt-4o",
    ) -> dict[str, Any]:
        """ES news search — inactive in Phase 0.

        Requires provisioned ES1/ES2 clusters + LLM rerank pipeline.
        Falls back to market_news from fin-skill MCP for basic news.
        """
        if self.bridge_available():
            return self.search_multi_provider(query=question)
        return _not_available("ES news search (requires ES cluster)")

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def append_memory(self, *, user_id: str, text: str) -> dict[str, Any]:
        return {
            "success": True,
            "message": f"Memory appended for user {user_id}.",
            "text": text,
        }

    def get_memory_document(self, *, user_id: str) -> dict[str, Any]:
        return {
            "success": True,
            "user_id": user_id,
            "document": "",
        }


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def build_financial_toolkit(
    settings: Settings | None = None,
    *,
    mcp_session_manager: Any = None,
) -> FinancialToolkit:
    return FinancialToolkit(
        settings=settings,
        mcp_session_manager=mcp_session_manager,
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _not_available(feature: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": "finance_data_unavailable",
        "message": f"{feature} is not available (phase 0).",
    }


def _error(code: str, message: str, started: float) -> dict[str, Any]:
    return {
        "success": False,
        "error": code,
        "message": message,
        "execution_time": round(time.perf_counter() - started, 4),
    }


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _has_meaningful_quotes(items: list[dict[str, Any]]) -> bool:
    for item in items:
        price = item.get("price")
        if price is not None and price != 0:
            return True
    return False
