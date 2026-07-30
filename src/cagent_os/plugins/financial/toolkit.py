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
import os
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

        items: list[dict[str, Any]] = []
        data_source = "none"

        # ── Tier 1: fin-skill MCP ──
        if self.bridge_available():
            for sym in tickers:
                result = self._call_mcp("get_stock_quote", {"symbol": sym.upper()})
                data = self._parse_mcp_result(result)
                if data:
                    items.append(data)
                else:
                    items.append({"symbol": sym, "error": "no data from MCP"})
            if _has_meaningful_quotes(items):
                data_source = "fin_skill_mcp"

        # ── Tier 2: yfinance fallback ──
        if not _has_meaningful_quotes(items):
            yf_items = self._fetch_yfinance_quotes(tickers)
            if _has_meaningful_quotes(yf_items):
                items = yf_items
                data_source = "yfinance"
            elif not items:
                items = yf_items

        # ── Tier 3: akshare US stock daily fallback ──
        # When yfinance is rate-limited, akshare can still fetch US stock
        # daily OHLCV via Sina Finance. Only price/close is available.
        if not _has_meaningful_quotes(items):
            ak_items = self._fetch_akshare_us_quotes(tickers)
            if _has_meaningful_quotes(ak_items):
                items = ak_items
                data_source = "akshare_us_fallback"

        if not _has_meaningful_quotes(items):
            return _error(
                "finance_empty_result",
                "Finance request returned no valid quote prices from any source (MCP + yfinance + akshare).",
                started,
            )

        return {
            "success": True,
            "question": question,
            "items": items,
            "data_source": data_source,
            "execution_time": round(time.perf_counter() - started, 4),
        }

    def _fetch_yfinance_quotes(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Fallback quote fetch via yfinance (sync, runs in caller's thread).

        yfinance is a free, no-API-key tier-1 data source. It covers
        equities, ETFs, crypto (e.g. BTC-USD), and indices (^GSPC).
        Used when the fin-skill MCP bridge is unavailable or returns no data.
        """
        import yfinance as yf

        items: list[dict[str, Any]] = []
        for sym in tickers:
            try:
                stock = yf.Ticker(sym.upper())
                info = stock.info or {}
                if not info:
                    items.append({"symbol": sym, "error": "yfinance returned empty info"})
                    continue
                items.append({
                    "symbol": sym.upper(),
                    "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "previous_close": info.get("previousClose") or info.get("regularMarketPreviousClose"),
                    "open": info.get("open") or info.get("regularMarketOpen"),
                    "day_high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                    "day_low": info.get("dayLow") or info.get("regularMarketDayLow"),
                    "volume": info.get("volume") or info.get("regularMarketVolume"),
                    "market_cap": info.get("marketCap"),
                    "change": info.get("regularMarketChange"),
                    "change_percent": info.get("regularMarketChangePercent"),
                    "currency": info.get("currency", "USD"),
                    "name": info.get("shortName") or info.get("longName", sym),
                    "exchange": info.get("exchange", ""),
                    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    "fifty_day_avg": info.get("fiftyDayAverage"),
                    "two_hundred_day_avg": info.get("twoHundredDayAverage"),
                })
            except Exception:
                logger.debug("yfinance quote fetch failed for %s", sym, exc_info=True)
                items.append({"symbol": sym, "error": "yfinance fetch failed"})
        return items

    def _fetch_akshare_us_quotes(self, tickers: list[str]) -> list[dict[str, Any]]:
        """Tier 3 fallback: US stock quotes via akshare (Sina Finance US).

        Called when both fin-skill MCP and yfinance fail (e.g. yfinance
        rate-limited). Only provides daily close price — no intraday,
        no PE/PB/market_cap. The returned price is the previous trading
        day's close (US market hours may not have completed yet).

        Non-US tickers (A-shares with digits, HK .HK suffix, crypto -USD)
        are skipped — this fallback is US equity only.
        """
        import re

        items: list[dict[str, Any]] = []
        for sym in tickers:
            sym_upper = sym.upper()
            # Skip non-US tickers: A-shares (contain digits), HK (.HK), crypto (-USD), indices (^)
            if re.search(r"\d", sym_upper) or ".HK" in sym_upper or "-USD" in sym_upper or sym_upper.startswith("^"):
                items.append({"symbol": sym, "error": "akshare_us_skip: not a US equity ticker"})
                continue
            try:
                import akshare as ak
                df = ak.stock_us_daily(symbol=sym_upper, adjust="qfq")
                if df is None or len(df) == 0:
                    items.append({"symbol": sym, "error": "akshare_us: no data"})
                    continue
                last = df.iloc[-1]
                close = float(last.get("close", 0))
                if close == 0:
                    items.append({"symbol": sym, "error": "akshare_us: zero price"})
                    continue
                date_str = str(last.get("date", ""))
                items.append({
                    "symbol": sym_upper,
                    "price": close,
                    "previous_close": close,
                    "currency": "USD",
                    "name": sym_upper,
                    "exchange": "US",
                    "price_as_of": date_str,
                    "source_note": "akshare US daily (previous close, not intraday)",
                })
                logger.info("akshare US fallback quote OK: %s $%.2f (%s)", sym_upper, close, date_str)
            except Exception as exc:
                logger.debug("akshare US fallback failed for %s: %s", sym, exc)
                items.append({"symbol": sym, "error": f"akshare_us: {exc}"})
        return items

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
        combined: list[dict[str, Any]] = []

        # ── Tier 1: Tavily (high-quality semantic search, paid API) ──
        if len(combined) < num_results:
            tavily_results = self._search_tavily(normalized, limit=num_results)
            if tavily_results:
                combined.extend(tavily_results)
                providers_used.append("tavily")
            else:
                providers_failed["tavily"] = "no results or not configured"

        # ── Tier 2: fin-skill MCP market news (free, no API key) ──
        if len(combined) < num_results and self.bridge_available():
            result = self._call_mcp("get_market_news", {"limit": num_results - len(combined)})
            data = self._parse_mcp_result(result)
            mcp_results: list[dict[str, Any]] = []
            if isinstance(data, dict):
                mcp_results = data.get("articles", data.get("news", data.get("results", [])))
            elif isinstance(data, list):
                mcp_results = data
            if mcp_results:
                for item in mcp_results[:num_results - len(combined)]:
                    if isinstance(item, dict):
                        combined.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", item.get("link", "")),
                            "snippet": item.get("summary", item.get("snippet", item.get("description", ""))),
                        })
                providers_used.append("fin_skill_market_news")
            else:
                providers_failed["fin_skill_market_news"] = "no results"
        elif len(combined) >= num_results:
            pass  # already satisfied by Tier 1
        elif not self.bridge_available():
            providers_failed["fin_skill_market_news"] = "bridge unavailable"

        # ── Tier 3: Perplexity (AI-powered search, paid API) ──
        if len(combined) < num_results:
            pplx_results = self._search_perplexity(normalized, limit=num_results - len(combined))
            if pplx_results:
                combined.extend(pplx_results)
                providers_used.append("perplexity")
            else:
                providers_failed["perplexity"] = "no results or not configured"

        # ── Tier 3b: Google CSE (100 free queries/day) ──
        if len(combined) < num_results:
            google_results = self._search_google_cse(normalized, limit=num_results - len(combined))
            if google_results:
                combined.extend(google_results)
                providers_used.append("google_cse")
            else:
                providers_failed["google_cse"] = "no results or not configured"

        # ── Tier 3c: SerpAPI (Google scrape, 250 free queries/month) ──
        if len(combined) < num_results:
            serp_results = self._search_serpapi(normalized, limit=num_results - len(combined))
            if serp_results:
                combined.extend(serp_results)
                providers_used.append("serpapi")
            else:
                providers_failed["serpapi"] = "no results or not configured"

        # ── Tier 3d: AnySearch (unified search, supplementary) ──
        if len(combined) < num_results:
            any_results = self._search_anysearch(normalized, limit=num_results - len(combined))
            if any_results:
                combined.extend(any_results)
                providers_used.append("anysearch")
            else:
                providers_failed["anysearch"] = "no results or not configured"

        # ── Tier 4: DuckDuckGo (free fallback) ──
        if len(combined) < num_results:
            ddg_results = self._search_ddg(normalized, limit=num_results - len(combined))
            if ddg_results:
                combined.extend(ddg_results)
                providers_used.append("duckduckgo_web")
            else:
                providers_failed["duckduckgo_web"] = "no results"
        return {
            "success": True if combined else False,
            "query": normalized,
            "results": combined[:num_results],
            "providers_used": providers_used,
            "providers_failed": providers_failed,
            "provider_params": provider_params or {},
            "execution_time": round(time.perf_counter() - started, 4),
        }

    def _search_tavily(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """High-quality search via Tavily API. Returns empty list if no key or error."""
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            return []
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "include_answer": False,
                },
                proxies=proxies,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Tavily search HTTP %d: %s", resp.status_code, resp.text[:200])
                return results
            data = resp.json()
            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")[:500],
                })
        except Exception:
            logger.debug("Tavily search failed for query: %s", query, exc_info=True)
        return results

    def _search_perplexity(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """AI-powered search via Perplexity Sonar API. Returns empty list if no key or error.

        Uses the chat/completions endpoint with model 'sonar' which returns
        an AI-synthesized answer + citation URLs.
        """
        api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
        if not api_key:
            return []
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [
                        {"role": "system", "content": "You are a financial research assistant. Provide factual, concise answers with sources. Always respond in the same language as the query."},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": 1024,
                },
                proxies=proxies,
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("Perplexity search HTTP %d: %s", resp.status_code, resp.text[:200])
                return results
            data = resp.json()
            # Extract AI answer
            answer = ""
            choices = data.get("choices", [])
            if choices:
                answer = choices[0].get("message", {}).get("content", "")
            # Extract citations (Perplexity returns them at top level)
            citations = data.get("citations", [])
            # Build results: if we have citations, use them; otherwise wrap answer as single result
            if citations:
                for url in citations[:limit]:
                    results.append({
                        "title": url.split("/")[-1][:80] if "/" in url else url[:80],
                        "url": url,
                        "snippet": answer[:500] if not results else "",
                    })
            elif answer:
                # No citations but got an answer — wrap as a single result
                results.append({
                    "title": "Perplexity AI Answer",
                    "url": "https://www.perplexity.ai",
                    "snippet": answer[:500],
                })
        except Exception:
            logger.debug("Perplexity search failed for query: %s", query, exc_info=True)
        return results

    def _search_google_cse(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search via Google Custom Search Engine API. 100 free queries/day.

        Requires GOOGLE_API_KEY + SEARCH_ENGINE_ID env vars.
        Create a CSE at https://programmablesearchengine.google.com/ and
        enable "Search the entire web" for general results.
        """
        api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
        cx = os.environ.get("SEARCH_ENGINE_ID", "").strip()
        if not api_key or not cx:
            return []
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cx,
                    "q": query,
                    "num": min(limit, 10),  # Google CSE max 10 per request
                },
                proxies=proxies,
                timeout=8,
            )
            if resp.status_code != 200:
                logger.warning("Google CSE search HTTP %d: %s", resp.status_code, resp.text[:200])
                return results
            data = resp.json()
            for item in data.get("items", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", "")[:300],
                })
        except Exception:
            logger.debug("Google CSE search failed for query: %s", query, exc_info=True)
        return results

    def _search_serpapi(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search via SerpAPI (Google results scrape). 250 free queries/month.

        Requires SERPAPI_KEY env var. Returns organic_results from Google.
        """
        api_key = os.environ.get("SERPAPI_KEY", "").strip()
        if not api_key:
            return []
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google",
                    "api_key": api_key,
                    "q": query,
                    "num": min(limit, 10),
                },
                proxies=proxies,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("SerpAPI search HTTP %d: %s", resp.status_code, resp.text[:200])
                return results
            data = resp.json()
            for item in data.get("organic_results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", "")[:300],
                })
        except Exception:
            logger.debug("SerpAPI search failed for query: %s", query, exc_info=True)
        return results

    def _search_anysearch(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search via AnySearch API. Supplementary provider for cross-check.

        Requires ANYSEARCH_API_KEY env var. Free anonymous tier available.
        """
        api_key = os.environ.get("ANYSEARCH_API_KEY", "").strip()
        results: list[dict[str, Any]] = []
        proxy = self._settings.effective_proxy if self._settings else ""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.post(
                "https://api.anysearch.com/v1/search",
                headers=headers,
                json={
                    "query": query,
                    "max_results": limit,
                },
                proxies=proxies,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("AnySearch HTTP %d: %s", resp.status_code, resp.text[:200])
                return results
            data = resp.json()
            # Response format may vary — try common keys
            items = data.get("results", data.get("items", data.get("data", [])))
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        results.append({
                            "title": item.get("title", item.get("name", "")),
                            "url": item.get("url", item.get("link", "")),
                            "snippet": item.get("snippet", item.get("content", item.get("description", "")))[:300],
                        })
        except Exception:
            logger.debug("AnySearch failed for query: %s", query, exc_info=True)
        return results

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
